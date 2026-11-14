from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_VALUES = {
    "",
    "to_do",
    "todo",
    "your_api_key",
    "your_token",
    "changeme",
    "replace_me",
    "none",
    "null",
}

MANAGED_ENV_KEYS = (
    "ALIST_URL",
    "ALIST_USERNAME",
    "ALIST_PASSWORD",
    "TMDB_TOKEN",
    "MDBLIST_APIKEY",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_API",
    "PLAYER_PATH",
)


def is_effective_value(value: str | None) -> bool:
    """判断配置值是否为非空且非占位的有效值。"""
    if value is None:
        return False
    cleaned = value.strip()
    if not cleaned:
        return False
    return cleaned.lower() not in PLACEHOLDER_VALUES


def is_placeholder_only(value: str | None) -> bool:
    """判断配置值是否显式填写了类似 to_do 的占位符。"""
    if value is None:
        return False
    cleaned = value.strip()
    return bool(cleaned) and cleaned.lower() in PLACEHOLDER_VALUES


@dataclass(frozen=True)
class AppSettings:
    alist_url: str = "http://127.0.0.1:5244"
    alist_username: str = "admin"
    alist_password: str = ""
    tmdb_token: str = ""
    mdblist_apikey: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_api: str = "chat_completions"
    player_path: str = ""
    app_host: str = "127.0.0.1"
    app_port: int = 5000
    secret_key: str = "yingku-local-session-secret"

    @property
    def alist_ready(self) -> bool:
        return is_effective_value(self.alist_url) and is_effective_value(self.alist_username)

    @property
    def tmdb_ready(self) -> bool:
        return is_effective_value(self.tmdb_token)

    @property
    def mdblist_ready(self) -> bool:
        return is_effective_value(self.mdblist_apikey)

    @property
    def llm_ready(self) -> bool:
        return is_effective_value(self.llm_base_url) and is_effective_value(self.llm_api_key)

    @property
    def player_ready(self) -> bool:
        return is_effective_value(self.player_path)

    @property
    def required_ready(self) -> bool:
        return self.alist_ready and self.tmdb_ready

    def to_env_dict(self) -> dict[str, str]:
        return {
            "ALIST_URL": self.alist_url,
            "ALIST_USERNAME": self.alist_username,
            "ALIST_PASSWORD": self.alist_password,
            "TMDB_TOKEN": self.tmdb_token,
            "MDBLIST_APIKEY": self.mdblist_apikey,
            "LLM_BASE_URL": self.llm_base_url,
            "LLM_API_KEY": self.llm_api_key,
            "LLM_MODEL": self.llm_model,
            "LLM_API": self.llm_api,
            "PLAYER_PATH": self.player_path,
        }


class ConfigManager:
    """负责 .env 文件读写、内存热加载及数据目录路径管理。"""

    def __init__(
        self,
        env_path: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.env_path = Path(env_path) if env_path else PROJECT_ROOT / ".env"
        self.data_dir = Path(data_dir) if data_dir else PROJECT_ROOT / "data"
        self.media_db_path = self.data_dir / "media.db"
        self.local_db_path = self.data_dir / "local_state.db"
        self.image_cache_dir = self.data_dir / "cache" / "images"
        self._settings = self._load_from_disk()

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_from_disk(self) -> AppSettings:
        file_values: dict[str, str] = {}
        if self.env_path.exists():
            raw = dotenv_values(self.env_path, encoding="utf-8")
            file_values = {k: (v or "").strip() for k, v in raw.items() if k}

        def pick(key: str, default: str = "") -> str:
            if key in file_values:
                return file_values[key]
            env_val = os.environ.get(key)
            if env_val is not None:
                return env_val.strip()
            return default

        port_raw = pick("APP_PORT", "5000")
        try:
            port = int(port_raw)
        except ValueError:
            port = 5000

        llm_api_mode = pick("LLM_API", "chat_completions").lower()
        if llm_api_mode not in ("responses", "chat_completions"):
            llm_api_mode = "chat_completions"

        return AppSettings(
            alist_url=pick("ALIST_URL", "http://127.0.0.1:5244").rstrip("/"),
            alist_username=pick("ALIST_USERNAME", "admin"),
            alist_password=pick("ALIST_PASSWORD", ""),
            tmdb_token=pick("TMDB_TOKEN", ""),
            mdblist_apikey=pick("MDBLIST_APIKEY", ""),
            llm_base_url=pick("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            llm_api_key=pick("LLM_API_KEY", ""),
            llm_model=pick("LLM_MODEL", "deepseek-chat") or "deepseek-chat",
            llm_api=llm_api_mode,
            player_path=pick("PLAYER_PATH", ""),
            app_host=pick("APP_HOST", "127.0.0.1") or "127.0.0.1",
            app_port=port,
            secret_key=pick("FLASK_SECRET_KEY", "yingku-local-session-secret"),
        )

    @property
    def settings(self) -> AppSettings:
        with self._lock:
            return self._settings

    def reload(self) -> AppSettings:
        with self._lock:
            self._settings = self._load_from_disk()
            return self._settings

    def update_env(self, updates: Mapping[str, str]) -> AppSettings:
        """将新配置原子写回 .env 并立即刷新内存配置。"""
        with self._lock:
            normalized: dict[str, str] = {}
            for key, val in updates.items():
                if key in MANAGED_ENV_KEYS or key in ("APP_HOST", "APP_PORT"):
                    clean_val = (val or "").strip()
                    if key in ("ALIST_URL", "LLM_BASE_URL") and clean_val:
                        clean_val = clean_val.rstrip("/")
                    normalized[key] = clean_val

            existing_lines: list[str] = []
            if self.env_path.exists():
                existing_lines = self.env_path.read_text(encoding="utf-8").splitlines()

            seen_keys: set[str] = set()
            output_lines: list[str] = []
            for line in existing_lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in line:
                    output_lines.append(line)
                    continue
                key_part = line.split("=", 1)[0].strip()
                if key_part in normalized:
                    output_lines.append(f"{key_part}={self._format_env_value(normalized[key_part])}")
                    seen_keys.add(key_part)
                else:
                    output_lines.append(line)
                    seen_keys.add(key_part)

            if not existing_lines:
                # 首次生成整洁分组的 .env
                groups = [
                    ("ALIST_URL", "ALIST_USERNAME", "ALIST_PASSWORD"),
                    ("TMDB_TOKEN",),
                    ("MDBLIST_APIKEY",),
                    ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_API"),
                    ("PLAYER_PATH",),
                ]
                current_defaults = self._settings.to_env_dict()
                current_defaults.update(normalized)
                for idx, group in enumerate(groups):
                    if idx > 0:
                        output_lines.append("")
                    for key in group:
                        val = current_defaults.get(key, "")
                        output_lines.append(f"{key}={self._format_env_value(val)}")
                        seen_keys.add(key)
            else:
                for key, val in normalized.items():
                    if key not in seen_keys:
                        output_lines.append(f"{key}={self._format_env_value(val)}")
                        seen_keys.add(key)

            self.env_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.env_path.with_suffix(".env.tmp")
            tmp_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
            tmp_path.replace(self.env_path)

            for key, val in normalized.items():
                os.environ[key] = val

            self._settings = self._load_from_disk()
            return self._settings

    @staticmethod
    def _format_env_value(value: str) -> str:
        clean = value.replace("\r", "").replace("\n", "")
        if any(ch in clean for ch in ("#", '"')) or clean != clean.strip():
            escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return clean
