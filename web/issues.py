import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from services.issue_builder import (
    create_issue_shell,
    get_card_readiness,
    has_complete_card,
    run_card_prepare_task,
    run_issue_publish_task,
    summarize_card_readiness,
    validate_issue_article_ids,
    validate_issue_ready_for_h5,
)
from services.tasks import _card_gen_lock, _start_bg_task, _task_lock, _task_store
from .state import CONFIG, IMAGE_DIR, db, logger

bp = Blueprint("issues", __name__)

# ============ 组刊工作台 API ============

@bp.route("/api/candidate-pool")
def api_candidate_pool():
    """返回候选池文章列表（按频道分组、顺延置顶、档位排序）"""
    articles = db.get_candidate_pool()
    return jsonify(articles)

@bp.route("/api/evergreen-pool")
def api_evergreen_pool():
    articles = db.get_evergreen_pool()
    return jsonify(articles)

@bp.route("/api/mark-evergreen", methods=["POST"])
def api_mark_evergreen():
    data = request.json or {}
    article_id = int(data["id"])
    value = bool(data.get("evergreen", True))
    article = db.get_article(article_id)
    if not article:
        return jsonify({"ok": False, "error": "文章不存在"}), 404
    if value and article.get("status") in ("rejected", "sunk", "in_issue", "published"):
        return jsonify({
            "ok": False,
            "error": f"这篇文章当前是{article.get('status')}状态，不能直接放入常青库；请先恢复到候选/待筛选。"
        }), 400
    db.mark_evergreen(article_id, value)
    return jsonify({"ok": True, "evergreen": value})

@bp.route("/api/generate-issue", methods=["POST"])
def api_generate_issue():
    """基于选中的文章生成期刊。自动处理顺延和落选分流。"""
    data = request.json
    article_ids, selected_articles, error = validate_issue_article_ids(db, data.get("article_ids", []))
    if error:
        return jsonify({"ok": False, "error": error})

    integrity_errors = validate_issue_ready_for_h5(
        {"article_ids": article_ids},
        selected_articles,
    )
    if integrity_errors:
        return jsonify({
            "ok": False,
            "error": "同步生成已阻止，请改用后台生成或先修复文章: " + "；".join(integrity_errors),
        }), 400

    issue_shell = create_issue_shell(db, article_ids, data)
    issue_id = issue_shell["issue_id"]
    issue_number = issue_shell["issue_number"]
    created_date = issue_shell["created_date"]
    archived_count = issue_shell["archived_count"]

    articles = db.get_issue_articles(issue_id)

    # Generate H5 report
    try:
        from src.report_generator import generate_report
        output_path = generate_report(articles, CONFIG, issue_number=issue_number, report_type="daily", report_date=created_date)
        db.update_issue(issue_id, {"html_path": output_path})
    except Exception as e:
        logger.error(f"生成 H5 失败: {e}")
        db.update_issue(issue_id, {"status": "failed"})
        return jsonify({"ok": False, "error": f"生成 H5 失败: {str(e)[:200]}"}), 500

    return jsonify({
        "ok": True,
        "issue_id": issue_id,
        "issue_number": issue_number,
        "html_path": output_path,
        "archived_count": archived_count,
    })

@bp.route("/api/prepare-cards-async", methods=["POST"])
def api_prepare_cards_async():
    """后台任务化: 只为组刊篮文章准备卡片，不创建期刊。"""
    data = request.json or {}
    article_ids, selected_articles, error = validate_issue_article_ids(db, data.get("article_ids", []))
    if error:
        return jsonify({"ok": False, "error": error})

    mode = data.get("mode") or "all"
    if mode not in ("all", "not_ready"):
        return jsonify({"ok": False, "error": "mode 必须是 all 或 not_ready"}), 400

    def _do_prepare(task_id):
        return run_card_prepare_task(
            db=db,
            config=CONFIG,
            logger=logger,
            task_id=task_id,
            task_store=_task_store,
            task_lock=_task_lock,
            card_gen_lock=_card_gen_lock,
            article_ids=article_ids,
            mode=mode,
        )

    task_id = _start_bg_task(_do_prepare)
    return jsonify({
        "ok": True,
        "task_id": task_id,
        "readiness": summarize_card_readiness(selected_articles),
    })

