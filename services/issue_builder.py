"""Issue-building helpers shared by issue routes."""

import json
import traceback
from datetime import date, datetime

from src.config import load_config

CARD_READY_STATUSES = {"ready", "approved"}
CARD_NOT_READY_STATUSES = {"none", "needs_rewrite", "date_risk", "failed"}

CARD_STATUS_LABELS = {
    "ready": "可入刊",
    "approved": "人工通过",
    "none": "待成卡",
    "needs_rewrite": "卡待重写",
    "date_risk": "日期风险",
    "failed": "成卡失败",
    "article_blocked": "文章待人工",
}

CARD_REASON_LABELS = {
    "missing_card": "缺完整card_json",
    "incomplete_card": "缺完整card_json",
    "editor_confidence_low": "低置信",
    "example_similarity": "疑似套用示例",
    "person_ref_leak": "人称泄漏",
    "forbidden_hit": "违禁词命中",
    "card_api_failed": "成卡失败",
    "card_exception": "成卡异常",
    "date_year_mismatch": "年份疑似写错",
    "manual_approved": "人工通过",
    "pending_human": "待人工",
    "summary_flagged": "摘要待审",
}


def _reason_label(reason_code: str) -> str:
    if reason_code.startswith("date_year_mismatch"):
        return CARD_REASON_LABELS["date_year_mismatch"]
    return CARD_REASON_LABELS.get(reason_code, reason_code)


def validate_issue_article_ids(db, raw_article_ids):
    if not raw_article_ids:
        return None, None, "未选择文章"
    try:
        article_ids = [int(aid) for aid in raw_article_ids]
    except (TypeError, ValueError):
        return None, None, "文章ID格式不正确"

    selected_articles = db.get_articles_by_ids(article_ids)
    if len(selected_articles) != len(article_ids):
        found = {a["id"] for a in selected_articles}
        missing = [aid for aid in article_ids if aid not in found]
        return None, None, f"文章不存在: {missing}"

    blocked = []
    for a in selected_articles:
        reasons = []
        if a.get("status") in ("rejected", "sunk", "published"):
            reasons.append(f"状态={a.get('status')}")
        if a.get("issue_id"):
            reasons.append(f"已在期刊#{a.get('issue_id')}")
        if a.get("pending_human"):
            reasons.append("待人工")
        if a.get("summary_flagged"):
            reasons.append("摘要待审")
        if reasons:
            blocked.append(f"{a['id']}({';'.join(reasons)})")
    if blocked:
        return None, None, f"以下文章不可入刊或需人工复核: {blocked}"

    return article_ids, selected_articles, None


