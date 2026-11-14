from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.clients.http_client import ExternalServiceError, RateLimitedHttpClient
from app.config import ConfigManager, is_effective_value, is_placeholder_only
from app.models.state_model import LocalStateRepository

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


class TMDBClient:
    """TMDB 影视资料与图片本地缓存客户端封装。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        state_repo: LocalStateRepository | None = None,
        http_client: RateLimitedHttpClient | None = None,
    ) -> None:
        self._cfg = config_manager
        self._state = state_repo
        self._http = http_client or RateLimitedHttpClient("TMDB", min_interval=0.18, max_retries=3, timeout=18.0)

    def _headers(self, token_override: str | None = None) -> dict[str, str]:
        token = (token_override if token_override is not None else self._cfg.settings.tmdb_token).strip()
        if not is_effective_value(token):
            if is_placeholder_only(token):
                raise ExternalServiceError("TMDB", f"TMDB_TOKEN 当前为占位值（{token}），请填写有效的只读访问令牌")
            raise ExternalServiceError("TMDB", "尚未配置 TMDB 访问令牌（Bearer Token）")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _get_json(self, path: str, params: dict[str, Any] | None = None, token_override: str | None = None) -> dict[str, Any]:
        resp = self._http.request(
            "GET",
            f"{TMDB_API_BASE}{path}",
            headers=self._headers(token_override),
            params=params,
        )
        if resp.status_code == 401:
            raise ExternalServiceError("TMDB", "TMDB 访问令牌无效或已过期 (HTTP 401)，请确认填写的是 Bearer 读访问令牌", status_code=401)
        if resp.status_code == 404:
            raise ExternalServiceError("TMDB", "未在 TMDB 找到对应条目 (HTTP 404)", status_code=404)
        if resp.status_code >= 400:
            raise ExternalServiceError("TMDB", f"TMDB 接口返回错误 (HTTP {resp.status_code})", status_code=resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise ExternalServiceError("TMDB", "TMDB 返回了无法解析的响应内容") from exc

    def check_connection(self, token: str | None = None) -> tuple[bool, str, dict[str, Any]]:
        tok = (token if token is not None else self._cfg.settings.tmdb_token).strip()
        if not is_effective_value(tok):
            if is_placeholder_only(tok):
                return False, f"TMDB_TOKEN 当前为占位值（{tok}），请填入有效的只读访问令牌", {}
            return False, "请填写 TMDB 只读访问令牌（Bearer Token）", {}

        try:
            data = self._get_json("/configuration", token_override=tok)
            img_base = (data.get("images") or {}).get("secure_base_url") or TMDB_IMAGE_BASE
            return True, f"TMDB 验证通过（图片源 {img_base}）", {"image_base": img_base}
        except ExternalServiceError as exc:
            return False, exc.message, {}
        except Exception as exc:
            return False, f"TMDB 检测异常：{exc}", {}

    def search_candidates(
        self,
        query: str,
        media_type: str | None = None,
        year: int | None = None,
    ) -> list[dict[str, Any]]:
        clean_q = (query or "").strip()
        if not clean_q:
            return []

        params: dict[str, Any] = {
            "query": clean_q,
            "language": "zh-CN",
            "include_adult": "false",
            "page": 1,
        }
        if media_type == "movie":
            if year:
                params["year"] = int(year)
            data = self._get_json("/search/movie", params=params)
            raw_list = data.get("results") or []
            return [self._normalize_search_item(it, forced_type="movie") for it in raw_list if it.get("id")]

        if media_type == "tv":
            if year:
                params["first_air_date_year"] = int(year)
            data = self._get_json("/search/tv", params=params)
            raw_list = data.get("results") or []
            return [self._normalize_search_item(it, forced_type="tv") for it in raw_list if it.get("id")]

        data = self._get_json("/search/multi", params=params)
        results: list[dict[str, Any]] = []
        for it in data.get("results") or []:
            mtype = it.get("media_type")
            if mtype in ("movie", "tv") and it.get("id"):
                norm = self._normalize_search_item(it, forced_type=mtype)
                results.append(norm)
        return results

    @staticmethod
    def _normalize_search_item(item: dict[str, Any], forced_type: str) -> dict[str, Any]:
        is_movie = forced_type == "movie"
        title = (item.get("title") if is_movie else item.get("name")) or ""
        orig_title = (item.get("original_title") if is_movie else item.get("original_name")) or ""
        date_str = (item.get("release_date") if is_movie else item.get("first_air_date")) or ""
        year = None
        if len(date_str) >= 4 and date_str[:4].isdigit():
            year = int(date_str[:4])

        poster_remote = item.get("poster_path") or ""
        return {
            "tmdb_id": int(item["id"]),
            "media_type": forced_type,
            "title": title or orig_title,
            "original_title": orig_title,
            "year": year,
            "release_date": date_str,
            "overview": item.get("overview") or "",
            "tmdb_rating": round(float(item.get("vote_average") or 0.0), 1),
            "tmdb_votes": int(item.get("vote_count") or 0),
            "popularity": float(item.get("popularity") or 0.0),
            "poster_remote": poster_remote,
            "backdrop_remote": item.get("backdrop_path") or "",
        }

    def fetch_work_detail(self, media_type: str, tmdb_id: int) -> dict[str, Any]:
        """获取电影或剧集的完整资料（含中英文标题、简介、演职员、Logo、剧集季列表）。"""
        if media_type not in ("movie", "tv"):
            raise ExternalServiceError("TMDB", f"不支持的媒体类型：{media_type}")

        data = self._get_json(
            f"/{media_type}/{int(tmdb_id)}",
            params={
                "language": "zh-CN",
                "append_to_response": "credits,external_ids,images",
                "include_image_language": "zh,zh-CN,zh-TW,cn,en,null",
            },
        )

        # 若中文简介为空，回退拉取英文简介
        overview = (data.get("overview") or "").strip()
        if not overview:
            try:
                en_data = self._get_json(f"/{media_type}/{int(tmdb_id)}", params={"language": "en-US"})
                overview = (en_data.get("overview") or "").strip()
            except ExternalServiceError:
                pass

        is_movie = media_type == "movie"
        title = (data.get("title") if is_movie else data.get("name")) or ""
        original_title = (data.get("original_title") if is_movie else data.get("original_name")) or ""
        date_str = (data.get("release_date") if is_movie else data.get("first_air_date")) or ""
        year = int(date_str[:4]) if (len(date_str) >= 4 and date_str[:4].isdigit()) else None

        if is_movie:
            runtime = int(data.get("runtime") or 0)
        else:
            ep_runtimes = data.get("episode_run_time") or []
            runtime = int(ep_runtimes[0]) if ep_runtimes else 0

        genres = [str(g["name"]) for g in (data.get("genres") or []) if g.get("name")]
        ext_ids = data.get("external_ids") or {}
        imdb_id = str(data.get("imdb_id") or ext_ids.get("imdb_id") or "")

        images_block = data.get("images") or {}
        best_logo = self._pick_best_image(images_block.get("logos") or [], prefer_png=True)
        best_poster = data.get("poster_path") or self._pick_best_image(images_block.get("posters") or [])
        best_backdrop = data.get("backdrop_path") or self._pick_best_image(images_block.get("backdrops") or [], prefer_null_lang=True)

        credits = data.get("credits") or {}
        cast_list: list[dict[str, Any]] = []
        for person in (credits.get("cast") or [])[:12]:
            cast_list.append(
                {
                    "name": person.get("name") or "",
                    "character": person.get("character") or "",
                    "profile_remote": person.get("profile_path") or "",
                }
            )

        seasons_summary: list[dict[str, Any]] = []
        if not is_movie:
            for s in data.get("seasons") or []:
                s_num = s.get("season_number")
                if s_num is None:
                    continue
                # 常规优先保留正片季（season >= 1）；若只有第 0 季则也保留
                seasons_summary.append(
                    {
                        "season_number": int(s_num),
                        "name": s.get("name") or f"第 {s_num} 季",
                        "overview": s.get("overview") or "",
                        "air_date": s.get("air_date") or "",
                        "episode_count": int(s.get("episode_count") or 0),
                        "poster_remote": s.get("poster_path") or "",
                    }
                )
            regular_seasons = [s for s in seasons_summary if s["season_number"] > 0]
            if regular_seasons:
                seasons_summary = regular_seasons

        return {
            "media_type": media_type,
            "tmdb_id": int(tmdb_id),
            "imdb_id": imdb_id,
            "title": title or original_title,
            "original_title": original_title,
            "year": year,
            "release_date": date_str,
            "runtime": runtime,
            "overview": overview,
            "genres": genres,
            "tmdb_rating": round(float(data.get("vote_average") or 0.0), 1),
            "tmdb_votes": int(data.get("vote_count") or 0),
            "poster_remote": best_poster or "",
            "backdrop_remote": best_backdrop or "",
            "logo_remote": best_logo or "",
            "cast": cast_list,
            "seasons": seasons_summary,
        }

    def fetch_season_episodes(self, tmdb_id: int, season_number: int) -> list[dict[str, Any]]:
        data = self._get_json(
            f"/tv/{int(tmdb_id)}/season/{int(season_number)}",
            params={"language": "zh-CN"},
        )
        episodes: list[dict[str, Any]] = []
        for ep in data.get("episodes") or []:
            ep_num = ep.get("episode_number")
            if ep_num is None:
                continue
            episodes.append(
                {
                    "season_number": int(season_number),
                    "episode_number": int(ep_num),
                    "title": ep.get("name") or f"第 {ep_num} 集",
                    "overview": ep.get("overview") or "",
                    "air_date": ep.get("air_date") or "",
                    "runtime": int(ep.get("runtime") or 0),
                    "still_remote": ep.get("still_path") or "",
                    "tmdb_rating": round(float(ep.get("vote_average") or 0.0), 1),
                }
            )
        return episodes

    def fetch_candidate_images(self, media_type: str, tmdb_id: int) -> dict[str, list[dict[str, Any]]]:
        """获取作品在 TMDB 上的多张候选 Logo、海报与背景图（供后台管理切换）。"""
        data = self._get_json(
            f"/{media_type}/{int(tmdb_id)}/images",
            params={"include_image_language": "zh,zh-CN,zh-TW,cn,en,null"},
        )

        def format_items(items: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
            sorted_items = sorted(items, key=lambda x: self._image_sort_key(x), reverse=True)
            out: list[dict[str, Any]] = []
            for it in sorted_items[:limit]:
                fp = it.get("file_path")
                if not fp:
                    continue
                lang = it.get("iso_639_1")
                lang_label = {"zh": "中文", "cn": "中文", "en": "英文"}.get(lang or "", "无字/通用" if not lang else str(lang))
                out.append(
                    {
                        "file_path": fp,
                        "lang": lang_label,
                        "width": int(it.get("width") or 0),
                        "height": int(it.get("height") or 0),
                        "vote_average": round(float(it.get("vote_average") or 0.0), 1),
                    }
                )
            return out

        return {
            "logos": format_items(data.get("logos") or [], limit=16),
            "posters": format_items(data.get("posters") or [], limit=18),
            "backdrops": format_items(data.get("backdrops") or [], limit=16),
        }

    def cache_image(self, remote_file_path: str, size: str = "w780", category: str = "posters") -> str:
        """将 TMDB 图片下载到本地缓存目录，返回本地相对路径（如 posters/w780_xxx.jpg）。"""
        clean_remote = (remote_file_path or "").strip()
        if not clean_remote:
            return ""
        if not clean_remote.startswith("/"):
            clean_remote = "/" + clean_remote

        ext = Path(clean_remote).suffix.lower() or ".jpg"
        # SVG Logo 在 TMDB 上也支持 .png 渲染，保留原始后缀即可正常本地提供
        remote_url = f"{TMDB_IMAGE_BASE}/{size}{clean_remote}"

        if self._state:
            cached_rel = self._state.get_cached_image(remote_url)
            if cached_rel:
                abs_cached = self._cfg.image_cache_dir / cached_rel
                if abs_cached.exists() and abs_cached.stat().st_size > 0:
                    return cached_rel

        digest = hashlib.sha1(remote_url.encode("utf-8")).hexdigest()[:16]
        stem = Path(clean_remote).stem[:24]
        rel_path = f"{category}/{size}_{stem}_{digest}{ext}"
        abs_path = self._cfg.image_cache_dir / rel_path

        if abs_path.exists() and abs_path.stat().st_size > 0:
            if self._state:
                self._state.save_cached_image(remote_url, rel_path, category=category)
            return rel_path

        try:
            resp = self._http.request("GET", remote_url, timeout=20.0)
            if resp.status_code == 200 and resp.content:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_file = abs_path.with_suffix(ext + ".tmp")
                tmp_file.write_bytes(resp.content)
                tmp_file.replace(abs_path)
                if self._state:
                    self._state.save_cached_image(remote_url, rel_path, category=category)
                return rel_path
        except ExternalServiceError:
            return ""
        except OSError:
            return ""
        return ""

    @classmethod
    def _pick_best_image(
        cls,
        items: list[dict[str, Any]],
        prefer_png: bool = False,
        prefer_null_lang: bool = False,
    ) -> str:
        if not items:
            return ""
        ranked = sorted(
            items,
            key=lambda x: cls._image_sort_key(x, prefer_png=prefer_png, prefer_null_lang=prefer_null_lang),
            reverse=True,
        )
        return str(ranked[0].get("file_path") or "")

    @staticmethod
    def _image_sort_key(
        item: dict[str, Any],
        prefer_png: bool = False,
        prefer_null_lang: bool = False,
    ) -> tuple[int, int, float, int]:
        lang = (item.get("iso_639_1") or "").lower()
        if prefer_null_lang:
            lang_score = 4 if lang == "" else (3 if lang in ("zh", "cn") else (2 if lang == "en" else 1))
        else:
            if lang in ("zh", "cn"):
                lang_score = 5
            elif lang == "tw":
                lang_score = 4
            elif lang == "en":
                lang_score = 3
            elif lang == "":
                lang_score = 2
            else:
                lang_score = 1

        fp = str(item.get("file_path") or "").lower()
        ext_score = 2 if (not prefer_png or fp.endswith(".png")) else 1
        vote = float(item.get("vote_average") or 0.0)
        width = int(item.get("width") or 0)
        return (lang_score, ext_score, vote, width)