@bp.route("/api/prepare-card-async/<int:article_id>", methods=["POST"])
def api_prepare_single_card_async(article_id):
    """后台任务化: 强制重成单篇文章卡片，不创建期刊。"""
    article_ids, selected_articles, error = validate_issue_article_ids(db, [article_id])
    if error:
        return jsonify({"ok": False, "error": error})

    def _do_prepare(task_id):
        return run_card_prepare_task(
            db=db,
            config=CONFIG,
            logger=logger,
            task_id=task_id,
            task_store=_task_store,
            task_lock=_task_lock,
            card_gen_lock=_card_gen_lock,
            article_ids=article_ids,
            mode="force",
        )

    task_id = _start_bg_task(_do_prepare)
    return jsonify({
        "ok": True,
        "task_id": task_id,
        "readiness": summarize_card_readiness(selected_articles),
    })

@bp.route("/api/article-card-status/<int:article_id>", methods=["POST"])
def api_article_card_status(article_id):
    """Update card-level editorial status without changing article lifecycle state."""
    data = request.json or {}
    status = data.get("status")
    if status not in ("approved", "needs_rewrite", "none"):
        return jsonify({"ok": False, "error": "status 必须是 approved/needs_rewrite/none"}), 400
    article = db.get_article(article_id)
    if not article:
        return jsonify({"ok": False, "error": "文章不存在"}), 404
    if status == "approved":
        if article.get("pending_human") or article.get("summary_flagged"):
            return jsonify({"ok": False, "error": "文章待人工/摘要待审，不能按卡片人工通过"}), 400
        if not has_complete_card(article):
            return jsonify({"ok": False, "error": "卡片不完整，不能人工通过"}), 400
    reason = "manual_approved" if status == "approved" else None
    db.update_article(article_id, {
        "card_status": status,
        "card_review_reason": reason,
        "card_updated_at": datetime.now().isoformat(),
    })
    refreshed = db.get_articles_by_ids([article_id])
    return jsonify({"ok": True, "readiness": summarize_card_readiness(refreshed)})

@bp.route("/api/generate-issue-async", methods=["POST"])
def api_generate_issue_async():
    """后台任务化: 仅在卡片全部就绪后创建期刊并生成 H5。"""
    data = request.json or {}
    article_ids, selected_articles, error = validate_issue_article_ids(db, data.get("article_ids", []))
    if error:
        return jsonify({"ok": False, "error": error})

    integrity_errors = validate_issue_ready_for_h5({"article_ids": article_ids}, selected_articles)
    if integrity_errors:
        return jsonify({
            "ok": False,
            "error": "组刊已阻止，请先成卡/重成卡/人工通过: " + "；".join(integrity_errors),
            "readiness": summarize_card_readiness(selected_articles),
        }), 400

    def _do_generate(task_id):
        return run_issue_publish_task(
            db=db,
            config=CONFIG,
            logger=logger,
            task_id=task_id,
            task_store=_task_store,
            task_lock=_task_lock,
            article_ids=article_ids,
            data=data,
        )


    task_id = _start_bg_task(_do_generate)
    return jsonify({
        "ok": True, "task_id": task_id,
        "readiness": summarize_card_readiness(selected_articles),
    })

@bp.route("/api/task-status/<task_id>")
def api_task_status(task_id):
    """查询后台任务进度"""
    with _task_lock:
        t = _task_store.get(task_id)
    if not t:
        return jsonify({"ok": False, "error": "任务不存在"})
    return jsonify({"ok": True, "task_id": task_id, **t})

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

