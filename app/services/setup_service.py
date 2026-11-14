from __future__ import annotations

from typing import Any, Mapping

from app.clients.alist_client import AListClient
from app.clients.deepseek_client import DeepSeekClient
from app.clients.mdblist_client import MDBListClient
from app.clients.player_client import PlayerClient
from app.clients.tmdb_client import TMDBClient
from app.config import ConfigManager, is_placeholder_only
from app.models.state_model import LocalStateRepository

SERVICE_GUIDES: list[dict[str, Any]] = [
    {
        "id": "alist",
        "step": 1,
        "title": "AList 网盘挂载服务",
        "required": True,
        "badge": "必需",
        "purpose": "用于浏览夸克网盘、百度网盘中的电影与剧集目录，并为本地播放器生成流式直链。",
        "guide_url": "https://alist.nn.ci/zh/guide/",
        "guide_label": "AList 官方配置文档",
        "degrade_hint": "",
    },
    {
        "id": "tmdb",
        "step": 2,
        "title": "TMDB 影视资料库",
        "required": True,
        "badge": "必需",
        "purpose": "用于检索作品中英文标题、简介、演职员、分季分集信息，并下载横版背景图、竖版海报、片名 Logo 与单集剧照。",
        "guide_url": "https://www.themoviedb.org/settings/api",
        "guide_label": "前往 TMDB API 设置页获取只读访问令牌（Bearer Token）",
        "degrade_hint": "",
    },
    {
        "id": "mdblist",
        "step": 3,
        "title": "MDBList 多平台评分",
        "required": False,
        "badge": "选填 · 可跳过",
        "purpose": "用于补充获取 IMDb、烂番茄新鲜度、爆米花指数、Metacritic 与 Trakt 等多平台评分。",
        "guide_url": "https://mdblist.com/preferences/",
        "guide_label": "前往 MDBList Preferences 页面底部获取 API Key",
        "degrade_hint": "跳过后不显示 IMDb / 烂番茄等补充评分，仅显示 TMDB 官方评分；后续可随时在“设置”页补填。",
    },
    {
        "id": "deepseek",
        "step": 4,
        "title": "DeepSeek 大模型名称识别",
        "required": False,
        "badge": "选填 · 可跳过",
        "purpose": "当网盘文件名存在复杂谐音、拆字、缩写等防和谐改写且本地规则无法确定时，辅助推测原始片名并交由 TMDB 校验。",
        "guide_url": "https://platform.deepseek.com/api_keys",
        "guide_label": "前往 DeepSeek 开放平台创建 API Key",
        "degrade_hint": "跳过后自动降级为纯本地规则清洗与拼音/字形还原识别，不影响浏览、入库与播放；后续可随时在“设置”页补填。",
    },
    {
        "id": "player",
        "step": 5,
        "title": "MPC-HC 本地播放器",
        "required": False,
        "badge": "本机播放",
        "purpose": "点击首页或详情页“播放”按钮时，由后端直接拉起本机播放器加载网盘流媒体并支持断点续播。",
        "guide_url": "https://github.com/clsid2/mpc-hc/releases",
        "guide_label": "MPC-HC 官方下载页（clsid2 维护版）",
        "degrade_hint": "请确认播放器可执行文件路径存在，否则点击播放时无法拉起本地窗口。",
    },
]


