from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.clients.http_client import ExternalServiceError
from app.config import ConfigManager, is_effective_value, is_placeholder_only


class PlayerClient:
    """本机播放器（如 MPC-HC）进程拉起与观看时长回写封装。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        popen_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._cfg = config_manager
        self._popen = popen_factory

    def resolve_executable(self, path_override: str | None = None) -> str | None:
        raw = (path_override if path_override is not None else self._cfg.settings.player_path).strip()
        if not is_effective_value(raw):
            return None
        candidate = Path(raw)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(raw)
        return found

    def check_connection(self, player_path: str | None = None) -> tuple[bool, str, dict[str, Any]]:
        raw = (player_path if player_path is not None else self._cfg.settings.player_path).strip()
        if not is_effective_value(raw):
            if is_placeholder_only(raw):
                return False, f"播放器路径当前为占位值（{raw}），请填写本机播放器可执行文件路径", {}
            return False, "请填写本机播放器可执行文件路径（例如 MPC-HC 的 mpc-hc64.exe）", {}

        resolved = self.resolve_executable(raw)
        if not resolved:
            return False, f"未找到播放器可执行文件：{raw}", {}

        exe_name = Path(resolved).name
        return True, f"播放器就绪：{exe_name}（{resolved}）", {"executable": resolved, "name": exe_name}

    def launch_stream(
        self,
        stream_url: str,
        *,
        start_seconds: int = 0,
        on_session_update: Callable[[int], None] | None = None,
    ) -> dict[str, Any]:
        exe = self.resolve_executable()
        if not exe:
            raise ExternalServiceError("Player", "未找到可用播放器，请前往“设置”确认本地播放器路径")
        if not stream_url:
            raise ExternalServiceError("Player", "未能获取到可播放的流媒体地址")

        exe_lower = Path(exe).name.lower()
        cmd = [exe, stream_url]
        if ("mpc-hc" in exe_lower or "mpc-be" in exe_lower) and start_seconds > 5:
            cmd.extend(["/play", "/start", str(int(start_seconds) * 1000)])

        try:
            proc = self._popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ExternalServiceError("Player", f"启动播放器失败：{exc}") from exc

        pid = getattr(proc, "pid", None)

        # 启动轻量级后台监测线程，按实际观看秒数自动累加回写观看进度
        if on_session_update is not None and hasattr(proc, "poll"):
            watcher = threading.Thread(
                target=self._watch_player_process,
                args=(proc, int(start_seconds or 0), on_session_update),
                daemon=True,
            )
            watcher.start()

        return {
            "pid": pid,
            "executable": exe,
            "player_name": Path(exe).name,
            "command": cmd,
        }

    @staticmethod
    def _watch_player_process(
        proc: Any,
        initial_seconds: int,
        on_session_update: Callable[[int], None],
    ) -> None:
        started = time.monotonic()
        last_reported = 0
        try:
            while proc.poll() is None:
                time.sleep(5.0)
                elapsed = int(time.monotonic() - started)
                if elapsed - last_reported >= 10:
                    last_reported = elapsed
                    on_session_update(initial_seconds + elapsed)
            total_elapsed = int(time.monotonic() - started)
            if total_elapsed >= 3:
                on_session_update(initial_seconds + total_elapsed)
        except Exception:
            pass