def _parse_card(article: dict) -> dict:
    card_json = article.get("card_json", "")
    if isinstance(card_json, dict):
        return card_json
    if isinstance(card_json, str) and card_json.strip():
        try:
            parsed = json.loads(card_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def has_complete_card(article: dict) -> bool:
    card = _parse_card(article)
    return bool(card and card.get("body") and card.get("deep_dive"))


def get_card_readiness(article: dict) -> dict:
    """Return card-level readiness without conflating it with article review state."""
    aid = article.get("id")
    if article.get("pending_human"):
        return {
            "id": aid,
            "ready": False,
            "status": "article_blocked",
            "label": CARD_STATUS_LABELS["article_blocked"],
            "reason": CARD_REASON_LABELS["pending_human"],
            "reason_code": "pending_human",
        }
    if article.get("summary_flagged"):
        return {
            "id": aid,
            "ready": False,
            "status": "article_blocked",
            "label": CARD_STATUS_LABELS["article_blocked"],
            "reason": CARD_REASON_LABELS["summary_flagged"],
            "reason_code": "summary_flagged",
        }

    card = _parse_card(article)
    complete = bool(card and card.get("body") and card.get("deep_dive"))
    raw_status = str(article.get("card_status") or "").strip()
    status = raw_status if raw_status in CARD_READY_STATUSES | CARD_NOT_READY_STATUSES else ""
    reason_code = str(article.get("card_review_reason") or "").strip()

    if not complete:
        if status == "failed":
            final_status = "failed"
            final_reason = reason_code or "card_api_failed"
        else:
            final_status = "none"
            final_reason = "missing_card"
        return {
            "id": aid,
            "ready": False,
            "status": final_status,
            "label": CARD_STATUS_LABELS[final_status],
            "reason": _reason_label(final_reason),
            "reason_code": final_reason,
        }

    if status == "approved":
        return {
            "id": aid,
            "ready": True,
            "status": "approved",
            "label": CARD_STATUS_LABELS["approved"],
            "reason": _reason_label(reason_code),
            "reason_code": reason_code,
        }

    if status in {"needs_rewrite", "date_risk", "failed"}:
        if status == "failed":
            final_reason = reason_code or "card_api_failed"
        elif status == "date_risk":
            final_reason = reason_code or "date_year_mismatch"
        else:
            final_reason = reason_code or "editor_confidence_low"
        return {
            "id": aid,
            "ready": False,
            "status": status,
            "label": CARD_STATUS_LABELS[status],
            "reason": _reason_label(final_reason),
            "reason_code": final_reason,
        }

    if card.get("editor_confidence") == "low":
        return {
            "id": aid,
            "ready": False,
            "status": "needs_rewrite",
            "label": CARD_STATUS_LABELS["needs_rewrite"],
            "reason": CARD_REASON_LABELS["editor_confidence_low"],
            "reason_code": "editor_confidence_low",
        }

    return {
        "id": aid,
        "ready": True,
        "status": "ready",
        "label": CARD_STATUS_LABELS["ready"] if status == "ready" else "旧卡可复用",
        "reason": _reason_label(reason_code),
        "reason_code": reason_code,
    }


def has_pending_human_blocker(article: dict) -> bool:
    return bool(
        article.get("pending_human")
        or article.get("summary_flagged")
    )


def incomplete_or_blocked_card_ids(articles: list[dict]) -> list[int]:
    return [a["id"] for a in articles if not get_card_readiness(a)["ready"]]


def _normalize_issue_article_ids(raw_article_ids) -> list[int]:
    if isinstance(raw_article_ids, str):
        try:
            raw_article_ids = json.loads(raw_article_ids)
        except Exception:
            raw_article_ids = []
    try:
        return [int(aid) for aid in raw_article_ids or []]
    except (TypeError, ValueError):
        return []


def validate_issue_ready_for_h5(issue: dict, articles: list[dict]) -> list[str]:
    """Return blocking reasons that would make an issue render incomplete H5."""
    errors = []
    issue_ids = _normalize_issue_article_ids(issue.get("article_ids", []))
    found_ids = {int(a["id"]) for a in articles}
    missing_ids = [aid for aid in issue_ids if aid not in found_ids]
    if missing_ids:
        errors.append(f"期刊 article_ids 中有文章不存在或未取回: {missing_ids}")

    blocked = []
    for a in articles:
        reasons = get_issue_article_blockers(a)
        if reasons:
            blocked.append(f"{a['id']}({';'.join(reasons)})")
    if blocked:
        errors.append(f"以下文章不可生成H5: {blocked}")
    return errors


def get_issue_article_blockers(article: dict) -> list[str]:
    readiness = get_card_readiness(article)
    if readiness["ready"]:
        return []
    reason = readiness.get("reason") or readiness.get("label") or "未就绪"
    return [reason]


def split_h5_ready_articles(articles: list[dict]) -> tuple[list[dict], list[str]]:
    ready = []
    blocked = []
    for article in articles:
        reasons = get_issue_article_blockers(article)
        if reasons:
            blocked.append(f"{article['id']}({';'.join(reasons)})")
        else:
            ready.append(article)
    return ready, blocked


def summarize_card_readiness(articles: list[dict]) -> dict:
    items = []
    counts = {
        "total": len(articles),
        "ready": 0,
        "approved": 0,
        "none": 0,
        "needs_rewrite": 0,
        "date_risk": 0,
        "failed": 0,
        "article_blocked": 0,
        "not_ready": 0,
    }
    for article in articles:
        readiness = get_card_readiness(article)
        status = readiness["status"]
        if readiness["ready"]:
            counts["ready"] += 1
            if status == "approved":
                counts["approved"] += 1
        else:
            counts["not_ready"] += 1
            if status in counts:
                counts[status] += 1
        items.append({
            **readiness,
            "title": article.get("translated_title") or article.get("title") or "",
            "category": article.get("category") or "",
            "gate2_tier": article.get("gate2_tier") or "",
        })
    return {"counts": counts, "items": items}


def run_card_prepare_task(
    *,
    db,
    config,
    logger,
    task_id: str,
    task_store: dict,
    task_lock,
    card_gen_lock,
    article_ids: list[int],
    mode: str = "all",
):
    """Prepare cards for selected articles without creating or mutating an issue."""
    try:
        from run_generate_cards import run_card_generation

        articles = db.get_articles_by_ids(article_ids)
        if mode == "force":
            target_ids = [a["id"] for a in articles]
        elif mode == "not_ready":
            target_ids = [a["id"] for a in articles if not get_card_readiness(a)["ready"]]
        else:
            # 主按钮“成卡”只补齐/重写未就绪卡，避免无谓覆盖可入刊旧卡。
            target_ids = [a["id"] for a in articles if not get_card_readiness(a)["ready"]]

        with task_lock:
            task_store[task_id]["progress"] = 5
            task_store[task_id]["status_text"] = f"待处理卡片 {len(target_ids)} 篇"

        stats = {"success": 0, "fact_fail": 0, "card_fail": 0, "cached": 0, "forbidden_hit": 0, "pending_human": 0, "needs_rewrite": 0}
        if target_ids:
            def _card_progress(done, total):
                with task_lock:
                    pct = min(5 + int(done / max(total, 1) * 80), 85)
                    task_store[task_id]["progress"] = pct
                    task_store[task_id]["status_text"] = f"成卡 {done}/{total}"

            with card_gen_lock:
                result = run_card_generation(
                    limit=len(target_ids),
                    dry_run=False,
                    force=True,
                    progress_callback=_card_progress,
                    article_ids=target_ids,
                    generate_editor_note=False,
                )
            if result:
                stats, _, _ = result

        refreshed = db.get_articles_by_ids(article_ids)
        summary = summarize_card_readiness(refreshed)
        with task_lock:
            task_store[task_id]["progress"] = 95
            task_store[task_id]["status_text"] = (
                f"可入刊 {summary['counts']['ready']} / {summary['counts']['total']} 篇"
            )
        return {
            "stats": stats,
            "readiness": summary,
        }
    except Exception as e:
        logger.error(f"成卡准备失败: {e}\n{traceback.format_exc()}")
        raise


def run_issue_publish_task(
    *,
    db,
    config,
    logger,
    task_id: str,
    task_store: dict,
    task_lock,
    article_ids: list[int],
    data: dict,
):
    """Create an issue and render H5 only after every selected card is ready."""
    issue_id = None
    try:
        from run_generate_cards import generate_editor_note_for_articles
        from src.report_generator import generate_report

        articles = db.get_articles_by_ids(article_ids)
        integrity_errors = validate_issue_ready_for_h5({"article_ids": article_ids}, articles)
        if integrity_errors:
            raise RuntimeError("组刊已阻止: " + "；".join(integrity_errors))

        with task_lock:
            task_store[task_id]["progress"] = 10
            task_store[task_id]["status_text"] = "创建期刊..."

        issue_shell = create_issue_shell(db, article_ids, data)
        issue_id = issue_shell["issue_id"]
        issue_number = issue_shell["issue_number"]
        created_date = issue_shell["created_date"]
        archived_count = issue_shell["archived_count"]

        articles = db.get_issue_articles(issue_id)
        integrity_errors = validate_issue_ready_for_h5({"article_ids": article_ids}, articles)
        if integrity_errors:
            raise RuntimeError("组刊已阻止: " + "；".join(integrity_errors))

        with task_lock:
            task_store[task_id]["progress"] = 35
            task_store[task_id]["status_text"] = "生成本期看点..."

        editor_note = ""
        try:
            scoped_note = generate_editor_note_for_articles(articles, config=config, issue_id=issue_id)
            if scoped_note:
                editor_note = scoped_note
        except Exception as _scope_e:
            logger.warning(f"issue-scoped 看点异常: {_scope_e}")

        db.update_issue(issue_id, {
            "report_type": "daily",
            "report_date": created_date or date.today().strftime("%Y-%m-%d"),
            "editor_note": editor_note,
        })

        with task_lock:
            task_store[task_id]["progress"] = 70
            task_store[task_id]["status_text"] = "渲染H5..."

        output_path = generate_report(
            articles,
            config,
            editor_note=editor_note,
            issue_number=issue_number,
            report_type="daily",
            report_date=created_date,
        )
        if output_path:
            db.publish_issue(issue_id, output_path)

        return {
            "issue_id": issue_id,
            "issue_number": issue_number,
            "html_path": output_path or "",
            "article_count": len(articles),
            "archived_count": archived_count,
        }
    except Exception as e:
        logger.error(f"组刊生成失败 (issue={issue_id}): {e}\n{traceback.format_exc()}")
        if issue_id:
            try:
                released = db.fail_issue_release_articles(issue_id)
                logger.warning("issue#%s 已标记失败并释放 %s 篇文章", issue_id, released)
            except Exception:
                pass
        raise


def create_issue_shell(db, article_ids: list[int], data: dict) -> dict:
    now = datetime.now()
    issue_number = str(data.get("issue_number") or db.get_next_issue_number())
    created_date = data.get("created_date") or now.strftime("%Y-%m-%d")

    issue_id = db.create_issue(issue_number, created_date, article_ids)
    db.assign_to_issue(article_ids, issue_id)

    throttle_cfg = load_config().get("throttle", {})
    carryover_limit = throttle_cfg.get("carryover_limit", 2)
    archived_count = db.carryover_candidates(article_ids, carryover_limit=carryover_limit)

    return {
        "issue_id": issue_id,
        "issue_number": issue_number,
        "created_date": created_date,
        "archived_count": archived_count,
    }
