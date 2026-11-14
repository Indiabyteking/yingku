from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.database import connect_sqlite, utc_now_iso


class MediaRepository:
    """媒体资料库（media.db）读写模型，集中封装全部媒体 SQL。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.init_schema()

    def init_schema(self) -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS works (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL CHECK(media_type IN ('movie', 'tv')),
                    tmdb_id INTEGER NOT NULL,
                    imdb_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    custom_title TEXT NOT NULL DEFAULT '',
                    original_title TEXT NOT NULL DEFAULT '',
                    year INTEGER,
                    release_date TEXT NOT NULL DEFAULT '',
                    runtime INTEGER NOT NULL DEFAULT 0,
                    overview TEXT NOT NULL DEFAULT '',
                    genres_json TEXT NOT NULL DEFAULT '[]',
                    cast_json TEXT NOT NULL DEFAULT '[]',
                    tmdb_rating REAL NOT NULL DEFAULT 0,
                    tmdb_votes INTEGER NOT NULL DEFAULT 0,
                    ratings_json TEXT NOT NULL DEFAULT '[]',
                    poster_path TEXT NOT NULL DEFAULT '',
                    backdrop_path TEXT NOT NULL DEFAULT '',
                    logo_path TEXT NOT NULL DEFAULT '',
                    tmdb_poster_remote TEXT NOT NULL DEFAULT '',
                    tmdb_backdrop_remote TEXT NOT NULL DEFAULT '',
                    tmdb_logo_remote TEXT NOT NULL DEFAULT '',
                    alist_root_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(media_type, tmdb_id)
                );

                CREATE TABLE IF NOT EXISTS seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    season_number INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    overview TEXT NOT NULL DEFAULT '',
                    air_date TEXT NOT NULL DEFAULT '',
                    episode_count INTEGER NOT NULL DEFAULT 0,
                    poster_path TEXT NOT NULL DEFAULT '',
                    UNIQUE(work_id, season_number)
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    season_number INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    overview TEXT NOT NULL DEFAULT '',
                    air_date TEXT NOT NULL DEFAULT '',
                    runtime INTEGER NOT NULL DEFAULT 0,
                    still_path TEXT NOT NULL DEFAULT '',
                    tmdb_rating REAL NOT NULL DEFAULT 0,
                    UNIQUE(work_id, season_number, episode_number)
                );

                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    episode_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
                    season_number INTEGER,
                    episode_number INTEGER,
                    alist_path TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    version_label TEXT NOT NULL DEFAULT '',
                    match_status TEXT NOT NULL DEFAULT 'matched',
                    recognition_trace_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watch_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
                    episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
                    media_file_id INTEGER REFERENCES media_files(id) ON DELETE SET NULL,
                    position_seconds INTEGER NOT NULL DEFAULT 0,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    progress_percent REAL NOT NULL DEFAULT 0,
                    watched INTEGER NOT NULL DEFAULT 0,
                    play_count INTEGER NOT NULL DEFAULT 0,
                    last_played_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_works_media_type ON works(media_type);
                CREATE INDEX IF NOT EXISTS idx_episodes_work_season ON episodes(work_id, season_number, episode_number);
                CREATE INDEX IF NOT EXISTS idx_files_work ON media_files(work_id);
                CREATE INDEX IF NOT EXISTS idx_progress_work ON watch_progress(work_id, last_played_at DESC);
                """
            )

    @staticmethod
    def _hydrate_work(row: Any) -> dict[str, Any]:
        data = dict(row)
        data["genres"] = json.loads(data.pop("genres_json", "[]") or "[]")
        data["cast"] = json.loads(data.pop("cast_json", "[]") or "[]")
        data["ratings"] = json.loads(data.pop("ratings_json", "[]") or "[]")
        data["display_title"] = (data.get("custom_title") or "").strip() or data["title"]
        return data

    def upsert_work(self, payload: dict[str, Any]) -> int:
        now = utc_now_iso()
        genres_json = json.dumps(payload.get("genres") or [], ensure_ascii=False)
        cast_json = json.dumps(payload.get("cast") or [], ensure_ascii=False)
        ratings_json = json.dumps(payload.get("ratings") or [], ensure_ascii=False)

        with connect_sqlite(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id, custom_title FROM works WHERE media_type = ? AND tmdb_id = ?",
                (payload["media_type"], int(payload["tmdb_id"])),
            ).fetchone()

            if existing:
                work_id = int(existing["id"])
                custom_title = payload.get("custom_title")
                if custom_title is None:
                    custom_title = existing["custom_title"]
                conn.execute(
                    """
                    UPDATE works SET
                        imdb_id = ?,
                        title = ?,
                        custom_title = ?,
                        original_title = ?,
                        year = ?,
                        release_date = ?,
                        runtime = ?,
                        overview = ?,
                        genres_json = ?,
                        cast_json = ?,
                        tmdb_rating = ?,
                        tmdb_votes = ?,
                        ratings_json = ?,
                        poster_path = ?,
                        backdrop_path = ?,
                        logo_path = ?,
                        tmdb_poster_remote = ?,
                        tmdb_backdrop_remote = ?,
                        tmdb_logo_remote = ?,
                        alist_root_path = CASE WHEN ? != '' THEN ? ELSE alist_root_path END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        payload.get("imdb_id") or "",
                        payload["title"],
                        custom_title or "",
                        payload.get("original_title") or "",
                        payload.get("year"),
                        payload.get("release_date") or "",
                        int(payload.get("runtime") or 0),
                        payload.get("overview") or "",
                        genres_json,
                        cast_json,
                        float(payload.get("tmdb_rating") or 0.0),
                        int(payload.get("tmdb_votes") or 0),
                        ratings_json,
                        payload.get("poster_path") or "",
                        payload.get("backdrop_path") or "",
                        payload.get("logo_path") or "",
                        payload.get("tmdb_poster_remote") or "",
                        payload.get("tmdb_backdrop_remote") or "",
                        payload.get("tmdb_logo_remote") or "",
                        payload.get("alist_root_path") or "",
                        payload.get("alist_root_path") or "",
                        now,
                        work_id,
                    ),
                )
                return work_id

            cur = conn.execute(
                """
                INSERT INTO works (
                    media_type, tmdb_id, imdb_id, title, custom_title, original_title,
                    year, release_date, runtime, overview, genres_json, cast_json,
                    tmdb_rating, tmdb_votes, ratings_json, poster_path, backdrop_path,
                    logo_path, tmdb_poster_remote, tmdb_backdrop_remote, tmdb_logo_remote,
                    alist_root_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["media_type"],
                    int(payload["tmdb_id"]),
                    payload.get("imdb_id") or "",
                    payload["title"],
                    payload.get("custom_title") or "",
                    payload.get("original_title") or "",
                    payload.get("year"),
                    payload.get("release_date") or "",
                    int(payload.get("runtime") or 0),
                    payload.get("overview") or "",
                    genres_json,
                    cast_json,
                    float(payload.get("tmdb_rating") or 0.0),
                    int(payload.get("tmdb_votes") or 0),
                    ratings_json,
                    payload.get("poster_path") or "",
                    payload.get("backdrop_path") or "",
                    payload.get("logo_path") or "",
                    payload.get("tmdb_poster_remote") or "",
                    payload.get("tmdb_backdrop_remote") or "",
                    payload.get("tmdb_logo_remote") or "",
                    payload.get("alist_root_path") or "",
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_work(self, work_id: int) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute("SELECT * FROM works WHERE id = ?", (int(work_id),)).fetchone()
            return self._hydrate_work(row) if row else None

    def get_work_by_tmdb(self, media_type: str, tmdb_id: int) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM works WHERE media_type = ? AND tmdb_id = ?",
                (media_type, int(tmdb_id)),
            ).fetchone()
            return self._hydrate_work(row) if row else None

    def list_works(
        self,
        media_type: str | None = None,
        search: str = "",
        genre: str = "",
        year: int | None = None,
        min_rating: float | None = None,
        sort: str = "recent",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if media_type in ("movie", "tv"):
            clauses.append("w.media_type = ?")
            params.append(media_type)

        if search.strip():
            kw = f"%{search.strip()}%"
            clauses.append("(w.title LIKE ? OR w.custom_title LIKE ? OR w.original_title LIKE ? OR w.overview LIKE ?)")
            params.extend([kw, kw, kw, kw])

        if genre.strip():
            clauses.append("w.genres_json LIKE ?")
            params.append(f'%"{genre.strip()}"%')

        if year is not None:
            clauses.append("w.year = ?")
            params.append(int(year))

        if min_rating is not None:
            clauses.append("w.tmdb_rating >= ?")
            params.append(float(min_rating))

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_map = {
            "recent": "w.created_at DESC, w.id DESC",
            "rating": "w.tmdb_rating DESC, w.tmdb_votes DESC, w.id DESC",
            "year": "COALESCE(w.year, 0) DESC, w.tmdb_rating DESC",
            "title": "COALESCE(NULLIF(w.custom_title, ''), w.title) COLLATE NOCASE ASC",
        }
        order_sql = order_map.get(sort, order_map["recent"])
        limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""

        sql = f"""
            SELECT w.*,
                   (SELECT COUNT(*) FROM media_files mf WHERE mf.work_id = w.id) AS file_count,
                   (SELECT COUNT(*) FROM media_files mf WHERE mf.work_id = w.id AND mf.match_status = 'unmatched') AS unmatched_file_count
            FROM works w
            {where_sql}
            ORDER BY {order_sql}
            {limit_sql}
        """
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._hydrate_work(r) for r in rows]

    def list_distinct_genres(self) -> list[str]:
        genres: set[str] = set()
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute("SELECT genres_json FROM works").fetchall()
            for r in rows:
                for g in json.loads(r["genres_json"] or "[]"):
                    if g:
                        genres.add(str(g))
        return sorted(genres)

    def list_distinct_years(self) -> list[int]:
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT year FROM works WHERE year IS NOT NULL ORDER BY year DESC"
            ).fetchall()
            return [int(r["year"]) for r in rows if r["year"]]

    def replace_seasons_and_episodes(
        self,
        work_id: int,
        seasons_data: list[dict[str, Any]],
        episodes_data: list[dict[str, Any]],
    ) -> dict[tuple[int, int], int]:
        """更新剧集的季与集资料，同时保留已有的观看进度关联。"""
        ep_id_map: dict[tuple[int, int], int] = {}
        with connect_sqlite(self.db_path) as conn:
            # 记录旧集进度（按季号+集号保存，防止重建或重匹配时丢失）
            old_progress_rows = conn.execute(
                """
                SELECT e.season_number, e.episode_number,
                       wp.position_seconds, wp.duration_seconds, wp.progress_percent,
                       wp.watched, wp.play_count, wp.last_played_at, wp.media_file_id
                FROM watch_progress wp
                JOIN episodes e ON e.id = wp.episode_id
                WHERE wp.work_id = ?
                """,
                (int(work_id),),
            ).fetchall()
            saved_progress = {
                (int(r["season_number"]), int(r["episode_number"])): dict(r)
                for r in old_progress_rows
            }

            conn.execute("DELETE FROM seasons WHERE work_id = ?", (int(work_id),))
            conn.execute("DELETE FROM episodes WHERE work_id = ?", (int(work_id),))

            for s in seasons_data:
                conn.execute(
                    """
                    INSERT INTO seasons (work_id, season_number, name, overview, air_date, episode_count, poster_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(work_id),
                        int(s["season_number"]),
                        s.get("name") or f"第 {s['season_number']} 季",
                        s.get("overview") or "",
                        s.get("air_date") or "",
                        int(s.get("episode_count") or 0),
                        s.get("poster_path") or "",
                    ),
                )

            for ep in episodes_data:
                s_no = int(ep["season_number"])
                e_no = int(ep["episode_number"])
                cur = conn.execute(
                    """
                    INSERT INTO episodes (
                        work_id, season_number, episode_number, title, overview,
                        air_date, runtime, still_path, tmdb_rating
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(work_id),
                        s_no,
                        e_no,
                        ep.get("title") or f"第 {e_no} 集",
                        ep.get("overview") or "",
                        ep.get("air_date") or "",
                        int(ep.get("runtime") or 0),
                        ep.get("still_path") or "",
                        float(ep.get("tmdb_rating") or 0.0),
                    ),
                )
                ep_id = int(cur.lastrowid)
                ep_id_map[(s_no, e_no)] = ep_id

                if (s_no, e_no) in saved_progress:
                    sp = saved_progress[(s_no, e_no)]
                    conn.execute(
                        """
                        INSERT INTO watch_progress (
                            work_id, episode_id, media_file_id, position_seconds,
                            duration_seconds, progress_percent, watched, play_count, last_played_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(work_id),
                            ep_id,
                            sp["media_file_id"],
                            sp["position_seconds"],
                            sp["duration_seconds"],
                            sp["progress_percent"],
                            sp["watched"],
                            sp["play_count"],
                            sp["last_played_at"],
                        ),
                    )

        self.rebind_episode_files_for_work(work_id)
        return ep_id_map

    def rebind_episode_files_for_work(self, work_id: int) -> int:
        """按季号、集号将剧集媒体文件自动关联到对应的 TMDB 单集，对不上的标记为 unmatched。"""
        matched_count = 0
        with connect_sqlite(self.db_path) as conn:
            ep_rows = conn.execute(
                "SELECT id, season_number, episode_number FROM episodes WHERE work_id = ?",
                (int(work_id),),
            ).fetchall()
            ep_lookup = {(int(r["season_number"]), int(r["episode_number"])): int(r["id"]) for r in ep_rows}

            file_rows = conn.execute(
                "SELECT id, season_number, episode_number, match_status FROM media_files WHERE work_id = ?",
                (int(work_id),),
            ).fetchall()

            for f in file_rows:
                s_no = f["season_number"]
                e_no = f["episode_number"]
                ep_id = ep_lookup.get((int(s_no), int(e_no))) if (s_no is not None and e_no is not None) else None
                if ep_id is not None:
                    new_status = "manual" if f["match_status"] == "manual" else "matched"
                    conn.execute(
                        "UPDATE media_files SET episode_id = ?, match_status = ? WHERE id = ?",
                        (ep_id, new_status, int(f["id"])),
                    )
                    matched_count += 1
                else:
                    conn.execute(
                        "UPDATE media_files SET episode_id = NULL, match_status = 'unmatched' WHERE id = ?",
                        (int(f["id"]),),
                    )
        return matched_count

    def get_seasons(self, work_id: int) -> list[dict[str, Any]]:
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM media_files mf
                        WHERE mf.work_id = s.work_id AND mf.season_number = s.season_number AND mf.episode_id IS NOT NULL) AS available_count
                FROM seasons s
                WHERE s.work_id = ?
                ORDER BY CASE WHEN s.season_number = 0 THEN 9999 ELSE s.season_number END ASC
                """,
                (int(work_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_episodes(self, work_id: int, season_number: int | None = None) -> list[dict[str, Any]]:
        clauses = ["e.work_id = ?"]
        params: list[Any] = [int(work_id)]
        if season_number is not None:
            clauses.append("e.season_number = ?")
            params.append(int(season_number))

        sql = f"""
            SELECT e.*,
                   wp.position_seconds,
                   wp.duration_seconds,
                   COALESCE(wp.progress_percent, 0) AS progress_percent,
                   COALESCE(wp.watched, 0) AS watched,
                   COALESCE(wp.play_count, 0) AS play_count,
                   wp.last_played_at
            FROM episodes e
            LEFT JOIN watch_progress wp ON wp.episode_id = e.id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.season_number ASC, e.episode_number ASC
        """
        with connect_sqlite(self.db_path) as conn:
            ep_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            file_rows = conn.execute(
                "SELECT * FROM media_files WHERE work_id = ? ORDER BY file_size DESC, id ASC",
                (int(work_id),),
            ).fetchall()
            files_by_ep: dict[int, list[dict[str, Any]]] = {}
            for f in file_rows:
                fd = dict(f)
                fd["recognition_trace"] = json.loads(fd.pop("recognition_trace_json", "{}") or "{}")
                if fd.get("episode_id"):
                    files_by_ep.setdefault(int(fd["episode_id"]), []).append(fd)

            for ep in ep_rows:
                ep_files = files_by_ep.get(int(ep["id"]), [])
                ep["files"] = ep_files
                ep["primary_file"] = ep_files[0] if ep_files else None
                ep["playable"] = bool(ep_files)
            return ep_rows

    def upsert_media_file(
        self,
        work_id: int,
        alist_path: str,
        filename: str,
        file_size: int = 0,
        version_label: str = "",
        season_number: int | None = None,
        episode_number: int | None = None,
        episode_id: int | None = None,
        match_status: str = "matched",
        recognition_trace: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now_iso()
        trace_json = json.dumps(recognition_trace or {}, ensure_ascii=False)

        with connect_sqlite(self.db_path) as conn:
            if episode_id is None and season_number is not None and episode_number is not None:
                ep_row = conn.execute(
                    "SELECT id FROM episodes WHERE work_id = ? AND season_number = ? AND episode_number = ?",
                    (int(work_id), int(season_number), int(episode_number)),
                ).fetchone()
                if ep_row:
                    episode_id = int(ep_row["id"])
                    if match_status == "unmatched":
                        match_status = "matched"
                else:
                    # 若当前是剧集且找不到对应集，则留给用户手动指定
                    w_row = conn.execute("SELECT media_type FROM works WHERE id = ?", (int(work_id),)).fetchone()
                    if w_row and w_row["media_type"] == "tv":
                        match_status = "unmatched"

            existing = conn.execute(
                "SELECT id FROM media_files WHERE alist_path = ?",
                (alist_path,),
            ).fetchone()
            if existing:
                file_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE media_files SET
                        work_id = ?,
                        episode_id = ?,
                        season_number = ?,
                        episode_number = ?,
                        filename = ?,
                        file_size = ?,
                        version_label = ?,
                        match_status = ?,
                        recognition_trace_json = ?
                    WHERE id = ?
                    """,
                    (
                        int(work_id),
                        episode_id,
                        season_number,
                        episode_number,
                        filename,
                        int(file_size or 0),
                        version_label,
                        match_status,
                        trace_json,
                        file_id,
                    ),
                )
                return file_id

            cur = conn.execute(
                """
                INSERT INTO media_files (
                    work_id, episode_id, season_number, episode_number, alist_path,
                    filename, file_size, version_label, match_status, recognition_trace_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(work_id),
                    episode_id,
                    season_number,
                    episode_number,
                    alist_path,
                    filename,
                    int(file_size or 0),
                    version_label,
                    match_status,
                    trace_json,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get_media_files(self, work_id: int) -> list[dict[str, Any]]:
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT mf.*, e.title AS episode_title
                FROM media_files mf
                LEFT JOIN episodes e ON e.id = mf.episode_id
                WHERE mf.work_id = ?
                ORDER BY COALESCE(mf.season_number, 0) ASC, COALESCE(mf.episode_number, 0) ASC, mf.file_size DESC, mf.filename ASC
                """,
                (int(work_id),),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["recognition_trace"] = json.loads(d.pop("recognition_trace_json", "{}") or "{}")
                result.append(d)
            return result

    def get_media_file_by_id(self, file_id: int) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute("SELECT * FROM media_files WHERE id = ?", (int(file_id),)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["recognition_trace"] = json.loads(d.pop("recognition_trace_json", "{}") or "{}")
            return d

    def get_existing_alist_paths(self) -> set[str]:
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute("SELECT alist_path FROM media_files").fetchall()
            return {str(r["alist_path"]) for r in rows}

    def update_file_episode_mapping(
        self,
        file_id: int,
        work_id: int,
        season_number: int | None,
        episode_number: int | None,
    ) -> bool:
        with connect_sqlite(self.db_path) as conn:
            if season_number is None or episode_number is None:
                cur = conn.execute(
                    """
                    UPDATE media_files
                    SET season_number = NULL, episode_number = NULL, episode_id = NULL, match_status = 'unmatched'
                    WHERE id = ? AND work_id = ?
                    """,
                    (int(file_id), int(work_id)),
                )
                return cur.rowcount > 0

            ep_row = conn.execute(
                "SELECT id FROM episodes WHERE work_id = ? AND season_number = ? AND episode_number = ?",
                (int(work_id), int(season_number), int(episode_number)),
            ).fetchone()
            ep_id = int(ep_row["id"]) if ep_row else None
            status = "manual" if ep_id is not None else "unmatched"
            cur = conn.execute(
                """
                UPDATE media_files
                SET season_number = ?, episode_number = ?, episode_id = ?, match_status = ?
                WHERE id = ? AND work_id = ?
                """,
                (int(season_number), int(episode_number), ep_id, status, int(file_id), int(work_id)),
            )
            return cur.rowcount > 0

    def update_file_version_label(self, file_id: int, work_id: int, version_label: str) -> bool:
        with connect_sqlite(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE media_files SET version_label = ? WHERE id = ? AND work_id = ?",
                ((version_label or "").strip() or "标准版", int(file_id), int(work_id)),
            )
            return cur.rowcount > 0

    def delete_media_file(self, file_id: int, work_id: int) -> bool:
        with connect_sqlite(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM media_files WHERE id = ? AND work_id = ?",
                (int(file_id), int(work_id)),
            )
            return cur.rowcount > 0

    def update_work_fields(self, work_id: int, fields: dict[str, Any]) -> bool:
        allowed = {
            "custom_title",
            "title",
            "poster_path",
            "backdrop_path",
            "logo_path",
            "tmdb_poster_remote",
            "tmdb_backdrop_remote",
            "tmdb_logo_remote",
            "media_type",
            "tmdb_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [int(work_id)]
        with connect_sqlite(self.db_path) as conn:
            cur = conn.execute(f"UPDATE works SET {set_clause} WHERE id = ?", params)
            return cur.rowcount > 0

    def delete_work(self, work_id: int) -> bool:
        with connect_sqlite(self.db_path) as conn:
            cur = conn.execute("DELETE FROM works WHERE id = ?", (int(work_id),))
            return cur.rowcount > 0

    def update_watch_progress(
        self,
        work_id: int,
        episode_id: int | None = None,
        position_seconds: int | None = None,
        duration_seconds: int | None = None,
        progress_percent: float | None = None,
        watched: bool | None = None,
        media_file_id: int | None = None,
        increment_play: bool = False,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with connect_sqlite(self.db_path) as conn:
            if episode_id is not None:
                existing = conn.execute(
                    "SELECT * FROM watch_progress WHERE work_id = ? AND episode_id = ?",
                    (int(work_id), int(episode_id)),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT * FROM watch_progress WHERE work_id = ? AND episode_id IS NULL",
                    (int(work_id),),
                ).fetchone()

            if existing:
                pos = int(position_seconds) if position_seconds is not None else int(existing["position_seconds"])
                dur = int(duration_seconds) if (duration_seconds is not None and duration_seconds > 0) else int(existing["duration_seconds"])
                if progress_percent is not None:
                    pct = max(0.0, min(100.0, float(progress_percent)))
                    if dur > 0 and position_seconds is None:
                        pos = int(round(dur * pct / 100.0))
                elif dur > 0:
                    pct = max(0.0, min(100.0, round(pos * 100.0 / dur, 1)))
                else:
                    pct = float(existing["progress_percent"])

                if watched is True:
                    is_watched = 1
                    pct = 100.0
                    if dur > 0 and position_seconds is None:
                        pos = dur
                elif watched is False:
                    is_watched = 0
                    if progress_percent is None and position_seconds is None:
                        pct = 0.0
                        pos = 0
                else:
                    is_watched = 1 if pct >= 92.0 else int(existing["watched"])

                # 若刚开始播放且原本进度为 0，给一个初始在看进度（如 5%）以便在“继续观看”中直观呈现
                if increment_play and pct == 0.0 and not is_watched:
                    pct = 5.0
                    if dur > 0 and pos == 0:
                        pos = max(30, int(dur * 0.05))

                play_cnt = int(existing["play_count"]) + (1 if increment_play else 0)
                file_ref = media_file_id if media_file_id is not None else existing["media_file_id"]

                conn.execute(
                    """
                    UPDATE watch_progress SET
                        media_file_id = ?,
                        position_seconds = ?,
                        duration_seconds = ?,
                        progress_percent = ?,
                        watched = ?,
                        play_count = ?,
                        last_played_at = ?
                    WHERE id = ?
                    """,
                    (file_ref, pos, dur, pct, is_watched, play_cnt, now, int(existing["id"])),
                )
                row = conn.execute("SELECT * FROM watch_progress WHERE id = ?", (int(existing["id"]),)).fetchone()
                return dict(row)

            dur = int(duration_seconds or 0)
            pos = int(position_seconds or 0)
            if progress_percent is not None:
                pct = max(0.0, min(100.0, float(progress_percent)))
                if dur > 0 and pos == 0:
                    pos = int(round(dur * pct / 100.0))
            elif dur > 0 and pos > 0:
                pct = max(0.0, min(100.0, round(pos * 100.0 / dur, 1)))
            else:
                pct = 100.0 if watched else (5.0 if increment_play else 0.0)
                if dur > 0 and pct == 5.0 and pos == 0:
                    pos = max(30, int(dur * 0.05))

            if watched is True:
                is_watched = 1
                pct = 100.0
                if dur > 0 and pos == 0:
                    pos = dur
            elif watched is False:
                is_watched = 0
            else:
                is_watched = 1 if pct >= 92.0 else 0

            play_cnt = 1 if increment_play else 0
            cur = conn.execute(
                """
                INSERT INTO watch_progress (
                    work_id, episode_id, media_file_id, position_seconds,
                    duration_seconds, progress_percent, watched, play_count, last_played_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (int(work_id), episode_id, media_file_id, pos, dur, pct, is_watched, play_cnt, now),
            )
            row = conn.execute("SELECT * FROM watch_progress WHERE id = ?", (int(cur.lastrowid),)).fetchone()
            return dict(row)

    def get_movie_progress(self, work_id: int) -> dict[str, Any] | None:
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM watch_progress WHERE work_id = ? AND episode_id IS NULL ORDER BY last_played_at DESC LIMIT 1",
                (int(work_id),),
            ).fetchone()
            return dict(row) if row else None

    def resolve_resume_target(self, work_id: int) -> dict[str, Any] | None:
        """
        计算点击作品级“播放”时的目标文件：
        - 电影：选择上次播放的版本文件，若无则取最大体积的主文件；
        - 剧集：从上次看到的那一集继续（若该集已看完则顺延至下一可播集，若没有下一集则停留在最后一集）；
          从未看过则从第一季第一集（或首个可播集）开始。
        """
        work = self.get_work(work_id)
        if not work:
            return None

        with connect_sqlite(self.db_path) as conn:
            if work["media_type"] == "movie":
                prog = conn.execute(
                    "SELECT * FROM watch_progress WHERE work_id = ? AND episode_id IS NULL ORDER BY last_played_at DESC LIMIT 1",
                    (int(work_id),),
                ).fetchone()
                file_row = None
                if prog and prog["media_file_id"]:
                    file_row = conn.execute(
                        "SELECT * FROM media_files WHERE id = ? AND work_id = ?",
                        (int(prog["media_file_id"]), int(work_id)),
                    ).fetchone()
                if not file_row:
                    file_row = conn.execute(
                        "SELECT * FROM media_files WHERE work_id = ? ORDER BY file_size DESC, id ASC LIMIT 1",
                        (int(work_id),),
                    ).fetchone()
                if not file_row:
                    return None
                return {
                    "work": work,
                    "episode": None,
                    "media_file": dict(file_row),
                    "position_seconds": int(prog["position_seconds"]) if (prog and not prog["watched"]) else 0,
                    "progress_percent": float(prog["progress_percent"]) if prog else 0.0,
                }

            # 剧集逻辑
            last_prog = conn.execute(
                """
                SELECT wp.*, e.season_number, e.episode_number, e.title AS episode_title, e.runtime AS episode_runtime
                FROM watch_progress wp
                JOIN episodes e ON e.id = wp.episode_id
                WHERE wp.work_id = ?
                ORDER BY wp.last_played_at DESC
                LIMIT 1
                """,
                (int(work_id),),
            ).fetchone()

            playable_eps = conn.execute(
                """
                SELECT e.*, mf.id AS file_id
                FROM episodes e
                JOIN media_files mf ON mf.episode_id = e.id
                WHERE e.work_id = ?
                GROUP BY e.id
                ORDER BY CASE WHEN e.season_number = 0 THEN 9999 ELSE e.season_number END ASC,
                         e.episode_number ASC
                """,
                (int(work_id),),
            ).fetchall()

            target_ep = None
            resume_pos = 0
            resume_pct = 0.0

            if last_prog:
                last_ep_id = int(last_prog["episode_id"])
                if not last_prog["watched"]:
                    for ep in playable_eps:
                        if int(ep["id"]) == last_ep_id:
                            target_ep = dict(ep)
                            resume_pos = int(last_prog["position_seconds"] or 0)
                            resume_pct = float(last_prog["progress_percent"] or 0.0)
                            break
                else:
                    # 已看完上一集，自动尝试顺延下一集
                    found_last = False
                    for ep in playable_eps:
                        if found_last:
                            target_ep = dict(ep)
                            break
                        if int(ep["id"]) == last_ep_id:
                            found_last = True
                    if target_ep is None and playable_eps:
                        # 全部看完则回退到刚才那集或第一集
                        for ep in playable_eps:
                            if int(ep["id"]) == last_ep_id:
                                target_ep = dict(ep)
                                break

            if target_ep is None and playable_eps:
                target_ep = dict(playable_eps[0])

            if target_ep is not None:
                file_row = conn.execute(
                    "SELECT * FROM media_files WHERE episode_id = ? ORDER BY file_size DESC, id ASC LIMIT 1",
                    (int(target_ep["id"]),),
                ).fetchone()
                if file_row:
                    return {
                        "work": work,
                        "episode": target_ep,
                        "media_file": dict(file_row),
                        "position_seconds": resume_pos,
                        "progress_percent": resume_pct,
                    }

            # 兜底：存在未绑定集号的视频文件时仍允许播放第一个文件
            fallback_file = conn.execute(
                "SELECT * FROM media_files WHERE work_id = ? ORDER BY COALESCE(season_number, 99), COALESCE(episode_number, 999), id ASC LIMIT 1",
                (int(work_id),),
            ).fetchone()
            if fallback_file:
                return {
                    "work": work,
                    "episode": None,
                    "media_file": dict(fallback_file),
                    "position_seconds": 0,
                    "progress_percent": 0.0,
                }
            return None

    def list_continue_watching(self, limit: int = 12) -> list[dict[str, Any]]:
        """返回最近观看过的作品卡片列表（含当前集信息与观看进度百分比）。"""
        with connect_sqlite(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT wp.*, w.media_type
                FROM watch_progress wp
                JOIN works w ON w.id = wp.work_id
                WHERE wp.id IN (
                    SELECT wp2.id
                    FROM watch_progress wp2
                    WHERE wp2.work_id = wp.work_id
                    ORDER BY wp2.last_played_at DESC, wp2.id DESC
                    LIMIT 1
                )
                AND (wp.progress_percent > 0 OR wp.play_count > 0 OR wp.watched = 1)
                ORDER BY wp.last_played_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for r in rows:
            work_id = int(r["work_id"])
            work = self.get_work(work_id)
            if not work:
                continue
            target = self.resolve_resume_target(work_id)
            subtitle = ""
            pct = float(r["progress_percent"] or 0.0)
            ep_info = None

            if work["media_type"] == "tv":
                if r["episode_id"]:
                    with connect_sqlite(self.db_path) as conn:
                        ep_row = conn.execute("SELECT * FROM episodes WHERE id = ?", (int(r["episode_id"]),)).fetchone()
                        if ep_row:
                            ep_info = dict(ep_row)
                if target and target.get("episode"):
                    res_ep = target["episode"]
                    if r["watched"] and ep_info and int(res_ep["id"]) != int(ep_info["id"]):
                        subtitle = f"下一集 S{int(res_ep['season_number']):02d}E{int(res_ep['episode_number']):02d} · {res_ep['title']}"
                        pct = float(target.get("progress_percent") or 0.0)
                        ep_info = res_ep
                    elif ep_info:
                        subtitle = f"S{int(ep_info['season_number']):02d}E{int(ep_info['episode_number']):02d} · {ep_info['title']}"
            else:
                if r["watched"]:
                    subtitle = "已看完"
                elif r["position_seconds"] and r["duration_seconds"]:
                    mins = int(r["position_seconds"]) // 60
                    total_mins = int(r["duration_seconds"]) // 60
                    subtitle = f"已看 {mins} / {total_mins} 分钟"
                else:
                    subtitle = f"观看进度 {int(round(pct))}%"

            items.append(
                {
                    "work": work,
                    "episode": ep_info,
                    "progress_percent": max(3.0, min(100.0, pct)) if pct > 0 else (100.0 if r["watched"] else 5.0),
                    "watched": bool(r["watched"]),
                    "subtitle": subtitle,
                    "last_played_at": r["last_played_at"],
                    "resume_file_id": target["media_file"]["id"] if (target and target.get("media_file")) else None,
                    "resume_episode_id": target["episode"]["id"] if (target and target.get("episode")) else None,
                }
            )
        return items
