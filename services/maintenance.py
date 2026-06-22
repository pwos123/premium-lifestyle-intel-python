"""Long-running maintenance jobs used by the web maintenance routes."""

import threading
from datetime import datetime

from services.article_lifecycle import recompute_gate2_tier
from src.config import load_config, load_model_configs
from web.state import db, logger

_maint_tasks = {}

def _parse_article_ids(value) -> list[int]:
    if not value:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value).replace("\n", ",").replace("，", ",").split(",")
    ids = []
    for item in raw:
        try:
            aid = int(str(item).strip())
        except Exception:
            continue
        if aid > 0 and aid not in ids:
            ids.append(aid)
    return ids


def _issue_article_ids(issue_id) -> list[int]:
    try:
        iid = int(issue_id)
    except Exception:
        return []
    issue = db.get_issue(iid)
    if not issue:
        return []
    return [int(aid) for aid in (issue.get("article_ids") or [])]


def _rows_by_query(sql: str, args=()) -> list[dict]:
    with db._get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
        return [db._row_to_dict(r) for r in rows]


def _summary_target_articles(params: dict) -> list[dict]:
    params = params or {}
    mode = params.get("mode") or "ids"
    limit = max(1, min(int(params.get("limit") or 20), 100))
    ids = _parse_article_ids(params.get("ids"))
    if mode == "ids":
        return db.get_articles_by_ids(ids)
    where_map = {
        "featured": """gate2_tier IN ('A','B') AND status='pending'
                       AND COALESCE(evergreen,0)=0
                       AND COALESCE(pending_human,0)=0
                       AND COALESCE(summary_flagged,0)=0""",
        "selectable": """gate2_tier IN ('A','B','C') AND status='pending'
                         AND COALESCE(evergreen,0)=0
                         AND COALESCE(pending_human,0)=0
                         AND COALESCE(summary_flagged,0)=0""",
        "candidate": """status IN ('candidate','approved')
                        AND issue_id IS NULL
                        AND COALESCE(pending_human,0)=0
                        AND COALESCE(summary_flagged,0)=0""",
        "evergreen": """evergreen=1
                        AND status IN ('pending','candidate','approved')
                        AND issue_id IS NULL
                        AND COALESCE(pending_human,0)=0
                        AND COALESCE(summary_flagged,0)=0""",
    }
    where = where_map.get(mode)
    if not where:
        return []
    return _rows_by_query(
        f"""SELECT * FROM articles
            WHERE {where}
              AND summary IS NOT NULL AND summary != ''
            ORDER BY crawled_at DESC LIMIT ?""",
        (limit,),
    )


def _feedback_target_articles(params: dict) -> list[dict]:
    params = params or {}
    ids = _parse_article_ids(params.get("ids"))
    issue_id = params.get("issue_id")
    if issue_id:
        ids = _issue_article_ids(issue_id)
    if not ids:
        return []
    articles = db.get_articles_by_ids(ids)
    return [
        a for a in articles
        if a.get("dj_feedback") or a.get("feedback_detail")
    ]


def _reeval_target_articles(params: dict) -> list[dict]:
    params = params or {}
    ids = _parse_article_ids(params.get("ids"))
    if ids:
        articles = db.get_articles_by_ids(ids)
        return [
            a for a in articles
            if a.get("pending_human") and a.get("fit_keywords_hit")
        ]
    limit = max(1, min(int(params.get("limit") or 100), 300))
    return _rows_by_query(
        """SELECT * FROM articles
           WHERE pending_human=1
             AND fit_keywords_hit IS NOT NULL
             AND fit_keywords_hit != ''
             AND fit_keywords_hit != '[]'
           ORDER BY crawled_at DESC LIMIT ?""",
        (limit,),
    )


