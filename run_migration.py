#!/usr/bin/env python3
"""
存量数据迁移 — 部署后一次性执行
1. 对「精选待筛选」「周报候选」中的存量文章重跑否决检查
2. 同批文章重跑中文摘要
3. 输出迁移报告

用法: python run_migration.py [--dry-run] [--limit 200]
"""

import sys, json, logging, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import LLMCaller, ModelConfig
from src.database import Database
from src.config import load_config, load_model_configs
from prompts.veto_check import VETO_CHECK_PROMPT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")


RESUMMARIZE_PROMPT = """你是一位专业编辑。请根据原文,用中文写一段100字以内的事实摘要。只陈述事实:谁、做了什么、在哪、何时、规模数字。

禁用词(出现即不合格):不可错过、文化盛事、极致、奢华、彰显品味、引领潮流、匠心独运、完美诠释、深度探访、值得拥有

禁止描述读者:不得出现"适合……的读者/爱好者/人群"句式
禁止评价性收尾,以事实句结束

只输出 JSON:
{"article_id":"原样回显","title":"原样回显","summary":"摘要文本,100字以内"}"""


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


def build_summary_prompt(a: dict) -> str:
    content = (a.get("content") or "")[:2000]
    return f"""请为以下文章生成中文摘要:

article_id: {a['id']}
标题: {a.get('title', '')}
正文: {content}
信源: {a.get('source', '')}

只输出 JSON。"""


def run_migration(limit: int = 200, dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])
    model_configs = load_model_configs(config)

    qwen_cfg = model_configs.get("qwen")
    if not qwen_cfg:
        logger.error("qwen 未配置，无法执行迁移")
        return

    # Veto checker uses qwen-flash
    veto_mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url,
                          model="qwen-flash", weight=1.0)
    veto_caller = LLMCaller({"qwen": veto_mc})

    # Summarizer also uses qwen-flash
    summary_caller = LLMCaller({"qwen": veto_mc})

    # Get target articles
    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE (status IN ('candidate','approved') OR gate3_selected=1)
               ORDER BY crawled_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        articles = [db._row_to_dict(r) for r in rows]

    logger.info(f"迁移目标: {len(articles)} 篇文章")

    report = {
        "total_processed": len(articles),
        "veto_hits": 0,
        "veto_hit_titles": [],
        "summary_rerun": 0,
        "summary_errors": 0,
    }

    for i, a in enumerate(articles):
        aid = a["id"]
        title = (a.get("title") or "")[:60]
        logger.info(f"[{i+1}/{len(articles)}] {title}...")

        # Step 1: Veto check (only if not already checked)
        try:
            if a.get("veto_hit") is None or dry_run:
                prompt = build_veto_prompt(a)
                result = veto_caller.call_model("qwen", VETO_CHECK_PROMPT, prompt,
                                                temperature=0.1, max_tokens=400, timeout=30)
                if result.success and result.data:
                    veto_hit = result.data.get("veto_hit", False)
                    veto_rule = result.data.get("veto_rule", "")

                    if not dry_run:
                        db.update_article(aid, {
                            "veto_hit": 1 if veto_hit else 0,
                            "veto_rule": veto_rule if veto_rule and veto_rule != "null" else "",
                        })

                    if veto_hit:
                        report["veto_hits"] += 1
                        report["veto_hit_titles"].append(title)
                        if not dry_run:
                            db.update_article(aid, {
                                "gate2_tier": "D",
                                "gate2_veto": f"否决检查(迁移): {veto_rule}",
                            })
                            # Archive vetoed article
                            db.auto_archive(aid, "否决")
                        logger.info(f"  🚫 否决: {veto_rule}")
                        # Skip summary for vetoed articles
                        time.sleep(0.3)
                        continue
                    else:
                        logger.info(f"  ✅ 否决通过")
                else:
                    logger.warning(f"  否决检查调用失败: {result.error}")
        except Exception as e:
            logger.error(f"  否决检查异常: {e}")

        time.sleep(0.3)

        # Step 2: Rerun summary (only summary field)
        try:
            prompt = build_summary_prompt(a)
            result = summary_caller.call_model("qwen", RESUMMARIZE_PROMPT, prompt,
                                               temperature=0.2, max_tokens=500, timeout=30)

            if result.success and result.data:
                new_summary = result.data.get("summary", "")
                if not new_summary:
                    report["summary_errors"] += 1
                    continue

                # Validate banned words
                banned = ["不可错过", "文化盛事", "极致", "奢华", "彰显品味", "引领潮流",
                          "匠心独运", "完美诠释", "深度探访", "值得拥有"]
                hit_banned = [w for w in banned if w in new_summary]
                if hit_banned:
                    logger.warning(f"  ⚠️ 摘要含禁用词 {hit_banned}, 跳过")
                    report["summary_errors"] += 1
                    continue

                if "适合" in new_summary:
                    logger.warning(f"  ⚠️ 摘要含'适合……'句式, 跳过")
                    report["summary_errors"] += 1
                    continue

                if not dry_run:
                    db.update_article(aid, {"summary": new_summary})
                report["summary_rerun"] += 1
                logger.info(f"  📝 摘要 ({len(new_summary)}字)")
            else:
                report["summary_errors"] += 1
                logger.warning(f"  摘要生成失败: {result.error}")
        except Exception as e:
            report["summary_errors"] += 1
            logger.error(f"  摘要生成异常: {e}")

        time.sleep(0.3)

    # Output report
    logger.info(f"\n{'='*60}")
    logger.info(f"迁移报告")
    logger.info(f"{'='*60}")
    logger.info(f"处理总数: {report['total_processed']}")
    logger.info(f"否决拦截: {report['veto_hits']}")
    if report["veto_hit_titles"]:
        logger.info(f"否决文章清单:")
        for t in report["veto_hit_titles"]:
            logger.info(f"  - {t}")
    logger.info(f"摘要重跑: {report['summary_rerun']}")
    logger.info(f"摘要失败: {report['summary_errors']}")
    logger.info(f"{'='*60}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="存量数据迁移: 重跑否决检查与中文摘要")
    parser.add_argument("--limit", type=int, default=200, help="最大处理数")
    parser.add_argument("--dry-run", action="store_true", help="仅检查不写入")
    args = parser.parse_args()
    run_migration(limit=args.limit, dry_run=args.dry_run)
