from __future__ import annotations

import posixpath
from typing import Any
from urllib.parse import quote

from app.clients.http_client import ExternalServiceError, RateLimitedHttpClient
from app.config import ConfigManager, is_effective_value, is_placeholder_only

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".ts",
    ".m2ts",
    ".m4v",
    ".webm",
    ".wmv",
    ".rmvb",
    ".mpg",
    ".mpeg",
    ".iso",
}


def format_file_size(num_bytes: int) -> str:
    size = float(max(0, int(num_bytes or 0)))
    if size <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f} {unit}" if unit in ("GB", "TB") else f"{size:.0f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def is_video_filename(name: str) -> bool:
    dot = name.rfind(".")
    if dot < 0:
        return False
    return name[dot:].lower() in VIDEO_EXTENSIONS


class AListClient:
    """AList 网盘挂载服务客户端封装。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        http_client: RateLimitedHttpClient | None = None,
    ) -> None:
        self._cfg = config_manager
        self._http = http_client or RateLimitedHttpClient("AList", min_interval=0.1, max_retries=2, timeout=20.0)
        self._cached_token: str = ""
        self._cached_creds: tuple[str, str, str] = ("", "", "")

    def _login(self, base_url: str, username: str, password: str) -> str:
        url = f"{base_url.rstrip('/')}/api/auth/login"
        resp = self._http.request(
            "POST",
            url,
            json_body={"username": username, "password": password},
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ExternalServiceError("AList", f"AList 返回了非 JSON 响应 (HTTP {resp.status_code})") from exc

        code = payload.get("code")
        if code != 200:
            msg = payload.get("message") or "登录失败"
            if "password" in msg.lower() or "incorrect" in msg.lower():
                raise ExternalServiceError("AList", f"AList 账号或密码错误（{msg}）", status_code=401)
            raise ExternalServiceError("AList", f"AList 登录失败：{msg}", status_code=code)

        token = (payload.get("data") or {}).get("token") or ""
        if not token:
            raise ExternalServiceError("AList", "AList 登录成功但未返回访问令牌")
        return str(token)

    def _get_token(self, force_refresh: bool = False) -> str:
        s = self._cfg.settings
        if not is_effective_value(s.alist_url):
            raise ExternalServiceError("AList", "尚未配置 AList 服务地址")
        if is_placeholder_only(s.alist_password):
            raise ExternalServiceError("AList", "AList 密码当前为占位值（to_do），请在设置中填写正确密码")

        creds = (s.alist_url, s.alist_username, s.alist_password)
        if not force_refresh and self._cached_token and self._cached_creds == creds:
            return self._cached_token

        token = self._login(s.alist_url, s.alist_username, s.alist_password)
        self._cached_token = token
        self._cached_creds = creds
        return token

    def check_connection(
        self,
        alist_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        s = self._cfg.settings
        url = (alist_url if alist_url is not None else s.alist_url).strip().rstrip("/")
        user = (username if username is not None else s.alist_username).strip()
        pwd = (password if password is not None else s.alist_password).strip()

        if not is_effective_value(url):
            return False, "请填写有效的 AList 服务地址（例如 http://127.0.0.1:5244）", {}
        if not url.startswith(("http://", "https://")):
            return False, "AList 地址需以 http:// 或 https:// 开头", {}
        if not is_effective_value(user):
            return False, "请填写 AList 登录用户名", {}
        if is_placeholder_only(pwd):
            return False, f"AList 密码当前为占位值（{pwd}），请填写实际密码", {}

        try:
            token = self._login(url, user, pwd)
            resp = self._http.request(
                "POST",
                f"{url}/api/fs/list",
                headers={"Authorization": token},
                json_body={"path": "/", "refresh": False},
            )
            body = resp.json()
            if body.get("code") != 200:
                return False, f"登录成功，但读取根目录失败：{body.get('message')}", {}
            items = (body.get("data") or {}).get("content") or []
            mounts = [f"/{it.get('name')}" for it in items if it.get("name")]
            mount_desc = "、".join(mounts) if mounts else "暂无挂载目录"
            return True, f"连接成功，检测到挂载目录：{mount_desc}", {"mounts": mounts}
        except ExternalServiceError as exc:
            return False, exc.message, {}
        except Exception as exc:
            return False, f"AList 检测异常：{exc}", {}

    def list_dir(self, path: str = "/", refresh: bool = False) -> list[dict[str, Any]]:
        norm_path = self._normalize_path(path)
        s = self._cfg.settings
        token = self._get_token()

        for attempt in range(2):
            resp = self._http.request(
                "POST",
                f"{s.alist_url}/api/fs/list",
                headers={"Authorization": token},
                json_body={"path": norm_path, "refresh": bool(refresh)},
            )
            body = resp.json()
            code = body.get("code")
            if code == 401 and attempt == 0:
                token = self._get_token(force_refresh=True)
                continue
            if code != 200:
                raise ExternalServiceError("AList", f"读取目录 {norm_path} 失败：{body.get('message') or code}")

            raw_items = (body.get("data") or {}).get("content") or []
            entries: list[dict[str, Any]] = []
            for item in raw_items:
                name = str(item.get("name") or "")
                if not name:
                    continue
                is_dir = bool(item.get("is_dir"))
                full_path = "/" + name if norm_path == "/" else f"{norm_path}/{name}"
                size = int(item.get("size") or 0)
                is_video = (not is_dir) and is_video_filename(name)
                entries.append(
                    {
                        "name": name,
                        "path": full_path,
                        "parent_path": norm_path,
                        "is_dir": is_dir,
                        "is_video": is_video,
                        "size": size,
                        "size_human": "" if is_dir else format_file_size(size),
                        "modified": item.get("modified") or "",
                        "sign": item.get("sign") or "",
                    }
                )
            entries.sort(key=lambda x: (0 if x["is_dir"] else (1 if x["is_video"] else 2), x["name"].lower()))
            return entries

        return []

    def collect_video_files(self, selected_paths: list[str], max_depth: int = 4) -> list[dict[str, Any]]:
        """根据用户选择的 AList 文件或文件夹，递归收集其中的视频文件。"""
        collected: dict[str, dict[str, Any]] = {}

        for raw_p in selected_paths:
            norm = self._normalize_path(raw_p)
            if is_video_filename(norm):
                info = self.get_item_meta(norm)
                if not info.get("is_dir"):
                    collected[norm] = {
                        "alist_path": norm,
                        "filename": posixpath.basename(norm),
                        "parent_path": posixpath.dirname(norm) or "/",
                        "size": int(info.get("size") or 0),
                    }
                    continue
            self._walk_videos(norm, depth=0, max_depth=max_depth, sink=collected)

        return list(collected.values())

    def _walk_videos(self, folder_path: str, depth: int, max_depth: int, sink: dict[str, dict[str, Any]]) -> None:
        if depth > max_depth:
            return
        try:
            items = self.list_dir(folder_path, refresh=False)
        except ExternalServiceError:
            if depth == 0:
                raise
            return

        for it in items:
            if it["is_dir"]:
                self._walk_videos(it["path"], depth + 1, max_depth, sink)
            elif it["is_video"]:
                sink[it["path"]] = {
                    "alist_path": it["path"],
                    "filename": it["name"],
                    "parent_path": it["parent_path"],
                    "size": int(it["size"] or 0),
                }

    def get_item_meta(self, path: str) -> dict[str, Any]:
        norm_path = self._normalize_path(path)
        s = self._cfg.settings
        token = self._get_token()

        for attempt in range(2):
            resp = self._http.request(
                "POST",
                f"{s.alist_url}/api/fs/get",
                headers={"Authorization": token},
                json_body={"path": norm_path},
            )
            body = resp.json()
            code = body.get("code")
            if code == 401 and attempt == 0:
                token = self._get_token(force_refresh=True)
                continue
            if code != 200:
                raise ExternalServiceError("AList", f"获取文件信息失败 ({norm_path})：{body.get('message') or code}")
            return body.get("data") or {}
        return {}

    def build_stream_url(self, alist_path: str) -> dict[str, str]:
        """获取可直接交给本地播放器（MPC-HC）流式播放的签名地址。"""
        norm_path = self._normalize_path(alist_path)
        s = self._cfg.settings
        meta = self.get_item_meta(norm_path)

        raw_url = str(meta.get("raw_url") or "").strip()
        sign = str(meta.get("sign") or "").strip()
        provider = str(meta.get("provider") or "")

        encoded_rel = "/".join(quote(seg, safe="") for seg in norm_path.lstrip("/").split("/"))
        direct_url = f"{s.alist_url}/d/{encoded_rel}"
        if sign:
            direct_url = f"{direct_url}?sign={quote(sign, safe='=:')}"

        # 若 AList 开启了本地代理（/p/...），优先使用该本机代理地址以避免夸克/百度防盗链拦截播放器
        if raw_url.startswith(s.alist_url):
            stream_url = raw_url
        else:
            stream_url = direct_url or raw_url

        return {
            "stream_url": stream_url,
            "direct_url": direct_url,
            "raw_url": raw_url,
            "provider": provider,
            "filename": str(meta.get("name") or posixpath.basename(norm_path)),
        }

    @staticmethod
    def _normalize_path(path: str) -> str:
        clean = (path or "/").strip().replace("\\", "/")
        if not clean.startswith("/"):
            clean = "/" + clean
        normalized = posixpath.normpath(clean)
        return "/" if normalized in (".", "//") else normalized
