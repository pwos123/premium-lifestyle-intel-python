from datetime import datetime

from flask import Blueprint, jsonify, request

from src.config import load_config
from services.article_lifecycle import recompute_gate2_tier
from services.maintenance import (
    get_status,
    preview_clear_feedback,
    preview_reeval,
    preview_reveto,
    preview_resummarize,
    start_clear_feedback,
    start_reeval,
    start_resummarize,
    start_reveto,
)
from .state import db

bp = Blueprint("maintenance", __name__)

@bp.route("/api/sunk-stats")
def api_sunk_stats():
    """沉库规模指标"""
    with db._get_conn() as conn:
        sunk_total = conn.execute("SELECT COUNT(*) FROM articles WHERE status='sunk'").fetchone()[0]
        sunk_7d = conn.execute("SELECT COUNT(*) FROM articles WHERE status='sunk' AND archive_reason_at >= datetime('now', '-7 days')").fetchone()[0]
        return jsonify({"sunk_total": sunk_total, "sunk_7d": sunk_7d})

@bp.route("/api/run-expiry-check", methods=["POST"])
def api_run_expiry_check():
    config = load_config()
    throttle_cfg = config.get("throttle", {})
    sink_c_tier = request.args.get("sink_c_tier", "0") == "1"
    c_tier_window = throttle_cfg.get("c_tier_window_days", 3)
    stats = db.run_expiry_check(sink_c_tier=sink_c_tier, c_tier_window_days=c_tier_window)
    parts = [f"归档 {stats['archived']} 篇过期", f"{stats['nearing']} 篇即将过期"]
    if stats.get('c_sunk', 0) > 0:
        parts.append(f"C档沉底 {stats['c_sunk']} 篇")
    summary = ", ".join(parts)
    db.log_task_run("expiry_check", stats, summary)
    return jsonify({"ok": True, "stats": stats, "summary": summary})

@bp.route("/api/expiry-stats")
def api_expiry_stats():
    log = db.get_latest_task_log("expiry_check")
    return jsonify(log or {"stats": {}, "summary": "未运行过"})

# ============ 待人工操作 ============

@bp.route("/api/release-pending", methods=["POST"])
def api_release_pending():
    """放行待人工文章：清除 pending_human + summary_flagged 标记，恢复原档位正常流转"""
    data = request.json
    aid = data["id"]
    a = db.get_article(aid)
    updates = {
        "pending_human": 0,
        "summary_flagged": 0,
        "gate3_status": None,
        "fit_keywords_hit": None,
    }
    # If tier is D but dimensions suggest higher, recompute
    if a and a.get("gate2_tier") == "D" and not a.get("veto_hit"):
        updates["gate2_tier"] = recompute_gate2_tier(
            a.get("gate2_dim_excitement"),
            a.get("gate2_dim_feasibility"),
            a.get("gate2_dim_density"),
        )
    db.update_article(aid, updates)
    return jsonify({"ok": True})

@bp.route("/api/violate-pending", methods=["POST"])
def api_violate_pending():
    """确认违规：归档文章，原因=画像冲突 → 终点站"""
    data = request.json
    aid = data["id"]
    db.auto_archive(aid, "画像冲突", archive_type="archived")
    # Also clear pending flags
    db.update_article(aid, {
        "pending_human": 0,
        "gate3_status": None,
    })
    return jsonify({"ok": True})


# ============ 数据维护 API（异步后台执行）============

@bp.route("/api/maint/resummarize", methods=["POST"])
def api_maint_resummarize():
    start_resummarize(request.json or {})
    return jsonify({"ok": True, "msg": "started"})

@bp.route("/api/maint/resummarize/preview", methods=["POST"])
def api_maint_resummarize_preview():
    return jsonify({"ok": True, **preview_resummarize(request.json or {})})

@bp.route("/api/maint/reeval", methods=["POST"])
def api_maint_reeval():
    start_reeval(request.json or {})
    return jsonify({"ok": True, "msg": "started"})

@bp.route("/api/maint/reeval/preview", methods=["POST"])
def api_maint_reeval_preview():
    return jsonify({"ok": True, **preview_reeval(request.json or {})})

@bp.route("/api/maint/reveto", methods=["POST"])
def api_maint_reveto():
    start_reveto(request.json or {})
    return jsonify({"ok": True, "msg": "started"})

@bp.route("/api/maint/reveto/preview", methods=["POST"])
def api_maint_reveto_preview():
    return jsonify({"ok": True, **preview_reveto(request.json or {})})


@bp.route("/api/maint/clear-feedback", methods=["POST"])
def api_maint_clear_feedback():
    start_clear_feedback(request.json or {})
    return jsonify({"ok": True, "msg": "started"})

@bp.route("/api/maint/clear-feedback/preview", methods=["POST"])
def api_maint_clear_feedback_preview():
    return jsonify({"ok": True, **preview_clear_feedback(request.json or {})})

@bp.route("/api/maint/status/<op>")
def api_maint_status(op):
    return jsonify(get_status(op))
