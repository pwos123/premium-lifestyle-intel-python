#!/usr/bin/env python3
"""
时效自动出清 — 每日定时任务
检查周报候选与常青库中文章的时效字段，过期自动归档

用法: python run_expiry_check.py [--dry-run]
建议 cron: 0 8 * * * cd /path/to/project && python run_expiry_check.py
"""

import sys, logging, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("expiry_check")


def run_expiry_check(dry_run: bool = False):
    config = load_config()
    db = Database(config["database"]["path"])

    stats = db.run_expiry_check()

    summary = (
        f"过期检查: 扫描 {stats['checked']} 篇, "
        f"归档 {stats['archived']} 篇, "
        f"即将过期 {stats['nearing']} 篇"
    )

    if not dry_run and (stats["archived"] > 0 or stats["nearing"] > 0):
        db.log_task_run("expiry_check", stats, summary)

    logger.info(summary)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="时效自动出清: 检查过期文章并自动归档")
    parser.add_argument("--dry-run", action="store_true", help="仅检查不写入")
    args = parser.parse_args()
    run_expiry_check(dry_run=args.dry_run)
