from __future__ import annotations

import posixpath
import threading
import uuid
from typing import Any

from app.clients.alist_client import AListClient, format_file_size
from app.clients.http_client import ExternalServiceError
from app.clients.mdblist_client import MDBListClient
from app.clients.tmdb_client import TMDBClient
from app.config import ConfigManager
from app.models.media_model import MediaRepository
from app.models.state_model import LocalStateRepository
from app.services.recognition_service import RecognitionService


PRESET_OBFUSCATED_SAMPLES: list[dict[str, str]] = [
    {
        "label": "谐音+拼音+分隔符：周·chu·除·三·hai",
        "filename": "【先转存防和谐】周·chu·除·三·hai.2023.2160p.WEB-DL.H265.mp4",
        "parent_path": "/资源/电影分享",
    },
    {
        "label": "夹杂拼音+点号：肖·shen·克·的·jiu·赎",
        "filename": "【夸克首发】肖·shen·克·的·jiu·赎.1994.4K.HDR.10bit-珍藏版.mkv",
        "parent_path": "/baidu/我的资源/高分经典",
    },
    {
        "label": "首字母缩写+剧集目录：XDL.S01E01",
        "filename": "【关注公众号防失联】XDL.S01E01.1080p.BluRay.x265-NEW字幕组.mp4",
        "parent_path": "/资源/来自：分享/兄弟连",
    },
    {
        "label": "繁简混用+谐音改写：無·堅·道",
        "filename": "[免费分享严禁商用]無·堅·道.Infernal.Affairs.2002.1080p.国粤双语.mkv",
        "parent_path": "/baidu/港片合集",
    },
]


