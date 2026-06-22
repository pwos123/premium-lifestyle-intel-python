from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from src.ai_analyzer import AIAnalyzer
from src.category_classifier import STANDARD_CATEGORIES
from src.config import load_config, load_model_configs
from services.article_light_analysis import rerun_article_summary, translate_article_content
from services.image_selection import select_h5_visible_images
from .state import CONFIG, db, logger

bp = Blueprint("articles", __name__)

@bp.route("/api/archive-stats")
def api_archive_stats():
    exclude_sunk = request.args.get("exclude_sunk", "1") == "1"
    return jsonify(db.get_archive_reason_stats(exclude_sunk=exclude_sunk))

@bp.route("/api/stats")
def api_stats():
    stats = db.get_stats()
    stats["category_counts"] = db.get_category_counts()
    return jsonify(stats)

@bp.route("/api/articles")
def api_articles():
    limit = request.args.get("limit", 500, type=int)
    status = request.args.get("status", None)
    archive_type = request.args.get("archive_type", None)
    include_archived = request.args.get("include_archived", "0") == "1"

    if status:
        with db._get_conn() as conn:
            if status == "candidate":
                rows = conn.execute(
                    """SELECT * FROM articles
                       WHERE status IN ('candidate','approved')
                         AND COALESCE(evergreen,0)=0
                       ORDER BY score DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return jsonify([db._row_to_dict(r) for r in rows])
            if status == "in_flow":
                # 流转中: pending (非 rejected 非 published 非 in_issue)
                rows = conn.execute(
                    """SELECT * FROM articles
                       WHERE status IN ('pending','candidate','approved')
                       ORDER BY score DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return jsonify([db._row_to_dict(r) for r in rows])
            if status == "all":
                # 全部入库: 根据 archive_type 筛选
                if archive_type == "sunk":
                    return jsonify(db.get_sunk_articles(limit=limit))
                if archive_type == "archived":
                    rows = conn.execute(
                        "SELECT * FROM articles WHERE status='rejected' ORDER BY archive_reason_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    return jsonify([db._row_to_dict(r) for r in rows])
                # Default (no archive_type): 返回全量(含 rejected/sunk)
                rows = conn.execute(
                    """SELECT * FROM articles
                       ORDER BY score DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return jsonify([db._row_to_dict(r) for r in rows])
            if status == 'pending':
                # C档待筛选: 只返回窗口内的 C 档
                throttle_cfg = load_config().get("throttle", {})
                c_window = throttle_cfg.get("c_tier_window_days", 3)
                rows = conn.execute(
                    """SELECT * FROM articles WHERE status='pending'
                       AND (gate2_tier != 'C' OR gate2_checked_at IS NULL
                            OR date(gate2_checked_at) >= date('now', ?))
                       ORDER BY score DESC LIMIT ?""",
                    (f'-{c_window} days', limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM articles WHERE status=? ORDER BY score DESC LIMIT ?", (status, limit)).fetchall()
            return jsonify([db._row_to_dict(r) for r in rows])

    with db._get_conn() as conn:
        if not include_archived:
            rows = conn.execute("SELECT * FROM articles WHERE status NOT IN ('rejected','sunk') ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM articles ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
        return jsonify([db._row_to_dict(r) for r in rows])

@bp.route("/api/articles/<int:article_id>")
def api_article(article_id):
    a = db.get_article(article_id)
    if a:
        return jsonify(a)
    return jsonify({"error": "not found"}), 404

@bp.route("/api/articles/<int:article_id>/visible-images")
def api_article_visible_images(article_id):
    a = db.get_article(article_id)
    if not a:
        return jsonify({"error": "not found"}), 404
    return jsonify(select_h5_visible_images(a.get("images", []), max_gallery=4))


@bp.route("/api/articles/<int:article_id>/category", methods=["POST"])
def api_update_article_category(article_id):
    data = request.json or {}
    category = (data.get("category") or "").strip()
    if category not in STANDARD_CATEGORIES:
        return jsonify({"ok": False, "error": "频道无效"})
    a = db.get_article(article_id)
    if not a:
        return jsonify({"ok": False, "error": "文章不存在"})
    db.update_article(article_id, {"category": category})
    return jsonify({"ok": True, "category": category})

@bp.route("/api/promote-sunk", methods=["POST"])
def api_promote_sunk():
    """将沉库文章提升回候选池"""
    data = request.json
    aid = data["id"]
    db.update_article(aid, {
        "status": "candidate",
        "reviewed_at": datetime.now().isoformat(),
        "archive_reason": None,
        "archive_type": None,
    })
    return jsonify({"ok": True})

@bp.route("/api/review", methods=["POST"])
def api_review():
    data = request.json
    db.review_article(data["id"], data["status"], data.get("archive_reason"))
    return jsonify({"ok": True})

@bp.route("/api/batch-review", methods=["POST"])
def api_batch_review():
    data = request.json
    ids = data.get("ids") or []
    count = db.batch_review(ids, data["status"], data.get("archive_reason"))
    return jsonify({"ok": True, "count": count})

@bp.route("/api/batch-move-pending", methods=["POST"])
def api_batch_move_pending():
    data = request.json or {}
    ids = data.get("ids") or []
    count = db.batch_move_to_pending(ids)
    return jsonify({"ok": True, "count": count})

@bp.route("/api/clear-pending", methods=["POST"])
def api_clear_pending():
    """清除 pending_human 标记"""
    data = request.json
    ids = data.get("ids", [data.get("id")] if data.get("id") else [])
    for aid in ids:
        db.update_article(aid, {"pending_human": 0, "summary_flagged": 0, "gate3_status": None, "fit_keywords_hit": None})
    return jsonify({"ok": True, "count": len(ids)})

@bp.route("/api/deep-analyze", methods=["POST"])
def api_deep_analyze():
    data = request.json
    article = db.get_article(data["id"])
    if not article:
        return jsonify({"ok": False, "error": "文章不存在"})

    try:
        analyzer = AIAnalyzer(load_model_configs(CONFIG))
        if not analyzer.llm.available_models:
            return jsonify({"ok": False, "error": "未配置模型 API Key，请先设置环境变量"})
        result = analyzer.analyze_article(
            title=article["title"],
            content=article.get("content", ""),
            source=article.get("source", ""),
            category_hint=article.get("category", ""),
        )
        db.update_article(data["id"], {
            "summary": result.get("summary", ""),
            "translated_title": result.get("translated_title", ""),
            "translated_content": result.get("translated_content", ""),
            "category": result.get("category", ""),
            "score": result.get("score", 0),
            "tags": result.get("tags", []),
            "recommend_reason": result.get("recommend_reason", ""),
            "scenario": result.get("scenario", ""),
            "pros": result.get("pros", []),
            "cons": result.get("cons", []),
            "recommend_level": result.get("recommend_level", "了解"),
            "is_relevant": 1 if result.get("is_relevant", True) else 0,
            "model_votes": result.get("model_votes", {}),
        })
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"深度分析失败: {e}")
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/api/articles/<int:article_id>/rerun-summary", methods=["POST"])
def api_rerun_article_summary(article_id):
    try:
        return jsonify(rerun_article_summary(article_id))
    except Exception as e:
        logger.error(f"重跑摘要失败: {e}")
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/api/articles/<int:article_id>/translate-content", methods=["POST"])
def api_translate_article_content(article_id):
    try:
        return jsonify(translate_article_content(article_id))
    except Exception as e:
        logger.error(f"补全文翻译失败: {e}")
        return jsonify({"ok": False, "error": str(e)})

@bp.route("/api/generate-report", methods=["POST"])
def api_generate_report():
    data = request.get_json(silent=True) or {}
    report_limit = data.get("limit", 50)
    report_type = data.get("report_type", "daily")
    # 精选池直接使用 A/B 档待筛选文章; Gate3 已停用
    articles = db.get_gate3_selected(limit=report_limit)
    if not articles:
        articles = db.get_approved_articles(limit=report_limit)
    if not articles:
        return jsonify({"ok": False, "error": "没有候选文章"})

    from run_generate_cards import run_card_generation
    from src.report_generator import generate_report

    # Run card generation first
    result = run_card_generation(limit=report_limit, dry_run=False, force=False)
    editor_note = ""
    if result:
        _, editor_note, _ = result

    # Re-fetch articles (now with updated card_json)
    articles = db.get_gate3_selected(limit=report_limit)
    if not articles:
        articles = db.get_approved_articles(limit=report_limit)

    report_date = data.get("report_date", "")
    output_path = generate_report(articles, CONFIG, editor_note=editor_note, report_type=report_type, report_date=report_date)
    filename = Path(output_path).name if output_path else ""
    return jsonify({"ok": True, "path": output_path, "filename": filename, "report_type": report_type})
