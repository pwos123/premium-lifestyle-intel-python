#!/usr/bin/env python3
"""
高品质图文推荐系统 — Web 应用
python app.py 启动后访问 http://0.0.0.0:8080
"""

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask

from web.auth import bp as auth_bp, add_cache_headers, require_login
from web.serving import bp as serving_bp
from web.articles import bp as articles_bp
from web.issues import bp as issues_bp
from web.maintenance import bp as maintenance_bp
from web.public import bp as public_bp
from web.state import CONFIG, DB_PATH, IMAGE_DIR, OUTPUT_DIR, db, logger


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me-for-public-deploy")

    app.before_request(require_login)
    app.after_request(add_cache_headers)

    for bp in (auth_bp, serving_bp, articles_bp, issues_bp, maintenance_bp, public_bp):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    print("=" * 50)
    print("  高品质图文推荐系统")
    print("  访问: http://0.0.0.0:8080")
    print("=" * 50)

    # 后台启动调度器（定时抓取 + 图片清理）
    from src.scheduler import start_scheduler
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True, name="scheduler")
    scheduler_thread.start()
    print("⏰ 调度器已启动（后台线程）")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