def _reveto_target_articles(params: dict) -> list[dict]:
    params = params or {}
    ids = _parse_article_ids(params.get("ids"))
    if ids:
        return [
            a for a in db.get_articles_by_ids(ids)
            if not a.get("pending_human")
        ]
    mode = params.get("mode") or "reviewable"
    limit = max(1, min(int(params.get("limit") or 10), 100))
    where_map = {
        "reviewable": """(status IN ('candidate','approved') OR gate3_selected=1)
                         AND COALESCE(pending_human,0)=0
                         AND (veto_hit IS NULL OR veto_hit=0)""",
        "featured": """gate2_tier IN ('A','B')
                       AND status='pending'
                       AND COALESCE(evergreen,0)=0
                       AND COALESCE(pending_human,0)=0
                       AND COALESCE(summary_flagged,0)=0
                       AND (veto_hit IS NULL OR veto_hit=0)""",
        "selectable": """gate2_tier IN ('A','B','C')
                         AND status='pending'
                         AND COALESCE(evergreen,0)=0
                         AND COALESCE(pending_human,0)=0
                         AND COALESCE(summary_flagged,0)=0
                         AND (veto_hit IS NULL OR veto_hit=0)""",
        "c_tier": """gate2_tier='C'
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                     AND (veto_hit IS NULL OR veto_hit=0)""",
        "candidate": """status IN ('candidate','approved')
                        AND COALESCE(pending_human,0)=0
                        AND (veto_hit IS NULL OR veto_hit=0)""",
    }
    where = where_map.get(mode)
    if not where:
        return []
    return _rows_by_query(
        f"""SELECT * FROM articles
            WHERE {where}
            ORDER BY crawled_at DESC LIMIT ?""",
        (limit,),
    )


def _reeval_decision(article: dict) -> dict:
    import json as _json
    from prompts.gate2_dj_tier import check_fit_forbidden

    try:
        hits = _json.loads(article.get("fit_keywords_hit", "[]")) if isinstance(article.get("fit_keywords_hit"), str) else (article.get("fit_keywords_hit") or [])
    except Exception:
        hits = []
    new_hits = check_fit_forbidden([str(h) for h in hits if h], article.get("category", ""))
    return {
        "hits": hits,
        "new_hits": new_hits,
        "action": "reset" if not new_hits else "keep",
    }


def _article_preview_rows(articles: list[dict]) -> list[dict]:
    return [{
        "id": a.get("id"),
        "title": a.get("translated_title") or a.get("title") or "",
        "category": a.get("category") or "",
        "source": a.get("source") or "",
        "status": a.get("status") or "",
        "tier": a.get("gate2_tier") or "",
        "dj_feedback": a.get("dj_feedback") or "",
        "feedback_detail": a.get("feedback_detail") or "",
    } for a in articles]


def preview_resummarize(params: dict) -> dict:
    articles = _summary_target_articles(params)
    return {"count": len(articles), "articles": _article_preview_rows(articles)}


def preview_clear_feedback(params: dict) -> dict:
    articles = _feedback_target_articles(params)
    return {"count": len(articles), "articles": _article_preview_rows(articles)}


def preview_reeval(params: dict) -> dict:
    articles = _reeval_target_articles(params)
    rows = []
    reset_count = 0
    for a in articles:
        row = _article_preview_rows([a])[0]
        decision = _reeval_decision(a)
        row.update(decision)
        if decision["action"] == "reset":
            reset_count += 1
        rows.append(row)
    return {"count": reset_count, "total": len(rows), "articles": rows}


def preview_reveto(params: dict) -> dict:
    articles = _reveto_target_articles(params)
    return {"count": len(articles), "articles": _article_preview_rows(articles)}