class SetupService:
    """首次引导与设置中心服务：管理各外部服务连通性检测、跳过降级状态与 .env 热更新。"""

    def __init__(
        self,
        config_manager: ConfigManager,
        state_repo: LocalStateRepository,
        alist_client: AListClient,
        tmdb_client: TMDBClient,
        mdblist_client: MDBListClient,
        deepseek_client: DeepSeekClient,
        player_client: PlayerClient,
    ) -> None:
        self._cfg = config_manager
        self._state = state_repo
        self._alist = alist_client
        self._tmdb = tmdb_client
        self._mdblist = mdblist_client
        self._deepseek = deepseek_client
        self._player = player_client

    def needs_onboarding(self) -> bool:
        if not self._state.onboarding_completed:
            return True
        if not self._cfg.settings.required_ready:
            return True
        return False

    def build_config_view_model(self) -> dict[str, Any]:
        s = self._cfg.settings
        saved_statuses = self._state.get_service_statuses()
        skipped = self._state.get_skipped_services()

        status_map: dict[str, dict[str, Any]] = {}
        for item in SERVICE_GUIDES:
            sid = item["id"]
            st = saved_statuses.get(sid)
            is_configured = {
                "alist": s.alist_ready and not is_placeholder_only(s.alist_password),
                "tmdb": s.tmdb_ready,
                "mdblist": s.mdblist_ready,
                "deepseek": s.llm_ready,
                "player": s.player_ready,
            }[sid]

            if st:
                badge_state = "ok" if st.get("ok") else ("skipped" if (not item["required"] and not is_configured and skipped.get(sid)) else "error")
                badge_text = "已连接" if st.get("ok") else ("已跳过（降级运行）" if badge_state == "skipped" else "连接异常")
                msg = st.get("message") or ""
            else:
                if is_configured:
                    badge_state = "pending"
                    badge_text = "已填写（待检测）"
                    msg = "点击“检测”可立即验证连通性"
                elif not item["required"] and skipped.get(sid):
                    badge_state = "skipped"
                    badge_text = "已跳过（可随时补填）"
                    msg = item["degrade_hint"]
                else:
                    badge_state = "missing"
                    badge_text = "未配置" if item["required"] else "未配置（选填）"
                    msg = "当前尚未填入有效密钥" if sid != "player" else "尚未配置有效播放器路径"

            status_map[sid] = {
                "state": badge_state,
                "label": badge_text,
                "message": msg,
                "configured": is_configured,
                "skipped": bool(skipped.get(sid)),
            }

        degraded_notices: list[str] = []
        if not s.mdblist_ready:
            degraded_notices.append("MDBList 补充评分尚未启用（当前仅展示 TMDB 评分），可在下方随时补填 API Key 开启 IMDb 与烂番茄评分。")
        if not s.llm_ready:
            degraded_notices.append("DeepSeek 大模型尚未启用（当前仅使用本地规则与防和谐词典识别），补填有效 LLM_API_KEY 后即可自动启用 AI 辅助推断。")

        return {
            "settings": s,
            "guides": SERVICE_GUIDES,
            "statuses": status_map,
            "degraded_notices": degraded_notices,
            "onboarding_completed": self._state.onboarding_completed,
            "placeholder_flags": {
                "alist_password": is_placeholder_only(s.alist_password),
                "tmdb_token": is_placeholder_only(s.tmdb_token),
                "mdblist_apikey": is_placeholder_only(s.mdblist_apikey),
                "llm_api_key": is_placeholder_only(s.llm_api_key),
            },
        }

    def check_single_service(self, service_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        sid = (service_id or "").strip().lower()
        if sid == "alist":
            ok, msg, detail = self._alist.check_connection(
                alist_url=str(payload.get("ALIST_URL") or ""),
                username=str(payload.get("ALIST_USERNAME") or ""),
                password=str(payload.get("ALIST_PASSWORD") or ""),
            )
        elif sid == "tmdb":
            ok, msg, detail = self._tmdb.check_connection(
                token=str(payload.get("TMDB_TOKEN") or ""),
            )
        elif sid == "mdblist":
            ok, msg, detail = self._mdblist.check_connection(
                apikey=str(payload.get("MDBLIST_APIKEY") or ""),
            )
        elif sid == "deepseek":
            ok, msg, detail = self._deepseek.check_connection(
                base_url=str(payload.get("LLM_BASE_URL") or ""),
                api_key=str(payload.get("LLM_API_KEY") or ""),
                model=str(payload.get("LLM_MODEL") or ""),
                api_mode=str(payload.get("LLM_API") or ""),
            )
        elif sid == "player":
            ok, msg, detail = self._player.check_connection(
                player_path=str(payload.get("PLAYER_PATH") or ""),
            )
        else:
            return {"ok": False, "service": sid, "message": f"未知的服务类型：{sid}"}

        self._state.update_service_status(sid, ok=ok, message=msg, detail=detail)
        return {"ok": ok, "service": sid, "message": msg, "detail": detail}

    def check_all_current_services(self) -> dict[str, dict[str, Any]]:
        env_dict = self._cfg.settings.to_env_dict()
        results: dict[str, dict[str, Any]] = {}
        for guide in SERVICE_GUIDES:
            sid = guide["id"]
            results[sid] = self.check_single_service(sid, env_dict)
        return results

    def save_settings(
        self,
        form_values: Mapping[str, Any],
        *,
        skipped_services: Mapping[str, bool] | None = None,
        complete_onboarding: bool = False,
        verify_required: bool = False,
    ) -> tuple[bool, str]:
        updates: dict[str, str] = {}
        for key in (
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
        ):
            if key in form_values and form_values[key] is not None:
                updates[key] = str(form_values[key]).strip()

        new_settings = self._cfg.update_env(updates)

        if skipped_services:
            self._state.set_skipped_services(dict(skipped_services))
        else:
            # 若用户补填了 MDBList 或 DeepSeek 有效密钥，自动清除对应的“已跳过”状态
            auto_unskip: dict[str, bool] = {}
            if new_settings.mdblist_ready:
                auto_unskip["mdblist"] = False
            if new_settings.llm_ready:
                auto_unskip["deepseek"] = False
            if auto_unskip:
                self._state.set_skipped_services(auto_unskip)

        if verify_required:
            if not new_settings.alist_ready or not new_settings.tmdb_ready:
                return False, "AList 与 TMDB 为必需项，请先填写有效配置后再完成引导。"
            alist_res = self.check_single_service("alist", new_settings.to_env_dict())
            if not alist_res["ok"]:
                return False, f"AList 连接未通过：{alist_res['message']}"
            tmdb_res = self.check_single_service("tmdb", new_settings.to_env_dict())
            if not tmdb_res["ok"]:
                return False, f"TMDB 连接未通过：{tmdb_res['message']}"
            # 顺便检测选填项与播放器以刷新状态徽标
            if new_settings.mdblist_ready:
                self.check_single_service("mdblist", new_settings.to_env_dict())
            if new_settings.llm_ready:
                self.check_single_service("deepseek", new_settings.to_env_dict())
            if new_settings.player_ready:
                self.check_single_service("player", new_settings.to_env_dict())

        if complete_onboarding:
            if not new_settings.mdblist_ready:
                self._state.set_skipped_services({"mdblist": True})
            if not new_settings.llm_ready:
                self._state.set_skipped_services({"deepseek": True})
            self._state.set_onboarding_completed(True)

        return True, "配置已写入 .env 并立即生效"
