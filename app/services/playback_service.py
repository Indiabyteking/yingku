from __future__ import annotations

from typing import Any

from app.clients.alist_client import AListClient, format_file_size
from app.clients.http_client import ExternalServiceError
from app.clients.player_client import PlayerClient
from app.models.media_model import MediaRepository


class PlaybackService:
    """首页聚合视图整理、详情页数据整理、MPC-HC 播放拉起与观看进度维护服务。"""

    def __init__(
        self,
        media_repo: MediaRepository,
        alist_client: AListClient,
        player_client: PlayerClient,
    ) -> None:
        self._media = media_repo
        self._alist = alist_client
        self._player = player_client

    def build_home_data(
        self,
        *,
        search: str = "",
        genre: str = "",
        year_raw: str = "",
        min_rating_raw: str = "",
        media_type: str = "",
    ) -> dict[str, Any]:
        year_val = int(year_raw) if (year_raw and year_raw.isdigit()) else None
        min_rating_val = None
        if min_rating_raw:
            try:
                min_rating_val = float(min_rating_raw)
            except ValueError:
                min_rating_val = None

        is_filtering = bool(search.strip() or genre.strip() or year_val is not None or min_rating_val is not None or media_type in ("movie", "tv"))

        all_works = self._media.list_works(sort="recent")
        filtered_works = (
            self._media.list_works(
                media_type=media_type if media_type in ("movie", "tv") else None,
                search=search,
                genre=genre,
                year=year_val,
                min_rating=min_rating_val,
                sort="rating" if min_rating_val else "recent",
            )
            if is_filtering
            else []
        )

        # 轮播优先挑选拥有横版背景图的高分/最新作品
        hero_candidates = [w for w in all_works if w.get("backdrop_path")] or all_works
        hero_items = [self._decorate_work_for_view(w) for w in hero_candidates[:6]]

        continue_watching = self._media.list_continue_watching(limit=12)
        for cw in continue_watching:
            cw["work"] = self._decorate_work_for_view(cw["work"])

        recent_items = [self._decorate_work_for_view(w) for w in all_works[:14]]
        movie_items = [self._decorate_work_for_view(w) for w in all_works if w["media_type"] == "movie"][:14]
        tv_items = [self._decorate_work_for_view(w) for w in all_works if w["media_type"] == "tv"][:14]

        top_rated_raw = self._media.list_works(sort="rating", limit=14)
        top_rated_items = [
            self._decorate_work_for_view(w)
            for w in top_rated_raw
            if float(w.get("tmdb_rating") or 0) >= 7.0 or len(top_rated_raw) <= 6
        ]

        return {
            "has_library": len(all_works) > 0,
            "total_count": len(all_works),
            "is_filtering": is_filtering,
            "filters": {
                "q": search,
                "genre": genre,
                "year": year_raw,
                "min_rating": min_rating_raw,
                "media_type": media_type,
            },
            "available_genres": self._media.list_distinct_genres(),
            "available_years": self._media.list_distinct_years(),
            "filtered_works": [self._decorate_work_for_view(w) for w in filtered_works],
            "hero_items": hero_items,
            "continue_watching": continue_watching,
            "recent_items": recent_items,
            "movie_items": movie_items,
            "tv_items": tv_items,
            "top_rated_items": top_rated_items,
        }

    def build_movie_detail(self, work_id: int) -> dict[str, Any] | None:
        work = self._media.get_work(work_id)
        if not work or work["media_type"] != "movie":
            return None

        decorated = self._decorate_work_for_view(work)
        files = self._media.get_media_files(work_id)
        for idx, f in enumerate(files, start=1):
            f["size_human"] = format_file_size(f["file_size"])
            if not f.get("version_label") or f["version_label"] == "标准版":
                f["display_version"] = f"版本 {idx} · {f['size_human']}" if len(files) > 1 else f"标准版 ({f['size_human']})"
            else:
                f["display_version"] = f"{f['version_label']} ({f['size_human']})"

        progress = self._media.get_movie_progress(work_id)
        return {
            "work": decorated,
            "files": files,
            "progress": progress,
            "watched": bool(progress and progress.get("watched")),
            "progress_percent": int(round(float(progress["progress_percent"]))) if progress else 0,
        }

    def build_tv_detail(self, work_id: int, selected_season: int | None = None) -> dict[str, Any] | None:
        work = self._media.get_work(work_id)
        if not work or work["media_type"] != "tv":
            return None

        decorated = self._decorate_work_for_view(work)
        seasons = self._media.get_seasons(work_id)
        active_season = selected_season
        if active_season is None:
            resume = self._media.resolve_resume_target(work_id)
            if resume and resume.get("episode"):
                active_season = int(resume["episode"]["season_number"])
            elif seasons:
                active_season = int(seasons[0]["season_number"])
            else:
                active_season = 1

        episodes = self._media.get_episodes(work_id, season_number=active_season)
        for ep in episodes:
            ep["progress_percent_int"] = int(round(float(ep.get("progress_percent") or 0)))
            ep["runtime_text"] = f"{ep['runtime']} 分钟" if ep.get("runtime") else ""

        all_files = self._media.get_media_files(work_id)
        unmatched_files = [f for f in all_files if f.get("match_status") == "unmatched"]
        for uf in unmatched_files:
            uf["size_human"] = format_file_size(uf["file_size"])

        resume_target = self._media.resolve_resume_target(work_id)
        resume_label = "立即播放"
        if resume_target and resume_target.get("episode"):
            rep = resume_target["episode"]
            if resume_target.get("progress_percent", 0) > 0:
                resume_label = f"继续播放 S{int(rep['season_number']):02d}E{int(rep['episode_number']):02d}"
            else:
                resume_label = f"播放 S{int(rep['season_number']):02d}E{int(rep['episode_number']):02d}"

        current_season_obj = next((s for s in seasons if int(s["season_number"]) == int(active_season)), None)

        return {
            "work": decorated,
            "seasons": seasons,
            "active_season": active_season,
            "current_season": current_season_obj,
            "episodes": episodes,
            "unmatched_files": unmatched_files,
            "all_files": all_files,
            "resume_target": resume_target,
            "resume_label": resume_label,
        }

    def launch_playback(
        self,
        *,
        work_id: int,
        episode_id: int | None = None,
        file_id: int | None = None,
    ) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到要播放的影视作品")

        target_file: dict[str, Any] | None = None
        target_episode: dict[str, Any] | None = None
        start_seconds = 0
        duration_seconds = int(work.get("runtime") or 0) * 60

        if file_id is not None:
            target_file = self._media.get_media_file_by_id(file_id)
            if not target_file or int(target_file["work_id"]) != int(work_id):
                raise ExternalServiceError("Library", "所选媒体文件不存在或不属于该作品")
            if target_file.get("episode_id"):
                episode_id = int(target_file["episode_id"])

        if work["media_type"] == "tv":
            if episode_id is not None:
                all_eps = self._media.get_episodes(work_id)
                target_episode = next((e for e in all_eps if int(e["id"]) == int(episode_id)), None)
                if not target_episode:
                    raise ExternalServiceError("Library", "未找到所选剧集单集")
                if target_file is None:
                    target_file = target_episode.get("primary_file")
                if not target_file:
                    raise ExternalServiceError("Library", "该集尚未关联网盘视频文件，请在下方或后台指定对应文件")
                if not target_episode.get("watched"):
                    start_seconds = int(target_episode.get("position_seconds") or 0)
                if target_episode.get("runtime"):
                    duration_seconds = int(target_episode["runtime"]) * 60
            else:
                resolved = self._media.resolve_resume_target(work_id)
                if not resolved or not resolved.get("media_file"):
                    raise ExternalServiceError("Library", "该剧集暂无可播放的关联视频文件")
                target_file = resolved["media_file"]
                target_episode = resolved.get("episode")
                episode_id = int(target_episode["id"]) if target_episode else None
                start_seconds = int(resolved.get("position_seconds") or 0)
                if target_episode and target_episode.get("runtime"):
                    duration_seconds = int(target_episode["runtime"]) * 60
        else:
            if target_file is None:
                resolved = self._media.resolve_resume_target(work_id)
                if not resolved or not resolved.get("media_file"):
                    raise ExternalServiceError("Library", "该电影暂无可播放的网盘视频文件")
                target_file = resolved["media_file"]
                start_seconds = int(resolved.get("position_seconds") or 0)
            else:
                prog = self._media.get_movie_progress(work_id)
                if prog and not prog.get("watched"):
                    start_seconds = int(prog.get("position_seconds") or 0)

        stream_info = self._alist.build_stream_url(target_file["alist_path"])

        def _on_tick(pos_sec: int) -> None:
            self._media.update_watch_progress(
                work_id=work_id,
                episode_id=episode_id,
                position_seconds=pos_sec,
                duration_seconds=duration_seconds if duration_seconds > 0 else 2700,
                media_file_id=int(target_file["id"]),
            )

        player_res = self._player.launch_stream(
            stream_info["stream_url"],
            start_seconds=start_seconds,
            on_session_update=_on_tick,
        )

        updated_prog = self._media.update_watch_progress(
            work_id=work_id,
            episode_id=episode_id,
            position_seconds=start_seconds if start_seconds > 0 else None,
            duration_seconds=duration_seconds if duration_seconds > 0 else 2700,
            media_file_id=int(target_file["id"]),
            increment_play=True,
        )

        ep_label = ""
        if target_episode:
            ep_label = f"S{int(target_episode['season_number']):02d}E{int(target_episode['episode_number']):02d} · {target_episode['title']}"

        return {
            "work_id": work_id,
            "work_title": (work.get("custom_title") or "").strip() or work["title"],
            "episode_id": episode_id,
            "episode_label": ep_label,
            "filename": target_file["filename"],
            "version_label": target_file.get("version_label") or "",
            "player_name": player_res["player_name"],
            "stream_url": stream_info["stream_url"],
            "progress": updated_prog,
        }

    @staticmethod
    def _decorate_work_for_view(work: dict[str, Any]) -> dict[str, Any]:
        d = dict(work)
        d["detail_url"] = f"/tv/{d['id']}" if d["media_type"] == "tv" else f"/movies/{d['id']}"
        d["media_type_label"] = "剧集" if d["media_type"] == "tv" else "电影"
        d["rating_text"] = f"{float(d['tmdb_rating']):.1f}" if float(d.get("tmdb_rating") or 0) > 0 else "暂无评分"
        d["runtime_text"] = f"{d['runtime']} 分钟" if int(d.get("runtime") or 0) > 0 else ""
        d["genres_short"] = " / ".join((d.get("genres") or [])[:3])

        # 提取主补充评分（IMDb、烂番茄）便于首页轮播与详情快速渲染
        imdb_badge = None
        rt_badge = None
        for r in d.get("ratings") or []:
            if r.get("source") == "imdb":
                imdb_badge = r
            elif r.get("source") == "tomatoes":
                rt_badge = r
        d["imdb_badge"] = imdb_badge
        d["rt_badge"] = rt_badge
        return d