def _run_resummarize(params=None):
    import time as _time
    import traceback as _tb
    from src.models import LLMCaller, ModelConfig
    task = _maint_tasks["resummarize"]
    task["status"] = "running"
    try:
        logger.info("resummarize: 开始摘要重跑")
        config = load_config()
        model_configs = load_model_configs(config)
        qwen_cfg = model_configs.get("qwen")
        if not qwen_cfg:
            task["status"] = "error"; task["error"] = "qwen未配置"; return
        mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url, model="qwen-flash")
        caller = LLMCaller({"qwen": mc})

        RESUMMARIZE = """你是一位专业编辑。请根据原文,用中文写一段100字以内的事实摘要。只陈述事实。
禁用词:不可错过、文化盛事、极致、奢华、彰显品味、引领潮流、匠心独运、完美诠释、深度探访、值得拥有、读者、人群、爱好者、品鉴、探访、高端人士。不评价不推荐不展望。只输出JSON:{"article_id":"原样回显","title":"原样回显","summary":"摘要文本"}"""
        banned = ["不可错过","文化盛事","极致","奢华","彰显品味","引领潮流","匠心独运","完美诠释","深度探访","值得拥有","读者","人群","爱好者","品鉴","探访","高端人士"]

        def validate(s):
            if len(s) > 120: return "超长(" + str(len(s)) + "字)"
            hit = [w for w in banned if w in s]
            if hit: return "禁用词:" + ",".join(hit)
            return None

        articles = _summary_target_articles(params or {})

        stats = {"total": len(articles), "ok": 0, "retry_ok": 0, "failed": 0}
        failed_list = []
        for i, a in enumerate(articles):
            task["progress"] = i + 1
            aid = a["id"]
            content_text = (a.get("content") or "")[:2000]
            prompt = "article_id: " + str(aid) + "\n标题: " + str(a.get('title','')) + "\n正文: " + content_text + "\n信源: " + str(a.get('source','')) + "\n只输出 JSON。"
            try:
                result = caller.call_model("qwen", RESUMMARIZE, prompt, temperature=0.2, max_tokens=500, timeout=30)
                if not result.success or not result.data:
                    stats["failed"] += 1; failed_list.append("id=" + str(aid) + " API失败"); continue
                new_summary = result.data.get("summary", "")
                fail_reason = validate(new_summary)
                if fail_reason:
                    _time.sleep(0.3)
                    result2 = caller.call_model("qwen", RESUMMARIZE, prompt, temperature=0.3, max_tokens=500, timeout=30)
                    if result2.success and result2.data:
                        new_summary2 = result2.data.get("summary", "")
                        if validate(new_summary2):
                            db.update_article(aid, {"summary": "[摘要待人工] " + new_summary[:80], "summary_flagged": 1})
                            stats["failed"] += 1; failed_list.append("id=" + str(aid) + " 重试仍不合格"); continue
                        stats["retry_ok"] += 1; db.update_article(aid, {"summary": new_summary2}); continue
                    db.update_article(aid, {"summary": "[摘要待人工] " + new_summary[:80], "summary_flagged": 1})
                    stats["failed"] += 1; failed_list.append("id=" + str(aid) + " 重试API失败"); continue
                stats["ok"] += 1; db.update_article(aid, {"summary": new_summary})
            except Exception as e:
                stats["failed"] += 1; failed_list.append("id=" + str(aid) + " " + str(e)[:50])
            _time.sleep(0.2)
        task["result"] = {"ok": True, "stats": stats, "failed_list": failed_list[:20], "summary": "处理 " + str(stats["total"]) + " 篇, 成功 " + str(stats["ok"]) + ", 重试成功 " + str(stats["retry_ok"]) + ", 失败 " + str(stats["failed"])}
        task["status"] = "done"
    except Exception as e:
        logger.error(f"维护任务失败: {e}")
        logger.error(_tb.format_exc())
        task["status"] = "error"; task["error"] = str(e)[:500]


def _run_reeval(params=None):
    import traceback as _tb
    task = _maint_tasks["reeval"]
    task["status"] = "running"
    try:
        logger.info("reeval: 开始重新评估待人工队列")
        reset_count = 0; keep_count = 0; reset_ids = []; tier_fixes = []
        articles = _reeval_target_articles(params or {})
        for i, a in enumerate(articles):
            task["progress"] = i + 1
            cat = a.get("category","")
            decision = _reeval_decision(a)
            hits = decision["hits"]
            new_hits = decision["new_hits"]
            if not new_hits:
                tier = recompute_gate2_tier(a.get("gate2_dim_excitement"), a.get("gate2_dim_feasibility"), a.get("gate2_dim_density"))
                updates = {"pending_human":0,"gate3_status":None,"fit_keywords_hit":None,"gate2_veto":None}
                if a.get("gate2_tier")=="D" and not a.get("veto_hit"):
                    updates["gate2_tier"]=tier; tier_fixes.append("id="+str(a["id"])+" D→"+tier)
                db.update_article(a["id"], updates)
                reset_count+=1; reset_ids.append("id="+str(a["id"])+" cat="+cat+" hits="+str(hits))
            else:
                keep_count+=1
        task["result"] = {"ok":True,"stats":{"reset":reset_count,"keep":keep_count,"tier_fixes":len(tier_fixes)},"reset_ids":reset_ids,"tier_fixes":tier_fixes,"summary":"复位 "+str(reset_count)+" 篇, 保持 "+str(keep_count)+" 篇"}
        task["status"] = "done"
    except Exception as e:
        logger.error(f"维护任务失败: {e}")
        logger.error(_tb.format_exc())
        task["status"] = "error"; task["error"] = str(e)[:500]