class LibraryService:
    """媒体扫描、入库资料补全、本地图片落盘与后台管理业务服务。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        media_repo: MediaRepository,
        state_repo: LocalStateRepository,
        alist_client: AListClient,
        tmdb_client: TMDBClient,
        mdblist_client: MDBListClient,
        recognition_service: RecognitionService,
    ) -> None:
        self._cfg = config_manager
        self._media = media_repo
        self._state = state_repo
        self._alist = alist_client
        self._tmdb = tmdb_client
        self._mdblist = mdblist_client
        self._recognizer = recognition_service

    # --- 1. AList 目录浏览与后台扫描识别任务 ---
    def browse_alist(self, path: str = "/", refresh: bool = False) -> dict[str, Any]:
        entries = self._alist.list_dir(path=path, refresh=refresh)
        existing_paths = self._media.get_existing_alist_paths()
        for item in entries:
            item["already_imported"] = item["path"] in existing_paths

        norm_path = "/" if not path or path == "/" else "/" + path.strip("/")
        breadcrumbs = [{"name": "网盘根目录", "path": "/"}]
        if norm_path != "/":
            acc = ""
            for seg in norm_path.strip("/").split("/"):
                acc = f"{acc}/{seg}"
                breadcrumbs.append({"name": seg, "path": acc})

        return {
            "current_path": norm_path,
            "breadcrumbs": breadcrumbs,
            "entries": entries,
        }

    def start_scan_task(
        self,
        selected_paths: list[str],
        filename_overrides: dict[str, str] | None = None,
    ) -> str:
        task_id = f"scan_{uuid.uuid4().hex[:12]}"
        self._state.create_task(task_id, "scan", total=max(1, len(selected_paths)), summary="正在扫描网盘目录...")
        worker = threading.Thread(
            target=self._run_scan_worker,
            args=(task_id, list(selected_paths), dict(filename_overrides or {})),
            daemon=True,
        )
        worker.start()
        return task_id

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        return self._state.get_task(task_id)

    def get_import_presets(self) -> dict[str, Any]:
        return {
            "samples": PRESET_OBFUSCATED_SAMPLES,
            "llm_enabled": self._cfg.settings.llm_ready,
            "mdblist_enabled": self._cfg.settings.mdblist_ready,
        }

    def _run_scan_worker(
        self,
        task_id: str,
        selected_paths: list[str],
        filename_overrides: dict[str, str] | None = None,
    ) -> None:
        overrides = filename_overrides or {}
        try:
            video_files = self._alist.collect_video_files(selected_paths)
            if not video_files:
                self._state.update_task(
                    task_id,
                    status="completed",
                    total=0,
                    completed=0,
                    summary="所选目录中未发现可识别的视频文件",
                    result={"items": [], "counts": {"confirmable": 0, "needs_review": 0, "unrecognized": 0}},
                )
                return

            existing_paths = self._media.get_existing_alist_paths()
            total = len(video_files)
            self._state.update_task(task_id, total=total, completed=0, summary=f"共发现 {total} 个视频文件，开始识别...")

            recognized_items: list[dict[str, Any]] = []
            counts = {"confirmable": 0, "needs_review": 0, "unrecognized": 0}

            # 同目录下同剧集的多集文件共享作品搜索上下文，提升多集剧识别速度与一致性
            for idx, vf in enumerate(video_files, start=1):
                effective_filename = (overrides.get(vf["alist_path"]) or vf["filename"]).strip()
                self._state.update_task(
                    task_id,
                    completed=idx - 1,
                    current_label=effective_filename,
                    summary=f"正在识别 ({idx}/{total})：{effective_filename}",
                )
                try:
                    rec = self._recognizer.recognize_file(
                        filename=effective_filename,
                        parent_path=vf["parent_path"],
                        alist_path=vf["alist_path"],
                        file_size=vf["size"],
                        use_cache=vf["alist_path"] not in overrides,
                    )
                except Exception as exc:
                    # 单个文件出错绝不中断整批扫描
                    rec = {
                        "alist_path": vf["alist_path"],
                        "filename": vf["filename"],
                        "parent_path": vf["parent_path"],
                        "file_size": vf["size"],
                        "raw_name": vf["filename"],
                        "cleaned_name": vf["filename"],
                        "inferred_title": vf["filename"],
                        "secondary_title": "",
                        "year": None,
                        "season_number": None,
                        "episode_number": None,
                        "version_label": "标准版",
                        "media_type": "movie",
                        "matched_work": None,
                        "candidates": [],
                        "confidence": 0.0,
                        "bucket": "unrecognized",
                        "bucket_label": "未识别",
                        "source": "rule",
                        "source_label": "规则识别",
                        "is_obfuscated": False,
                        "applied_rules": [],
                        "reasoning": f"识别过程中发生异常（{exc}），请手动搜索并指定 TMDB 作品。",
                    }

                rec["size_human"] = format_file_size(vf["size"])
                rec["already_imported"] = vf["alist_path"] in existing_paths
                counts[rec["bucket"]] = counts.get(rec["bucket"], 0) + 1
                recognized_items.append(rec)

            self._state.update_task(
                task_id,
                status="completed",
                total=total,
                completed=total,
                current_label="",
                summary=f"识别完成：可确认 {counts['confirmable']} 项，待核对 {counts['needs_review']} 项，未识别 {counts['unrecognized']} 项",
                result={"items": recognized_items, "counts": counts},
            )
        except Exception as exc:
            self._state.update_task(
                task_id,
                status="failed",
                error=str(exc),
                summary=f"扫描识别失败：{exc}",
            )

    def search_tmdb_manual(self, query: str, media_type: str | None = None, year: int | None = None) -> list[dict[str, Any]]:
        results = self._tmdb.search_candidates(query=query, media_type=media_type, year=year)
        hydrated: list[dict[str, Any]] = []
        for item in results[:10]:
            copied = dict(item)
            poster_remote = copied.get("poster_remote") or ""
            copied["poster_local"] = (
                self._tmdb.cache_image(poster_remote, size="w342", category="thumbs") if poster_remote else ""
            )
            hydrated.append(copied)
        return hydrated

    # --- 2. 批量确认入库与全量资料刮削任务 ---
    def start_import_task(self, confirmed_items: list[dict[str, Any]]) -> str:
        task_id = f"import_{uuid.uuid4().hex[:12]}"
        self._state.create_task(task_id, "import", total=max(1, len(confirmed_items)), summary="准备入库并刮削影视资料...")
        worker = threading.Thread(
            target=self._run_import_worker,
            args=(task_id, list(confirmed_items)),
            daemon=True,
        )
        worker.start()
        return task_id

    def import_items_sync(self, confirmed_items: list[dict[str, Any]], task_id: str | None = None) -> dict[str, Any]:
        """按 (media_type, tmdb_id) 聚合文件，拉取完整资料、多平台评分与本地图片缓存后写入数据库。"""
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for item in confirmed_items:
            mtype = str(item.get("media_type") or "").strip()
            tmdb_id_raw = item.get("tmdb_id")
            if mtype not in ("movie", "tv") or not tmdb_id_raw:
                continue
            grouped.setdefault((mtype, int(tmdb_id_raw)), []).append(item)

        total_groups = len(grouped)
        if task_id:
            self._state.update_task(task_id, total=max(1, total_groups), completed=0)

        imported_works: list[dict[str, Any]] = []
        errors: list[str] = []

        for idx, ((mtype, tmdb_id), file_entries) in enumerate(grouped.items(), start=1):
            sample_title = file_entries[0].get("title_hint") or f"TMDB #{tmdb_id}"
            if task_id:
                self._state.update_task(
                    task_id,
                    completed=idx - 1,
                    current_label=str(sample_title),
                    summary=f"正在刮削资料并缓存图片 ({idx}/{total_groups})：{sample_title}",
                )
            try:
                root_dir = self._infer_root_dir([str(f.get("alist_path") or "") for f in file_entries])
                work_id = self._scrape_and_persist_work(
                    media_type=mtype,
                    tmdb_id=tmdb_id,
                    alist_root_path=root_dir,
                    file_entries=file_entries,
                )
                saved_work = self._media.get_work(work_id)
                if saved_work:
                    imported_works.append(
                        {
                            "id": saved_work["id"],
                            "title": saved_work["display_title"],
                            "media_type": saved_work["media_type"],
                            "file_count": len(file_entries),
                        }
                    )
            except Exception as exc:
                # 单部作品失败记录错误，不中断后续作品入库
                errors.append(f"{sample_title}: {exc}")

        summary_msg = f"成功入库 {len(imported_works)} 部作品"
        if errors:
            summary_msg += f"（{len(errors)} 部失败：{'; '.join(errors[:2])}）"

        result_payload = {"imported": imported_works, "errors": errors}
        if task_id:
            self._state.update_task(
                task_id,
                status="completed" if (imported_works or not errors) else "failed",
                total=max(1, total_groups),
                completed=max(1, total_groups),
                current_label="",
                summary=summary_msg,
                result=result_payload,
                error="; ".join(errors) if (errors and not imported_works) else "",
            )
        return result_payload

    def _run_import_worker(self, task_id: str, confirmed_items: list[dict[str, Any]]) -> None:
        try:
            self.import_items_sync(confirmed_items, task_id=task_id)
        except Exception as exc:
            self._state.update_task(task_id, status="failed", error=str(exc), summary=f"入库任务异常：{exc}")

    def _scrape_and_persist_work(
        self,
        *,
        media_type: str,
        tmdb_id: int,
        alist_root_path: str = "",
        file_entries: list[dict[str, Any]] | None = None,
        target_work_id: int | None = None,
    ) -> int:
        detail = self._tmdb.fetch_work_detail(media_type, tmdb_id)
        ratings = self._mdblist.fetch_ratings(media_type, tmdb_id)

        poster_local = self._tmdb.cache_image(detail["poster_remote"], size="w500", category="posters")
        backdrop_local = self._tmdb.cache_image(detail["backdrop_remote"], size="w1280", category="backdrops")
        logo_local = self._tmdb.cache_image(detail["logo_remote"], size="w500", category="logos")

        cast_cached: list[dict[str, Any]] = []
        for person in detail.get("cast") or []:
            prof_local = (
                self._tmdb.cache_image(person["profile_remote"], size="w185", category="cast")
                if person.get("profile_remote")
                else ""
            )
            cast_cached.append(
                {
                    "name": person["name"],
                    "character": person["character"],
                    "profile_path": prof_local,
                }
            )

        work_payload = {
            "media_type": media_type,
            "tmdb_id": int(tmdb_id),
            "imdb_id": detail["imdb_id"],
            "title": detail["title"],
            "original_title": detail["original_title"],
            "year": detail["year"],
            "release_date": detail["release_date"],
            "runtime": detail["runtime"],
            "overview": detail["overview"],
            "genres": detail["genres"],
            "cast": cast_cached,
            "tmdb_rating": detail["tmdb_rating"],
            "tmdb_votes": detail["tmdb_votes"],
            "ratings": ratings,
            "poster_path": poster_local,
            "backdrop_path": backdrop_local,
            "logo_path": logo_local,
            "tmdb_poster_remote": detail["poster_remote"],
            "tmdb_backdrop_remote": detail["backdrop_remote"],
            "tmdb_logo_remote": detail["logo_remote"],
            "alist_root_path": alist_root_path,
        }

        if target_work_id is not None:
            # 重新匹配到另一部 TMDB 作品时，先更新原记录的 media_type 与 tmdb_id，再刷新字段
            existing_target = self._media.get_work_by_tmdb(media_type, tmdb_id)
            if existing_target and int(existing_target["id"]) != int(target_work_id):
                raise ExternalServiceError("Library", f"媒体库中已存在《{existing_target['display_title']}》，无法重复合并到同一条目")
            self._media.update_work_fields(
                target_work_id,
                {"media_type": media_type, "tmdb_id": int(tmdb_id), "custom_title": ""},
            )
            work_payload["custom_title"] = ""

        work_id = self._media.upsert_work(work_payload)

        if media_type == "tv":
            seasons_raw = detail.get("seasons") or []
            # 控制自动拉取季详情的范围：优先包含文件涉及的季 + 前 8 个常规季，防止超长连载动画一次性请求几十季
            needed_seasons = {
                int(f["season_number"])
                for f in (file_entries or [])
                if f.get("season_number") is not None
            }
            for s in seasons_raw[:8]:
                needed_seasons.add(int(s["season_number"]))

            seasons_to_save: list[dict[str, Any]] = []
            episodes_to_save: list[dict[str, Any]] = []

            for s in seasons_raw:
                s_num = int(s["season_number"])
                s_poster = (
                    self._tmdb.cache_image(s["poster_remote"], size="w342", category="seasons")
                    if s.get("poster_remote")
                    else poster_local
                )
                seasons_to_save.append(
                    {
                        "season_number": s_num,
                        "name": s["name"],
                        "overview": s["overview"],
                        "air_date": s["air_date"],
                        "episode_count": s["episode_count"],
                        "poster_path": s_poster,
                    }
                )
                if s_num in needed_seasons:
                    try:
                        eps = self._tmdb.fetch_season_episodes(tmdb_id, s_num)
                    except ExternalServiceError:
                        eps = []
                    for ep in eps:
                        still_local = (
                            self._tmdb.cache_image(ep["still_remote"], size="w500", category="stills")
                            if ep.get("still_remote")
                            else ""
                        )
                        episodes_to_save.append(
                            {
                                "season_number": s_num,
                                "episode_number": ep["episode_number"],
                                "title": ep["title"],
                                "overview": ep["overview"],
                                "air_date": ep["air_date"],
                                "runtime": ep["runtime"] or detail["runtime"],
                                "still_path": still_local,
                                "tmdb_rating": ep["tmdb_rating"],
                            }
                        )

            self._media.replace_seasons_and_episodes(work_id, seasons_to_save, episodes_to_save)
        else:
            self._media.replace_seasons_and_episodes(work_id, [], [])

        if file_entries:
            for fe in file_entries:
                alist_p = str(fe.get("alist_path") or "").strip()
                if not alist_p:
                    continue
                fname = str(fe.get("filename") or posixpath.basename(alist_p))
                s_no = int(fe["season_number"]) if fe.get("season_number") not in (None, "") else None
                e_no = int(fe["episode_number"]) if fe.get("episode_number") not in (None, "") else None
                match_st = "matched" if (media_type == "movie" or (s_no is not None and e_no is not None)) else "unmatched"
                self._media.upsert_media_file(
                    work_id=work_id,
                    alist_path=alist_p,
                    filename=fname,
                    file_size=int(fe.get("file_size") or 0),
                    version_label=str(fe.get("version_label") or "标准版"),
                    season_number=s_no if media_type == "tv" else None,
                    episode_number=e_no if media_type == "tv" else None,
                    match_status=match_st,
                    recognition_trace=fe.get("recognition_trace") or {},
                )

        if media_type == "tv":
            self._media.rebind_episode_files_for_work(work_id)
        return work_id

    # --- 3. 后台管理：刷新资料、重匹配、切换海报/Logo/背景图、调整季集 ---
    def refresh_work(self, work_id: int) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        existing_files = self._media.get_media_files(work_id)
        self._scrape_and_persist_work(
            media_type=work["media_type"],
            tmdb_id=int(work["tmdb_id"]),
            alist_root_path=work.get("alist_root_path") or "",
            file_entries=existing_files,
        )
        return self._media.get_work(work_id) or work

    def rematch_work(self, work_id: int, new_media_type: str, new_tmdb_id: int) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        existing_files = self._media.get_media_files(work_id)
        self._scrape_and_persist_work(
            media_type=new_media_type,
            tmdb_id=int(new_tmdb_id),
            alist_root_path=work.get("alist_root_path") or "",
            file_entries=existing_files,
            target_work_id=work_id,
        )
        return self._media.get_work(work_id) or work

    def get_work_candidate_images(self, work_id: int) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        raw = self._tmdb.fetch_candidate_images(work["media_type"], int(work["tmdb_id"]))

        # 将预览缩略图全部下载到本地缓存，确保页面绝不直接请求外链
        size_by_kind = {"logos": "w300", "posters": "w342", "backdrops": "w780"}
        current_by_kind = {
            "logos": work.get("tmdb_logo_remote") or "",
            "posters": work.get("tmdb_poster_remote") or "",
            "backdrops": work.get("tmdb_backdrop_remote") or "",
        }
        localized: dict[str, list[dict[str, Any]]] = {}
        for kind, items in raw.items():
            out_list: list[dict[str, Any]] = []
            for it in items:
                local_preview = self._tmdb.cache_image(it["file_path"], size=size_by_kind[kind], category="candidates")
                if not local_preview:
                    continue
                enriched = dict(it)
                enriched["preview_path"] = local_preview
                enriched["selected"] = it["file_path"] == current_by_kind[kind]
                out_list.append(enriched)
            localized[kind] = out_list
        return localized

    def switch_work_image(self, work_id: int, kind: str, remote_file_path: str) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        if kind not in ("logo", "poster", "backdrop"):
            raise ExternalServiceError("Library", f"不支持的图片类型：{kind}")

        if not remote_file_path:
            # 允许清空 Logo 切回文字标题
            if kind == "logo":
                self._media.update_work_fields(work_id, {"logo_path": "", "tmdb_logo_remote": ""})
                return self._media.get_work(work_id) or work
            raise ExternalServiceError("Library", "请选择有效的候选图片")

        cfg_map = {
            "logo": ("w500", "logos", "logo_path", "tmdb_logo_remote"),
            "poster": ("w500", "posters", "poster_path", "tmdb_poster_remote"),
            "backdrop": ("w1280", "backdrops", "backdrop_path", "tmdb_backdrop_remote"),
        }
        size, cat, local_col, remote_col = cfg_map[kind]
        local_rel = self._tmdb.cache_image(remote_file_path, size=size, category=cat)
        if not local_rel:
            raise ExternalServiceError("TMDB", "下载所选图片到本地缓存失败，请稍后重试")

        self._media.update_work_fields(work_id, {local_col: local_rel, remote_col: remote_file_path})
        return self._media.get_work(work_id) or work

    def update_display_title(self, work_id: int, custom_title: str) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        self._media.update_work_fields(work_id, {"custom_title": (custom_title or "").strip()})
        return self._media.get_work(work_id) or work

    def build_admin_list(
        self,
        *,
        search: str = "",
        media_type: str = "",
        sort: str = "recent",
    ) -> dict[str, Any]:
        all_works = self._media.list_works(sort="recent")
        filtered = self._media.list_works(
            media_type=media_type if media_type in ("movie", "tv") else None,
            search=search,
            sort=sort if sort in ("recent", "rating", "year", "title") else "recent",
        )
        for w in filtered:
            w["detail_url"] = f"/tv/{w['id']}" if w["media_type"] == "tv" else f"/movies/{w['id']}"
            w["media_type_label"] = "剧集" if w["media_type"] == "tv" else "电影"
            w["rating_text"] = f"{float(w['tmdb_rating']):.1f}" if float(w.get("tmdb_rating") or 0) > 0 else "—"

        movie_count = sum(1 for w in all_works if w["media_type"] == "movie")
        tv_count = sum(1 for w in all_works if w["media_type"] == "tv")
        unmatched_total = sum(int(w.get("unmatched_file_count") or 0) for w in all_works)

        return {
            "works": filtered,
            "stats": {
                "total": len(all_works),
                "movies": movie_count,
                "tv": tv_count,
                "unmatched_files": unmatched_total,
            },
            "filters": {
                "q": search,
                "media_type": media_type,
                "sort": sort,
            },
        }

    def build_admin_work_detail(self, work_id: int) -> dict[str, Any] | None:
        work = self._media.get_work(work_id)
        if not work:
            return None
        work["detail_url"] = f"/tv/{work['id']}" if work["media_type"] == "tv" else f"/movies/{work['id']}"
        work["media_type_label"] = "剧集" if work["media_type"] == "tv" else "电影"

        seasons = self._media.get_seasons(work_id) if work["media_type"] == "tv" else []
        episodes = self._media.get_episodes(work_id) if work["media_type"] == "tv" else []
        files = self._media.get_media_files(work_id)
        for f in files:
            f["size_human"] = format_file_size(f["file_size"])

        return {
            "work": work,
            "seasons": seasons,
            "episodes": episodes,
            "files": files,
        }

    def map_file_to_episode(
        self,
        *,
        work_id: int,
        file_id: int,
        season_number: int | None,
        episode_number: int | None,
    ) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        if season_number is not None:
            self.ensure_season_loaded(work_id, int(season_number))
        ok = self._media.update_file_episode_mapping(
            file_id=file_id,
            work_id=work_id,
            season_number=season_number,
            episode_number=episode_number,
        )
        if not ok:
            raise ExternalServiceError("Library", "未找到要调整映射的媒体文件")
        return self.build_admin_work_detail(work_id) or {"work": work}

    def update_file_version(self, *, work_id: int, file_id: int, version_label: str) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        ok = self._media.update_file_version_label(file_id=file_id, work_id=work_id, version_label=version_label)
        if not ok:
            raise ExternalServiceError("Library", "未找到要修改版本标签的媒体文件")
        return self.build_admin_work_detail(work_id) or {"work": work}

    def attach_alist_file_to_work(
        self,
        *,
        work_id: int,
        alist_path: str,
        version_label: str = "",
        season_number: int | None = None,
        episode_number: int | None = None,
    ) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        meta = self._alist.get_item_meta(alist_path)
        if meta.get("is_dir"):
            raise ExternalServiceError("AList", "请选择单个视频文件而非文件夹")
        fname = str(meta.get("name") or posixpath.basename(alist_path))
        fsize = int(meta.get("size") or 0)
        if work["media_type"] == "tv" and season_number is not None:
            self.ensure_season_loaded(work_id, int(season_number))
        match_st = (
            "matched"
            if (work["media_type"] == "movie" or (season_number is not None and episode_number is not None))
            else "unmatched"
        )
        self._media.upsert_media_file(
            work_id=work_id,
            alist_path=alist_path,
            filename=fname,
            file_size=fsize,
            version_label=(version_label or "").strip() or "标准版",
            season_number=season_number if work["media_type"] == "tv" else None,
            episode_number=episode_number if work["media_type"] == "tv" else None,
            match_status=match_st,
        )
        if work["media_type"] == "tv":
            self._media.rebind_episode_files_for_work(work_id)
        return self.build_admin_work_detail(work_id) or {"work": work}

    def remove_media_file(self, *, work_id: int, file_id: int) -> dict[str, Any]:
        work = self._media.get_work(work_id)
        if not work:
            raise ExternalServiceError("Library", "未找到该影视条目")
        ok = self._media.delete_media_file(file_id=file_id, work_id=work_id)
        if not ok:
            raise ExternalServiceError("Library", "未找到要移除的媒体文件")
        return self.build_admin_work_detail(work_id) or {"work": work}

    def delete_work(self, work_id: int) -> bool:
        return self._media.delete_work(work_id)

    def ensure_season_loaded(self, work_id: int, season_number: int) -> None:
        """若用户切换到某季且该季尚未抓取单集详情，自动从 TMDB 补抓并缓存剧照。"""
        work = self._media.get_work(work_id)
        if not work or work["media_type"] != "tv":
            return
        existing_eps = self._media.get_episodes(work_id, season_number=season_number)
        if existing_eps:
            return
        try:
            eps = self._tmdb.fetch_season_episodes(int(work["tmdb_id"]), int(season_number))
        except ExternalServiceError:
            return
        if not eps:
            return

        all_seasons = self._media.get_seasons(work_id)
        existing_other_eps = self._media.get_episodes(work_id)
        merged_eps: list[dict[str, Any]] = [
            {
                "season_number": e["season_number"],
                "episode_number": e["episode_number"],
                "title": e["title"],
                "overview": e["overview"],
                "air_date": e["air_date"],
                "runtime": e["runtime"],
                "still_path": e["still_path"],
                "tmdb_rating": e["tmdb_rating"],
            }
            for e in existing_other_eps
        ]
        for ep in eps:
            still_local = (
                self._tmdb.cache_image(ep["still_remote"], size="w500", category="stills")
                if ep.get("still_remote")
                else ""
            )
            merged_eps.append(
                {
                    "season_number": int(season_number),
                    "episode_number": ep["episode_number"],
                    "title": ep["title"],
                    "overview": ep["overview"],
                    "air_date": ep["air_date"],
                    "runtime": ep["runtime"] or work["runtime"],
                    "still_path": still_local,
                    "tmdb_rating": ep["tmdb_rating"],
                }
            )
        self._media.replace_seasons_and_episodes(work_id, all_seasons, merged_eps)

    @staticmethod
    def _infer_root_dir(paths: list[str]) -> str:
        valid = [p for p in paths if p]
        if not valid:
            return ""
        return posixpath.dirname(valid[0]) or "/"
