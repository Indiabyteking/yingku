from __future__ import annotations

import argparse

from app import create_app
from app.config import ConfigManager


def main() -> None:
    parser = argparse.ArgumentParser(description="启动影库（YingKu）本机影视资源管理网站")
    parser.add_argument("--host", default=None, help="监听地址（默认读取 .env 或 127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认读取 .env 或 5000）")
    parser.add_argument("--debug", action="store_true", help="开启调试模式")
    args = parser.parse_args()

    cfg = ConfigManager()
    app = create_app(config_manager=cfg)
    host = args.host or cfg.settings.app_host
    port = args.port or cfg.settings.app_port

    print(f"影库服务已启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