def _json_obj(value, fallback=None):
    if fallback is None:
        fallback = {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else fallback
        except Exception:
            return fallback
    return fallback

def _json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []

def _clean_card_text(value, max_len=6000):
    return str(value or "").strip()[:max_len]

def _clean_image_list(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s[:1000])
    return cleaned[:20]

def _issue_is_locked(issue: dict | None) -> bool:
    return bool(issue and issue.get("locked_at"))

def _locked_issue_response():
    return jsonify({"ok": False, "error": "期刊已发送锁定，不能再修改内容"}), 409

def _get_issue_article_or_error(issue_id: int, article_id: int):
    issue = db.get_issue(issue_id)
    if not issue:
        return None, None, (jsonify({"ok": False, "error": "期刊不存在"}), 404)
    issue_ids = [int(aid) for aid in issue.get("article_ids", [])]
    if article_id not in issue_ids:
        return issue, None, (jsonify({"ok": False, "error": "文章不属于此期刊"}), 404)
    article = db.get_article(article_id)
    if not article:
        return issue, None, (jsonify({"ok": False, "error": "文章不存在"}), 404)
    return issue, article, None

def _image_upload_dir() -> Path:
    configured = os.environ.get("IMAGE_CACHE_DIR")
    if configured:
        target = Path(configured)
    elif Path("/data/images").is_dir():
        target = Path("/data/images")
    else:
        target = Path(IMAGE_DIR)
    target.mkdir(parents=True, exist_ok=True)
    return target

@bp.route("/api/issue-card/<int:issue_id>/<int:article_id>", methods=["GET", "POST"])
def api_issue_card(issue_id, article_id):
    issue, article, error = _get_issue_article_or_error(issue_id, article_id)
    if error:
        return error
    card = _json_obj(article.get("card_json"), {})
    images = _json_list(article.get("images"))
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "issue_id": issue_id,
            "article_id": article_id,
            "article_title": article.get("translated_title") or article.get("title") or "",
            "category": article.get("category") or "",
            "locked": _issue_is_locked(issue),
            "card": card,
            "images": images,
        })
    if _issue_is_locked(issue):
        return _locked_issue_response()

    data = request.json or {}
    updates = {}
    card_update = data.get("card") or {}
    if isinstance(card_update, dict):
        for key, max_len in {
            "headline": 300,
            "channel": 80,
            "one_line": 300,
            "body": 6000,
            "deep_dive": 6000,
            "arrangement": 2000,
        }.items():
            if key in card_update:
                card[key] = _clean_card_text(card_update.get(key), max_len)
        if "cautions" in card_update:
            cautions = card_update.get("cautions")
            if isinstance(cautions, str):
                cautions = [x.strip() for x in cautions.splitlines() if x.strip()]
            elif isinstance(cautions, list):
                cautions = [_clean_card_text(x, 300) for x in cautions if _clean_card_text(x, 300)]
            else:
                cautions = []
            card["cautions"] = cautions[:8]
        updates["card_json"] = json.dumps(card, ensure_ascii=False)

    if "images" in data:
        updates["images"] = _clean_image_list(data.get("images"))

    if not updates:
        return jsonify({"ok": False, "error": "没有可保存的内容"}), 400
    db.update_article(article_id, updates)
    return jsonify({"ok": True})

@bp.route("/api/issue-card/<int:issue_id>/<int:article_id>/upload-image", methods=["POST"])
def api_issue_card_upload_image(issue_id, article_id):
    issue, article, error = _get_issue_article_or_error(issue_id, article_id)
    if error:
        return error
    if _issue_is_locked(issue):
        return _locked_issue_response()
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "未选择图片"}), 400
    original = secure_filename(f.filename)
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"ok": False, "error": "仅支持 jpg/png/webp/gif"}), 400
    filename = f"manual_{article_id}_{uuid.uuid4().hex[:10]}{ext}"
    target = _image_upload_dir() / filename
    f.save(target)
    image_path = str(target)
    return jsonify({"ok": True, "path": image_path})

def _regenerate_issue_h5(issue_id: int, issue: dict | None = None) -> str:
    issue = issue or db.get_issue(issue_id)
    if not issue:
        raise ValueError("期刊不存在")
    articles = db.get_issue_articles(issue_id)
    if not articles:
        raise ValueError("期刊无文章")
    integrity_errors = validate_issue_ready_for_h5(issue, articles)
    if integrity_errors:
        raise ValueError("重生成 H5 已阻止: " + "；".join(integrity_errors))

    from src.report_generator import generate_report
    # === 本期看点按 issue scope 重新生成，不信任 DB 里可能串期的旧文本 ===
    editor_note = issue.get("editor_note") or ""
    try:
        from run_generate_cards import generate_editor_note_for_articles
        scoped = generate_editor_note_for_articles(articles, config=CONFIG, issue_id=issue_id)
        if scoped:
            editor_note = scoped
            db.update_issue(issue_id, {"editor_note": editor_note})
    except Exception as _scope_e:
        logger.warning(f"regenerate-h5 scoped editor note failed: {_scope_e}, using stored")
    output_path = generate_report(
        articles, CONFIG,
        issue_number=issue.get("issue_number", ""),
        report_type=issue.get("report_type") or "daily",
        report_date=issue.get("report_date") or "",
        editor_note=editor_note,
    )
    db.update_issue(issue_id, {"html_path": output_path})
    return output_path