def _run_reveto(params=None):
    import time as _time
    import traceback as _tb
    from src.models import LLMCaller, ModelConfig
    from prompts.veto_check import VETO_CHECK_PROMPT
    task = _maint_tasks["reveto"]
    task["status"] = "running"
    try:
        logger.info("reveto: 开始否决重跑")
        config = load_config()
        model_configs = load_model_configs(config)
        qwen_cfg = model_configs.get("qwen")
        if not qwen_cfg:
            task["status"] = "error"; task["error"] = "qwen未配置"; return
        mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url, model="qwen-flash")
        caller = LLMCaller({"qwen": mc})
        articles = _reveto_target_articles(params or {})
        stats = {"total":len(articles),"veto":0,"pass":0,"error":0}
        veto_list = []
        for i, a in enumerate(articles):
            task["progress"] = i+1
            aid = a["id"]
            content_text = (a.get("content") or a.get("summary") or "")[:2000]
            prompt = "article_id: "+str(aid)+"\n标题: "+str(a.get('title',''))+"\n摘要: "+str(a.get('summary',''))+"\n正文: "+content_text+"\n频道: "+str(a.get('category',''))+"\n信源: "+str(a.get('source',''))+"\n请按照系统提示中的 JSON 格式输出判断结果。"
            try:
                result = caller.call_model("qwen", VETO_CHECK_PROMPT, prompt, temperature=0.1, max_tokens=400, timeout=30)
                if not result.success or not result.data:
                    stats["error"]+=1; continue
                data = result.data
                veto_hit = data.get("veto_hit", False)
                veto_rule = data.get("veto_rule", "")
                db.update_article(aid, {"veto_hit":1 if veto_hit else 0, "veto_rule":veto_rule if veto_rule and veto_rule!="null" else ""})
                if veto_hit:
                    db.update_article(aid, {"gate2_tier":"D","gate2_veto":"否决: "+veto_rule,"gate2_checked_at":datetime.now().isoformat()})
                    stats["veto"]+=1; veto_list.append("id="+str(aid)+" "+str(a.get('title',''))[:40])
                else:
                    stats["pass"]+=1
            except Exception as e:
                stats["error"]+=1
            _time.sleep(0.3)
        task["result"] = {"ok":True,"stats":stats,"veto_list":veto_list,"summary":"否决 "+str(stats["veto"])+" 篇, 通过 "+str(stats["pass"])+" 篇"}
        task["status"] = "done"
    except Exception as e:
        logger.error(f"reveto 失败: {e}")
        logger.error(_tb.format_exc())
        task["status"] = "error"; task["error"] = str(e)[:500]


def _run_clear_feedback(params=None):
    """清除指定文章的 dj_feedback / feedback_detail 勾选记录(不动文章状态与卡片缓存)。"""
    task = _maint_tasks["clear-feedback"]
    task["status"] = "running"
    try:
        articles = _feedback_target_articles(params or {})
        ids = [int(a["id"]) for a in articles]
        if not ids:
            task["result"] = {"ok": True, "stats": {"cleared": 0}, "summary": "没有可清除的勾选记录"}
            task["status"] = "done"
            return
        with db._get_conn() as conn:
            placeholders = ",".join(["?"] * len(ids))
            conn.execute(
                f"UPDATE articles SET dj_feedback=NULL, feedback_detail=NULL WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        task["result"] = {"ok": True, "stats": {"cleared": len(ids)}, "articles": _article_preview_rows(articles), "summary": f"已清除 {len(ids)} 篇文章的勾选记录"}
        task["status"] = "done"
        logger.info(f"clear-feedback 完成: {len(ids)} 篇")
    except Exception as e:
        task["status"] = "error"
        task["error"] = str(e)[:500]
        logger.error(f"clear-feedback 失败: {e}")


def start_resummarize(params=None):
    _maint_tasks["resummarize"] = {"status": "pending", "progress": 0}
    threading.Thread(target=_run_resummarize, args=(params or {},), daemon=True).start()


def start_reeval(params=None):
    _maint_tasks["reeval"] = {"status": "pending", "progress": 0}
    threading.Thread(target=_run_reeval, args=(params or {},), daemon=True).start()


def start_reveto(params=None):
    _maint_tasks["reveto"] = {"status": "pending", "progress": 0}
    threading.Thread(target=_run_reveto, args=(params or {},), daemon=True).start()


def start_clear_feedback(params=None):
    _maint_tasks["clear-feedback"] = {"status": "pending", "progress": 0}
    threading.Thread(target=_run_clear_feedback, args=(params or {},), daemon=True).start()


def get_status(op):
    task = _maint_tasks.get(op, {})
    return {
        "status": task.get("status", "unknown"),
        "progress": task.get("progress", 0),
        "result": task.get("result"),
        "error": task.get("error"),
    }
