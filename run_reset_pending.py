#!/usr/bin/env python3
"""
复位被误杀的待人工文章 — fit_reasons 关键词收窄后
对当前处于 pending_human 且命中词仅为已移除裸词（如"手工""原木""限量"）的文章:
恢复原档位与正常流转状态
"""

import sys, json, logging, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reset_pending")

# Old bare keywords that are now removed (no longer trigger pending_human)
REMOVED_KEYWORDS = ["手工", "原木", "限量", "稀缺"]

def run_reset(dry_run=False):
    config = load_config()
    db = Database(config["database"]["path"])

    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE pending_human=1 AND fit_keywords_hit IS NOT NULL"
        ).fetchall()
        articles = [db._row_to_dict(r) for r in rows]

    logger.info(f"待检查: {len(articles)} 篇待人工文章")

    reset_count = 0
    keep_count = 0

    for a in articles:
        hits = a.get("fit_keywords_hit", [])
        if isinstance(hits, str):
            try:
                hits = json.loads(hits)
            except:
                hits = []

        if not hits:
            continue

        # Check if ALL hit keywords exactly match removed list entries
        # (substring match would cause "手工打造" to be wrongly reset when "手工" is removed)
        hits_lower = [str(h).lower().strip() for h in hits]
        removed_lower = [r.lower().strip() for r in REMOVED_KEYWORDS]
        all_removed = all(h in removed_lower for h in hits_lower)

        if all_removed:
            logger.info(f"  复位: {a['id']} {str(a.get('title',''))[:50]} (命中: {hits})")
            if not dry_run:
                db.update_article(a["id"], {
                    "pending_human": 0,
                    "gate3_status": None,
                    "fit_keywords_hit": None,
                    "gate2_veto": None,
                })
            reset_count += 1
        else:
            keep_count += 1

    logger.info(f"复位: {reset_count}, 保持待人工: {keep_count}")
    return {"reset": reset_count, "keep": keep_count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="复位被误杀的待人工文章")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_reset(dry_run=args.dry_run)