@bp.route("/api/issues/<int:issue_id>/replace-article", methods=["POST"])
def api_replace_issue_article(issue_id):
    try:
        issue = db.get_issue(issue_id)
        if not issue:
            return jsonify({"ok": False, "error": "期刊不存在"}), 404
        if _issue_is_locked(issue):
            return _locked_issue_response()

        data = request.json or {}
        old_article_id = int(data.get("old_article_id") or 0)
        new_article_id = int(data.get("new_article_id") or 0)
        old_status = data.get("old_status") or "candidate"
        reason = data.get("reason") or "manual_issue_replace"
        if not old_article_id or not new_article_id:
            return jsonify({"ok": False, "error": "缺少旧文章或新文章"}), 400
        if old_article_id == new_article_id:
            return jsonify({"ok": False, "error": "新旧文章不能是同一篇"}), 400
        issue_article_ids = [int(aid) for aid in issue.get("article_ids") or []]
        if old_article_id not in issue_article_ids:
            return jsonify({"ok": False, "error": "旧文章不在此期刊中"}), 400

        _, selected_articles, error = validate_issue_article_ids(db, [new_article_id])
        if error:
            return jsonify({"ok": False, "error": error}), 400
        new_article = selected_articles[0]
        if new_article.get("status") in ("in_issue", "published"):
            return jsonify({"ok": False, "error": f"新文章当前是{new_article.get('status')}状态，不能替换入刊"}), 400
        if new_article_id in issue_article_ids:
            return jsonify({"ok": False, "error": "新文章已经在本期中"}), 400

        readiness = get_card_readiness(new_article)
        if not readiness.get("ready"):
            label = readiness.get("label") or "未就绪"
            reason_text = readiness.get("reason") or ""
            return jsonify({
                "ok": False,
                "error": f"新文章还不能入刊: {label}" + (f" · {reason_text}" if reason_text else ""),
                "readiness": readiness,
            }), 400

        result = db.replace_issue_article(
            issue_id,
            old_article_id,
            new_article_id,
            old_status=old_status,
            reason=reason,
        )
        refreshed_issue = db.get_issue(issue_id)
        output_path = _regenerate_issue_h5(issue_id, refreshed_issue)
        return jsonify({"ok": True, "html_path": output_path, "replacement": result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        import traceback
        logger.error(f"替换期刊文章失败: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)[:200]}), 500

@bp.route("/api/regenerate-h5/<int:issue_id>", methods=["POST"])
def api_regenerate_h5(issue_id):
    try:
        issue = db.get_issue(issue_id)
        if not issue:
            return jsonify({"ok": False, "error": "期刊不存在"})
        if _issue_is_locked(issue):
            return _locked_issue_response()
        articles = db.get_issue_articles(issue_id)
        if not articles:
            return jsonify({"ok": False, "error": "期刊无文章"})
        output_path = _regenerate_issue_h5(issue_id, issue)
        return jsonify({"ok": True, "html_path": output_path})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        import traceback
        logger.error(f"补生成H5失败: {e}\n{traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)[:200]})

@bp.route("/api/lock-issue/<int:issue_id>", methods=["POST"])
def api_lock_issue(issue_id):
    """Mark an issue as sent/immutable. Content-changing actions are blocked after this."""
    try:
        issue = db.get_issue(issue_id)
        if not issue:
            return jsonify({"ok": False, "error": "期刊不存在"}), 404
        if _issue_is_locked(issue):
            return jsonify({"ok": True, "locked_at": issue.get("locked_at")})
        if not issue.get("html_path"):
            return jsonify({"ok": False, "error": "请先生成 H5 后再锁定"}), 400
        locked_at = datetime.now().isoformat()
        db.update_issue(issue_id, {"locked_at": locked_at})
        return jsonify({"ok": True, "locked_at": locked_at})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/api/void-issue/<int:issue_id>", methods=["POST"])
def api_void_issue(issue_id):
    """作废期刊: 文章退回候选池, 卡片缓存保留"""
    try:
        issue = db.get_issue(issue_id)
        if not issue:
            return jsonify({"ok": False, "error": "期刊不存在"}), 404
        if _issue_is_locked(issue):
            return _locked_issue_response()
        result = db.void_issue(issue_id)
        logger.info(
            f"期刊 #{issue_id} 已作废, issue_number={result['issue_number']} -> {result['voided_number']}, "
            f"{result['count']} 篇文章退回候选"
        )
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@bp.route("/api/issues")
def api_issues():
    issues = db.get_all_issues()
    return jsonify(issues)

@bp.route("/api/issue-articles/<int:issue_id>")
def api_issue_articles(issue_id):
    articles = db.get_issue_articles(issue_id)
    return jsonify(articles)
