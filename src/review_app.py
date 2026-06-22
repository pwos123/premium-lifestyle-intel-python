"""
Flask 审核页面 — 本地 Web UI 用于人工筛选 Top 30 文章
"""

import json
import logging
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database

logger = logging.getLogger(__name__)

# 审核页面 HTML 模板
REVIEW_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>文章审核 — 高品质图文推荐</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 24px 32px;
            border-bottom: 1px solid #c9a96e33;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header h1 {
            font-size: 20px;
            color: #c9a96e;
            font-weight: 600;
        }
        .header .stats {
            font-size: 13px;
            color: #888;
            margin-top: 6px;
        }
        .toolbar {
            display: flex;
            gap: 10px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        .toolbar button {
            padding: 6px 16px;
            border: 1px solid #c9a96e55;
            background: transparent;
            color: #c9a96e;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .toolbar button:hover { background: #c9a96e22; }
        .toolbar button.active {
            background: #c9a96e;
            color: #1a1a2e;
        }
        .toolbar button.approve-all {
            background: #2d7a3a;
            border-color: #2d7a3a;
            color: white;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }
        .card {
            background: #1a1a2e;
            border: 1px solid #ffffff10;
            border-radius: 12px;
            margin-bottom: 16px;
            overflow: hidden;
            transition: border-color 0.2s;
        }
        .card:hover { border-color: #c9a96e44; }
        .card.approved { border-left: 3px solid #4caf50; }
        .card.rejected { border-left: 3px solid #f44336; opacity: 0.6; }
        .card-img {
            width: 100%;
            height: 200px;
            object-fit: cover;
            display: block;
        }
        .card-body { padding: 16px 20px; }
        .card-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
            flex-wrap: wrap;
        }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-must { background: #c9a96e; color: #1a1a2e; }
        .badge-rec { background: #4a90d9; color: white; }
        .badge-know { background: #555; color: #ccc; }
        .badge-cat { background: #ffffff15; color: #aaa; }
        .score-badge {
            font-size: 14px;
            font-weight: 700;
            color: #c9a96e;
        }
        .card-title {
            font-size: 17px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 8px;
            line-height: 1.4;
        }
        .card-source {
            font-size: 12px;
            color: #888;
            margin-bottom: 10px;
        }
        .card-summary {
            font-size: 14px;
            color: #bbb;
            line-height: 1.6;
            margin-bottom: 10px;
        }
        .card-scenario {
            font-size: 13px;
            color: #a0c4ff;
            margin-bottom: 8px;
            padding: 6px 10px;
            background: #a0c4ff10;
            border-radius: 4px;
        }
        .card-pros-cons {
            display: flex;
            gap: 16px;
            margin-bottom: 10px;
            font-size: 13px;
        }
        .pros { color: #81c784; }
        .cons { color: #ffb74d; }
        .card-tags {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 12px;
        }
        .tag {
            padding: 2px 8px;
            background: #ffffff10;
            border-radius: 3px;
            font-size: 11px;
            color: #aaa;
        }
        .card-actions {
            display: flex;
            gap: 10px;
            padding-top: 12px;
            border-top: 1px solid #ffffff10;
        }
        .card-actions button {
            flex: 1;
            padding: 8px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
        }
        .btn-approve { background: #2d7a3a; color: white; }
        .btn-approve:hover { background: #388e3c; }
        .btn-reject { background: #c62828; color: white; }
        .btn-reject:hover { background: #e53935; }
        .btn-approve.selected { box-shadow: 0 0 0 2px #4caf50; }
        .btn-reject.selected { box-shadow: 0 0 0 2px #f44336; }
        .card-url {
            font-size: 12px;
            color: #666;
            word-break: break-all;
            margin-top: 8px;
        }
        .card-url a { color: #6a9fd8; text-decoration: none; }
        .card-url a:hover { text-decoration: underline; }
        .model-votes {
            font-size: 11px;
            color: #666;
            margin-top: 6px;
        }
        .empty-msg {
            text-align: center;
            color: #666;
            padding: 60px 20px;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📋 文章审核 — 高品质图文推荐</h1>
        <div class="stats" id="stats">
            待审核: {{ pending_count }} | 已通过: {{ approved_count }} | 已拒绝: {{ rejected_count }}
        </div>
        <div class="toolbar">
            <button onclick="filterAll()" class="active" id="btn-all">全部 ({{ articles|length }})</button>
            <button onclick="filterCategory('')" id="btn-pending">待审核 ({{ pending_count }})</button>
            {% for cat in categories %}
            <button onclick="filterCategory('{{ cat }}')" id="btn-{{ loop.index }}">{{ cat }} ({{ cat_counts.get(cat, 0) }})</button>
            {% endfor %}
            <button onclick="batchApprove()" class="approve-all">✅ 全部通过</button>
        </div>
    </div>
    <div class="container" id="articles-container">
        {% for article in articles %}
        <div class="card" id="card-{{ article.id }}" data-id="{{ article.id }}" data-category="{{ article.category }}">
            {% if article.images and article.images[0] %}
            <img class="card-img" src="{{ article.images[0] }}" alt="" loading="lazy"
                 onerror="this.style.display='none'">
            {% endif %}
            <div class="card-body">
                <div class="card-meta">
                    <span class="score-badge">{{ article.score }}分</span>
                    {% if article.recommend_level == '必看' %}
                    <span class="badge badge-must">必看</span>
                    {% elif article.recommend_level == '推荐' %}
                    <span class="badge badge-rec">推荐</span>
                    {% else %}
                    <span class="badge badge-know">了解</span>
                    {% endif %}
                    <span class="badge badge-cat">{{ article.category }}</span>
                    <span class="card-source">{{ article.source }}</span>
                </div>
                <div class="card-title">{{ article.title }}</div>
                <div class="card-summary">{{ article.summary }}</div>
                {% if article.scenario %}
                <div class="card-scenario">🎯 {{ article.scenario }}</div>
                {% endif %}
                <div class="card-pros-cons">
                    {% if article.pros %}
                    <div class="pros">
                        ✅ {{ article.pros | join(' / ') if article.pros is string else article.pros | join(' / ') }}
                    </div>
                    {% endif %}
                    {% if article.cons %}
                    <div class="cons">
                        ⚠️ {{ article.cons | join(' / ') if article.cons is string else article.cons | join(' / ') }}
                    </div>
                    {% endif %}
                </div>
                <div class="card-tags">
                    {% for tag in article.tags %}
                    <span class="tag">{{ tag }}</span>
                    {% endfor %}
                </div>
                <div class="card-actions">
                    <button class="btn-approve" onclick="review({{ article.id }}, 'approved', this)">✅ 采纳</button>
                    <button class="btn-reject" onclick="review({{ article.id }}, 'rejected', this)">❌ 拒绝</button>
                </div>
                <div class="card-url"><a href="{{ article.url }}" target="_blank">{{ article.url[:80] }}</a></div>
                {% if article.model_votes %}
                <div class="model-votes">
                    {% for model, vote in article.model_votes.items() %}
                    {{ model }}: {{ vote.score }}分{% if not loop.last %} | {% endif %}
                    {% endfor %}
                </div>
                {% endif %}
            </div>
        </div>
        {% endfor %}
        {% if not articles %}
        <div class="empty-msg">暂无待审核文章，请先运行抓取任务</div>
        {% endif %}
    </div>

    <script>
        function review(id, status, btn) {
            fetch('/api/review', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id, status: status})
            })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    const card = document.getElementById('card-' + id);
                    card.classList.add(status);
                    btn.classList.add('selected');
                    setTimeout(() => card.style.display = 'none', 500);
                }
            });
        }

        function batchApprove() {
            if (!confirm('确认通过所有待审核文章？')) return;
            fetch('/api/batch-approve', {method: 'POST'})
            .then(r => r.json())
            .then(data => {
                if (data.ok) location.reload();
            });
        }

        function filterCategory(cat) {
            document.querySelectorAll('.card').forEach(card => {
                if (!cat) {
                    card.style.display = card.classList.contains('approved') || card.classList.contains('rejected') ? 'none' : '';
                } else {
                    card.style.display = card.dataset.category === cat ? '' : 'none';
                }
            });
        }

        function filterAll() {
            document.querySelectorAll('.card').forEach(card => {
                card.style.display = '';
            });
        }
    </script>
</body>
</html>
"""


def create_app(db_path: str = "data/content.db") -> Flask:
    """创建 Flask 审核应用"""
    app = Flask(__name__)
    db = Database(db_path)

    @app.route("/")
    def index():
        articles = db.get_articles_for_review(limit=50)
        stats = db.get_stats()
        cat_counts = db.get_category_counts()
        categories = [
            "精品酒店与度假", "旅行与探索", "美食与美酒", "艺术与文化",
            "建筑与空间", "产品与设计", "时尚与风格", "珠宝与腕表", "汽车与出行",
            "科技与生活", "健康与养生",
        ]
        return render_template_string(
            REVIEW_TEMPLATE,
            articles=articles,
            pending_count=stats["pending"],
            approved_count=stats["approved"],
            rejected_count=stats["rejected"],
            categories=categories,
            cat_counts=cat_counts,
        )

    @app.route("/api/review", methods=["POST"])
    def api_review():
        data = request.json
        article_id = data.get("id")
        status = data.get("status")
        if article_id and status in ("approved", "rejected"):
            db.review_article(article_id, status)
            return jsonify({"ok": True})
        return jsonify({"ok": False}), 400

    @app.route("/api/batch-approve", methods=["POST"])
    def api_batch_approve():
        articles = db.get_articles_for_review(limit=50)
        ids = [a["id"] for a in articles]
        if ids:
            db.batch_review(ids, "approved")
        return jsonify({"ok": True, "count": len(ids)})

    @app.route("/api/stats")
    def api_stats():
        return jsonify(db.get_stats())

    return app


def run_review(db_path: str = "data/content.db", port: int = 5000):
    """启动审核服务器"""
    app = create_app(db_path)
    logger.info(f"审核页面启动: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
