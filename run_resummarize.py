#!/usr/bin/env python3
"""
批量重跑中文摘要 — 只更新 summary 字段,不动其他数据
用法: python run_resummarize.py [--limit 50] [--dry-run]
"""

import sys, json, logging, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("resummarize")


RESUMMARIZE_PROMPT = """你是一位专业编辑。请根据原文,用中文写一段150字以内的事实摘要。只陈述事实:谁、做了什么、在哪、何时、规模数字。

以下词语禁止出现(任何句式):
不可错过、文化盛事、极致、奢华、彰显品味、引领潮流、匠心独运、完美诠释、深度探访、值得拥有、读者、人群、爱好者、品鉴、探访、高端人士

不评价、不推荐、不展望,只陈述事实;最后一句必须仍是事实句

只输出 JSON:
{{"article_id":"原样回显","title":"原样回显","summary":"摘要文本,150字以内"}}"""


def build_prompt(a: dict) -> str:
    content = (a.get("content") or "")[:4000]
    return f"""请为以下文章生成中文摘要:

article_id: {a['id']}
标题: {a.get('title', '')}
正文: {content}
信源: {a.get('source', '')}

只输出 JSON。"""


def run_resummarize(limit: int = 200, dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    # Use cheapest model (qwen-flash) for resummarization
    qwen_cfg = model_configs.get("qwen")
    if not qwen_cfg:
        logger.error("qwen 未配置")
        return

    mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url,
                     model="qwen-flash", weight=1.0)
    caller = LLMCaller({"qwen": mc})

    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE (status IN ('candidate','approved') OR gate3_selected=1)
                 AND summary IS NOT NULL AND summary != ''
               ORDER BY crawled_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        articles = [db._row_to_dict(r) for r in rows]

    logger.info(f"重跑摘要: {len(articles)} 篇")

    stats = {"ok": 0, "error": 0}

    for i, a in enumerate(articles):
        article_id = a["id"]
        title = (a.get("title") or "")[:50]
        logger.info(f"[{i+1}/{len(articles)}] {title}...")

        try:
            prompt = build_prompt(a)
            result = caller.call_model("qwen", RESUMMARIZE_PROMPT, prompt,
                                       temperature=0.2, max_tokens=500, timeout=30)

            if not result.success or not result.data:
                stats["error"] += 1
                logger.warning(f"  调用失败: {result.error}")
                continue

            data = result.data
            if str(data.get("article_id")) != str(article_id):
                logger.warning(f"  article_id 不一致")
                stats["error"] += 1
                continue

            new_summary = data.get("summary", "")
            if not new_summary:
                stats["error"] += 1
                continue

            # Hard validation
            banned = ["不可错过", "文化盛事", "极致", "奢华", "彰显品味", "引领潮流",
                      "匠心独运", "完美诠释", "深度探访", "值得拥有",
                      "读者", "人群", "爱好者", "品鉴", "探访", "高端人士"]

            def validate_summary(s):
                if len(s) > 180:
                    return f"超长({len(s)}字)"
                hit = [w for w in banned if w in s]
                if hit:
                    return f"禁用词: {','.join(hit)}"
                return None

            fail_reason = validate_summary(new_summary)
            if fail_reason:
                # Retry once
                logger.warning(f"  ⚠️ 首次不合格({fail_reason}), 重试...")
                time.sleep(0.5)
                result2 = caller.call_model("qwen", RESUMMARIZE_PROMPT, prompt,
                                            temperature=0.3, max_tokens=500, timeout=30)
                if result2.success and result2.data and str(result2.data.get("article_id")) == str(article_id):
                    new_summary2 = result2.data.get("summary", "")
                    fail_reason2 = validate_summary(new_summary2)
                    if fail_reason2:
                        logger.warning(f"  ❌ 重试仍不合格({fail_reason2}), 标记待人工")
                        if not dry_run:
                            db.update_article(article_id, {
                                "summary": new_summary[:80],
                                "summary_flagged": 1,
                                "pending_human": 1,
                            })
                        stats["error"] += 1
                        continue
                    new_summary = new_summary2
                else:
                    logger.warning(f"  重试调用失败, 标记待人工")
                    if not dry_run:
                        db.update_article(article_id, {
                            "summary": new_summary[:80],
                                "summary_flagged": 1,
                            "pending_human": 1,
                        })
                    stats["error"] += 1
                    continue

            if not dry_run:
                db.update_article(article_id, {"summary": new_summary})

            stats["ok"] += 1
            logger.info(f"  ✅ ({len(new_summary)}字) {new_summary[:60]}...")

        except Exception as e:
            stats["error"] += 1
            logger.error(f"  EXCEPTION: {e}")

        time.sleep(0.3)

    logger.info(f"重跑摘要完成: ok={stats['ok']} error={stats['error']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量重跑中文摘要")
    parser.add_argument("--limit", type=int, default=200, help="最大处理数")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_resummarize(limit=args.limit, dry_run=args.dry_run)
