from pathlib import Path

import yaml
from flask import Blueprint, jsonify, request, send_from_directory

from src.config import load_config
from .state import db

bp = Blueprint("public", __name__)

@bp.route("/api/issue-feedback/<issue_number>")
def api_issue_feedback(issue_number):
    """Return dj_feedback + feedback_detail for all articles in an issue. Lightweight."""
    issue = db.get_issue_by_number(issue_number)
    if not issue:
        return jsonify({"error": "issue not found"}), 404
    article_ids = issue.get("article_ids", [])
    if not article_ids:
        return jsonify([])
    with db._get_conn() as conn:
        placeholders = ",".join(["?"] * len(article_ids))
        rows = conn.execute(
            f"SELECT id, dj_feedback, feedback_detail FROM articles WHERE id IN ({placeholders})",
            article_ids
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "dj_feedback": r["dj_feedback"] or "",
                "feedback_detail": r["feedback_detail"] or "",
            })
        return jsonify(result)


@bp.route("/api/articles-feedback", methods=["POST"])
def api_articles_feedback():
    """Return dj_feedback for a list of article IDs."""
    data = request.json or {}
    article_ids = data.get("ids", [])
    if not article_ids:
        return jsonify([])
    rows = db.get_articles_feedback(article_ids)
    return jsonify(rows)

@bp.route("/api/dj-feedback", methods=["POST"])
def api_dj_feedback():
    data = request.json
    try:
        detail = data.get("detail", "")
        db.set_dj_feedback(data["id"], data["feedback"], detail)
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# ============ 公开门户 ============

@bp.route("/portal")
def portal():
    return send_from_directory("templates", "portal.html")

@bp.route("/api/c-tier-count")
def api_c_tier_count():
    """返回窗口内C档计数"""
    config = load_config()
    window_days = config.get("throttle", {}).get("c_tier_window_days", 3)
    articles = db.get_c_tier_in_window(window_days=window_days, limit=500)
    return jsonify({"count": len(articles), "window_days": window_days})

@bp.route("/api/public/articles")
def api_public_articles():
    """返回已审核文章，供公开门户使用"""
    limit = request.args.get("limit", 100, type=int)
    category = request.args.get("category", None)
    with db._get_conn() as conn:
        if category:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE status IN ('candidate','approved') AND category=?
                   ORDER BY crawled_at DESC, score DESC LIMIT ?""",
                (category, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE status IN ('candidate','approved')
                   ORDER BY crawled_at DESC, score DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        return jsonify([db._row_to_dict(r) for r in rows])

@bp.route("/api/public/sources")
def api_public_sources():
    """返回信源网站列表"""
    sites_path = Path(__file__).resolve().parent.parent / "config" / "sites.yaml"
    with open(sites_path, encoding="utf-8") as f:
        sites = yaml.safe_load(f)
    return jsonify(sites.get("sites", []))
