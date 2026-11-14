from __future__ import annotations

from pathlib import Path
from flask import Flask

from app.config import ConfigManager


def create_app(
    config_manager: ConfigManager | None = None,
    env_path: Path | None = None,
    data_dir: Path | None = None,
) -> Flask:
    """应用工厂，组装 MVC 各层依赖。"""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    cfg = config_manager or ConfigManager(env_path=env_path, data_dir=data_dir)
    cfg.ensure_dirs()
    app.config["SECRET_KEY"] = cfg.settings.secret_key
    app.extensions["config_manager"] = cfg

    # 后续提交中挂载数据库模型、外部服务封装与 Blueprint 路由
    return app
