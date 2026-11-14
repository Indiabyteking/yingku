from __future__ import annotations

from pathlib import Path
from typing import Any
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from app.clients import (
    AListClient,
    DeepSeekClient,
    MDBListClient,
    PlayerClient,
    TMDBClient,
)
from app.config import ConfigManager
from app.controllers import ServiceContainer
from app.controllers.admin_controller import admin_bp
from app.controllers.home_controller import home_bp
from app.controllers.import_controller import import_bp
from app.controllers.media_controller import media_bp
from app.controllers.setup_controller import setup_bp
from app.models import LocalStateRepository, MediaRepository
from app.services import LibraryService, PlaybackService, RecognitionService, SetupService


def create_app(
    config_manager: ConfigManager | None = None,
    env_path: Path | None = None,
    data_dir: Path | None = None,
    *,
    alist_client: AListClient | None = None,
    tmdb_client: TMDBClient | None = None,
    mdblist_client: MDBListClient | None = None,
    deepseek_client: DeepSeekClient | None = None,
    player_client: PlayerClient | None = None,
) -> Flask:
    """应用工厂，组装 MVC 各层依赖（Model / Service / Client / Controller / View）。"""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    cfg = config_manager or ConfigManager(env_path=env_path, data_dir=data_dir)
    cfg.ensure_dirs()
    app.config["SECRET_KEY"] = cfg.settings.secret_key

    # 1. Model 层：双 SQLite 物理隔离（媒体资料库 media.db + 本机凭据/识别/图片缓存库 local_state.db）
    media_repo = MediaRepository(cfg.media_db_path)
    state_repo = LocalStateRepository(cfg.local_db_path)

    # 2. 外部服务封装层
    alist = alist_client or AListClient(cfg)
    tmdb = tmdb_client or TMDBClient(cfg, state_repo=state_repo)
    mdblist = mdblist_client or MDBListClient(cfg)
    deepseek = deepseek_client or DeepSeekClient(cfg)
    player = player_client or PlayerClient(cfg)

    # 3. 业务服务编排层
    recognition_svc = RecognitionService(cfg, state_repo, tmdb, deepseek)
    library_svc = LibraryService(cfg, media_repo, state_repo, alist, tmdb, mdblist, recognition_svc)
    playback_svc = PlaybackService(media_repo, alist, player)
    setup_svc = SetupService(cfg, state_repo, alist, tmdb, mdblist, deepseek, player)

    container = ServiceContainer(
        config=cfg,
        setup_service=setup_svc,
        recognition_service=recognition_svc,
        library_service=library_svc,
        playback_service=playback_svc,
    )
    app.extensions["config_manager"] = cfg
    app.extensions["media_repo"] = media_repo
    app.extensions["state_repo"] = state_repo
    app.extensions["services"] = container

    # 4. 挂载路由控制器（Controller 层）
    app.register_blueprint(setup_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(admin_bp)

    # 5. 首次使用引导拦截守卫
    exempt_prefixes = ("/setup", "/api/setup/", "/static/", "/media-cache/", "/favicon.ico")

    @app.before_request
    def _enforce_onboarding():
        req_path = request.path
        if any(req_path == p or req_path.startswith(p) for p in exempt_prefixes):
            return None
        if setup_svc.needs_onboarding():
            if req_path.startswith("/api/"):
                return jsonify({"ok": False, "message": "请先完成首次使用引导配置", "redirect": "/setup"}), 403
            return redirect(url_for("setup.onboarding_page"))
        return None

    # 6. 模板只读显示辅助上下文（不做业务计算）
    @app.context_processor
    def _inject_view_helpers() -> dict[str, Any]:
        s = cfg.settings

        def media_img_url(rel_path: str | None) -> str:
            clean = (rel_path or "").strip().lstrip("/")
            return f"/media-cache/{clean}" if clean else ""

        return {
            "media_img_url": media_img_url,
            "site_name": "影库",
            "has_degraded_optional": (not s.mdblist_ready) or (not s.llm_ready),
        }

    # 7. 全局中文错误展示
    @app.errorhandler(404)
    def _handle_not_found(err: HTTPException):
        msg = err.description if (err and err.description and err.description != type(err).description) else "请求的页面或影视条目不存在"
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": msg}), 404
        return render_template("error.html", code=404, title="未找到内容", message=msg, page_title="未找到页面"), 404

    @app.errorhandler(500)
    def _handle_server_error(err: Exception):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "服务器内部处理异常，请稍后重试"}), 500
        return (
            render_template(
                "error.html",
                code=500,
                title="服务暂时出现异常",
                message="处理请求时遇到了意外问题，请检查本机服务配置或稍后重试。",
                page_title="服务异常",
            ),
            500,
        )

    return app
