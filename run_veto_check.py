#!/usr/bin/env python3
"""
否决检查 — 独立调用,位于第一关通过后、第二关评分前
用轻量模型(Qwen Flash),命中即标记D档终止流转
"""

import sys, json, logging, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs
from prompts.veto_check import VETO_CHECK_PROMPT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("veto")


def build_veto_prompt(a: dict) -> str:
    content = (a.get("content") or a.get("summary") or "")[:2000]
    return f"""请判断以下内容是否命中禁区:

article_id: {a['id']}
标题: {a.get('title', '')}
摘要: {a.get('summary', '')}
正文: {content}
频道: {a.get('category', '')}
信源: {a.get('source', '')}

请按照系统提示中的 JSON 格式输出判断结果。"""


def run_veto_check(limit: int = 400, dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    # Use qwen-flash (cheapest) for veto check
    qwen_cfg = model_configs.get("qwen")
    if not qwen_cfg:
        logger.error("qwen 未配置")
        return

    mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url,
                     model="qwen-flash", weight=1.0)
    caller = LLMCaller({"qwen": mc})

    # Get gate1=pass articles that haven't been veto-checked yet
    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE gate1_verdict='pass' AND veto_hit IS NULL
               ORDER BY crawled_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        articles = [db._row_to_dict(r) for r in rows]

    logger.info(f"否决检查: {len(articles)} 篇")

    stats = {"pass": 0, "veto": 0, "error": 0}

    for i, a in enumerate(articles):
        article_id = a["id"]
        title = (a.get("title") or "")[:50]
        logger.info(f"[{i+1}/{len(articles)}] {title}...")

        try:
            prompt = build_veto_prompt(a)
            result = caller.call_model("qwen", VETO_CHECK_PROMPT, prompt,
                                       temperature=0.1, max_tokens=400, timeout=30)

            if not result.success or not result.data:
                stats["error"] += 1
                logger.warning(f"  调用失败: {result.error}")
                continue

            data = result.data
            if str(data.get("article_id")) != str(article_id):
                logger.warning(f"  article_id 不一致,丢弃")
                stats["error"] += 1
                continue

            veto_hit = data.get("veto_hit", False)
            veto_rule = data.get("veto_rule", "")

            if not dry_run:
                db.update_article(article_id, {
                    "veto_hit": 1 if veto_hit else 0,
                    "veto_rule": veto_rule if veto_rule and veto_rule != "null" else "",
                })
                if veto_hit:
                    # Mark as D tier directly, skip gate2
                    db.update_article(article_id, {
                        "gate2_tier": "D",
                        "gate2_veto": f"否决检查: {veto_rule}",
                        "gate2_checked_at": __import__("datetime").datetime.now().isoformat(),
                    })

            if veto_hit:
                stats["veto"] += 1
                logger.info(f"  🚫 否决: {veto_rule}")
            else:
                stats["pass"] += 1
                logger.info(f"  ✅ 通过")

        except Exception as e:
            stats["error"] += 1
            logger.error(f"  EXCEPTION: {e}")

        time.sleep(0.3)

    logger.info(f"否决检查完成: pass={stats['pass']} veto={stats['veto']} error={stats['error']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="否决检查: Gate1→Gate2 之间的禁区过滤")
    parser.add_argument("--limit", type=int, default=400, help="最大处理数")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_veto_check(limit=args.limit, dry_run=args.dry_run)
