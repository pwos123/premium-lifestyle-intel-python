#!/usr/bin/env python3
"""
每日图片清理 — 删除超过 max_age_days 的缓存图片，释放磁盘空间
用法: python run_image_cleanup.py [--dry-run]
调度: 建议每日凌晨 3:00 执行
"""

import argparse, logging, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.database import Database
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("img_cleanup")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dir", type=str, default=None)
    args = parser.parse_args()

    config = load_config()
    img_cfg = config.get("images", {})
    image_dir = args.dir or img_cfg.get("cache_dir", "static/images")
    max_age_days = img_cfg.get("max_age_days", 30)

    if not os.path.isdir(image_dir):
        logger.error(f"目录不存在: {image_dir}")
        return

    now = time.time()
    cutoff = now - max_age_days * 86400

    files = [f for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))]
    deleted = 0
    deleted_bytes = 0
    kept = 0

    for fname in files:
        fpath = os.path.join(image_dir, fname)
        mtime = os.path.getmtime(fpath)
        fsize = os.path.getsize(fpath)
        if mtime < cutoff:
            deleted_bytes += fsize
            deleted += 1
            if not args.dry_run:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
        else:
            kept += 1

    deleted_mb = deleted_bytes / (1024 * 1024)
    logger.info("=" * 50)
    logger.info(f"图片清理完成: {image_dir}")
    logger.info(f"  保留: {kept} | 删除: {deleted} | 释放: {deleted_mb:.1f} MB")
    logger.info(f"  策略: 超过 {max_age_days} 天未访问")

    # Log to DB
    if not args.dry_run and deleted > 0:
        try:
            db = Database(config["database"]["path"])
            db.log_task_run("image_cleanup", {
                "kept": kept, "deleted": deleted,
                "freed_mb": round(deleted_mb, 1),
                "max_age_days": max_age_days,
            }, f"图片清理: 删除{deleted}张, 释放{deleted_mb:.1f}MB")
        except Exception as e:
            logger.warning(f"DB日志写入失败: {e}")

    logger.info("=" * 50)


if __name__ == "__main__":
    main()
