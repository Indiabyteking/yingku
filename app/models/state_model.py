from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.database import connect_sqlite, utc_now_iso


class LocalStateRepository:
    """本机状态、服务连通性快照、识别缓存与后台任务进度库（local_state.db），与媒体资料库物理隔离。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.init_schema()

    def init_schema(self) -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recognition_cache (
                    cache_key TEXT PRIMARY KEY,
                    alist_path TEXT NOT NULL,
                    raw_name TEXT NOT NULL,
                    cleaned_name TEXT NOT NULL,
                    inferred_title TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT '',
                    year INTEGER,
                    season_number INTEGER,
                    episode_number INTEGER,
                    matched_tmdb_id INTEGER,
                    confidence REAL NOT NULL DEFAULT 0,
                    bucket TEXT NOT NULL,
                    source TEXT NOT NULL,
                    reasoning TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS image_cache (
                    remote_url TEXT PRIMARY KEY,
                    local_rel_path TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    downloaded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_progress (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    current_label TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def get_value(self, key: str, default: Any = None) -> Any:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute("SELECT value_json FROM kv_store WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value_json"])
            except json.JSONDecodeError:
                return default

    def set_value(self, key: str, value: Any) -> None:
        now = utc_now_iso()
        payload = json.dumps(value, ensure_ascii=False)
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kv_store (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, payload, now),
            )

    @property
    def onboarding_completed(self) -> bool:
        return bool(self.get_value("onboarding_completed", False))

    def set_onboarding_completed(self, completed: bool = True) -> None:
        self.set_value("onboarding_completed", bool(completed))

    def get_skipped_services(self) -> dict[str, bool]:
        raw = self.get_value("skipped_services", {})
        return raw if isinstance(raw, dict) else {}

    def set_skipped_services(self, skipped: dict[str, bool]) -> None:
        current = self.get_skipped_services()
        current.update({k: bool(v) for k, v in skipped.items()})
        self.set_value("skipped_services", current)

    def get_service_statuses(self) -> dict[str, dict[str, Any]]:
        raw = self.get_value("service_statuses", {})
        return raw if isinstance(raw, dict) else {}

    def update_service_status(self, service: str, ok: bool, message: str, detail: dict[str, Any] | None = None) -> None:
        statuses = self.get_service_statuses()
        statuses[service] = {
            "ok": bool(ok),
            "message": message,
            "detail": detail or {},
            "checked_at": utc_now_iso(),
        }
        self.set_value("service_statuses", statuses)

    # --- 识别结果缓存 ---
    def get_recognition_cache(self, cache_key: str) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM recognition_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["payload_json"])
                data["from_cache"] = True
                return data
            except json.JSONDecodeError:
                return None

    def save_recognition_cache(self, cache_key: str, result: dict[str, Any]) -> None:
        now = utc_now_iso()
        matched = result.get("matched_work") or {}
        payload = json.dumps(result, ensure_ascii=False)
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO recognition_cache (
                    cache_key, alist_path, raw_name, cleaned_name, inferred_title,
                    media_type, year, season_number, episode_number, matched_tmdb_id,
                    confidence, bucket, source, reasoning, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    cleaned_name = excluded.cleaned_name,
                    inferred_title = excluded.inferred_title,
                    media_type = excluded.media_type,
                    year = excluded.year,
                    season_number = excluded.season_number,
                    episode_number = excluded.episode_number,
                    matched_tmdb_id = excluded.matched_tmdb_id,
                    confidence = excluded.confidence,
                    bucket = excluded.bucket,
                    source = excluded.source,
                    reasoning = excluded.reasoning,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    result.get("alist_path") or "",
                    result.get("raw_name") or "",
                    result.get("cleaned_name") or "",
                    result.get("inferred_title") or "",
                    result.get("media_type") or "",
                    result.get("year"),
                    result.get("season_number"),
                    result.get("episode_number"),
                    matched.get("tmdb_id"),
                    float(result.get("confidence") or 0.0),
                    result.get("bucket") or "unrecognized",
                    result.get("source") or "rule",
                    result.get("reasoning") or "",
                    payload,
                    now,
                ),
            )

    def clear_recognition_cache(self) -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.execute("DELETE FROM recognition_cache")

    # --- 本地图片缓存索引 ---
    def get_cached_image(self, remote_url: str) -> str | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT local_rel_path FROM image_cache WHERE remote_url = ?",
                (remote_url,),
            ).fetchone()
            return str(row["local_rel_path"]) if row else None

    def save_cached_image(self, remote_url: str, local_rel_path: str, category: str = "") -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO image_cache (remote_url, local_rel_path, category, downloaded_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(remote_url) DO UPDATE SET
                    local_rel_path = excluded.local_rel_path,
                    category = excluded.category,
                    downloaded_at = excluded.downloaded_at
                """,
                (remote_url, local_rel_path, category, utc_now_iso()),
            )

    # --- 后台任务进度跟踪 ---
    def create_task(self, task_id: str, task_type: str, total: int = 0, summary: str = "") -> dict[str, Any]:
        now = utc_now_iso()
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO task_progress (
                    task_id, task_type, status, total, completed,
                    current_label, summary, result_json, error, created_at, updated_at
                ) VALUES (?, ?, 'running', ?, 0, '', ?, '{}', '', ?, ?)
                """,
                (task_id, task_type, int(total), summary, now, now),
            )
        return self.get_task(task_id) or {}

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        total: int | None = None,
        completed: int | None = None,
        current_label: str | None = None,
        summary: str | None = None,
        result: Any | None = None,
        error: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {"updated_at": utc_now_iso()}
        if status is not None:
            fields["status"] = status
        if total is not None:
            fields["total"] = int(total)
        if completed is not None:
            fields["completed"] = int(completed)
        if current_label is not None:
            fields["current_label"] = current_label
        if summary is not None:
            fields["summary"] = summary
        if result is not None:
            fields["result_json"] = json.dumps(result, ensure_ascii=False)
        if error is not None:
            fields["error"] = error

        set_sql = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [task_id]
        with connect_sqlite(self.db_path) as conn:
            conn.execute(f"UPDATE task_progress SET {set_sql} WHERE task_id = ?", params)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute("SELECT * FROM task_progress WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["result"] = json.loads(d.pop("result_json", "{}") or "{}")
            total = int(d.get("total") or 0)
            completed = int(d.get("completed") or 0)
            d["percent"] = 100 if d["status"] == "completed" else (int(round(completed * 100 / total)) if total > 0 else 0)
            return d
