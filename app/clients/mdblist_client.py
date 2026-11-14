from __future__ import annotations

from typing import Any

from app.clients.http_client import ExternalServiceError, RateLimitedHttpClient
from app.config import ConfigManager, is_effective_value, is_placeholder_only

MDBLIST_V2_BASE = "https://api.mdblist.com"

SOURCE_DISPLAY_MAP = {
    "imdb": ("IMDb", "/10"),
    "tomatoes": ("烂番茄", "%"),
    "tomatoesaudience": ("爆米花", "%"),
    "popcorn": ("爆米花", "%"),
    "metacritic": ("Metacritic", ""),
    "trakt": ("Trakt", "%"),
    "letterboxd": ("Letterboxd", "/5"),
}


class MDBListClient:
    """MDBList 多平台评分聚合客户端封装（选填服务，未配置时自动降级）。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        http_client: RateLimitedHttpClient | None = None,
    ) -> None:
        self._cfg = config_manager
        self._http = http_client or RateLimitedHttpClient("MDBList", min_interval=0.25, max_retries=2, timeout=15.0)

    def check_connection(self, apikey: str | None = None) -> tuple[bool, str, dict[str, Any]]:
        key = (apikey if apikey is not None else self._cfg.settings.mdblist_apikey).strip()
        if not is_effective_value(key):
            if is_placeholder_only(key):
                return False, f"MDBLIST_APIKEY 当前为占位值（{key}），请填写真实密钥或跳过此步", {}
            return False, "未填写 MDBList API Key（此项可跳过，跳过后仅显示 TMDB 评分）", {}

        try:
            resp = self._http.request(
                "GET",
                f"{MDBLIST_V2_BASE}/tmdb/movie/550",
                params={"apikey": key},
            )
            if resp.status_code in (401, 403):
                return False, f"MDBList API Key 无效或被拒绝访问 (HTTP {resp.status_code})", {}
            if resp.status_code >= 400:
                return False, f"MDBList 返回异常状态码 (HTTP {resp.status_code})", {}

            data = resp.json()
            if data.get("response") is False or data.get("error"):
                return False, f"MDBList 验证失败：{data.get('error') or '无效密钥'}", {}

            ratings = self.parse_ratings_payload(data)
            return True, f"MDBList 验证通过（成功解析 {len(ratings)} 项平台评分）", {"sample_count": len(ratings)}
        except ExternalServiceError as exc:
            return False, exc.message, {}
        except Exception as exc:
            return False, f"MDBList 检测异常：{exc}", {}

    def fetch_ratings(self, media_type: str, tmdb_id: int) -> list[dict[str, Any]]:
        key = self._cfg.settings.mdblist_apikey.strip()
        if not is_effective_value(key):
            return []

        mdb_type = "show" if media_type == "tv" else "movie"
        try:
            resp = self._http.request(
                "GET",
                f"{MDBLIST_V2_BASE}/tmdb/{mdb_type}/{int(tmdb_id)}",
                params={"apikey": key},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if data.get("response") is False or data.get("error"):
                return []
            return self.parse_ratings_payload(data)
        except Exception:
            # 补充评分获取失败时静默降级，不中断作品入库
            return []

    @staticmethod
    def parse_ratings_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_ratings = payload.get("ratings") or []
        parsed: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        for item in raw_ratings:
            source = str(item.get("source") or "").lower().strip()
            if source not in SOURCE_DISPLAY_MAP:
                continue
            val = item.get("value")
            score = item.get("score")
            votes = int(item.get("votes") or 0)
            if val in (None, 0, 0.0, "0", "") and score in (None, 0, 0.0):
                continue

            label, suffix = SOURCE_DISPLAY_MAP[source]
            if label in seen_labels:
                continue
            seen_labels.add(label)

            chosen = val if val not in (None, "") else score
            if suffix == "%":
                display_val = f"{int(round(float(chosen)))}%"
            elif suffix == "/10":
                display_val = f"{float(chosen):.1f}"
            elif suffix == "/5":
                display_val = f"{float(chosen):.1f} / 5"
            else:
                display_val = f"{int(round(float(chosen)))}"

            parsed.append(
                {
                    "source": source,
                    "label": label,
                    "value": chosen,
                    "display": display_val,
                    "votes": votes,
                }
            )
        return parsed
