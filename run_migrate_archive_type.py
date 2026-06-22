#!/usr/bin/env python3
"""存量数据迁移: 为已有的 rejected 文章设置 archive_type"""
import sys, logging, argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from src.database import Database, _archive_type_for_reason
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_archive_type")


def run(dry_run=False):
    config = load_config()
    db = Database(config["database"]["path"])
    now = datetime.now().isoformat()
    migration_report = {}
    detail = []

    with db._get_conn() as conn:
        # 1. 迁移已 rejected 但无 archive_type 的文章
        rows = conn.execute(
            "SELECT * FROM articles WHERE status='rejected' AND archive_type IS NULL"
        ).fetchall()
        logger.info(f"1. rejected 无 archive_type: {len(rows)} 篇")
        for row in rows:
            d = dict(row)
            reason = d.get("archive_reason") or ""
            atype = _archive_type_for_reason(reason) if reason else "archived"
            title = (d.get("title") or "")[:40]
            if not dry_run:
                conn.execute("UPDATE articles SET archive_type=? WHERE id=?", (atype, d["id"]))
            k = f"1_rejected→{atype}"
            migration_report[k] = migration_report.get(k, 0) + 1
            detail.append(f"  id={d['id']} rejected reason='{reason}' -> {atype} | {title}")

        # 2. gate1 fail -> 归档 (skip if already rejected)
        g1_rows = conn.execute(
            "SELECT * FROM articles WHERE gate1_verdict='fail' AND status!='rejected'"
        ).fetchall()
        logger.info(f"2. Gate1 fail 待归档: {len(g1_rows)} 篇")
        for row in g1_rows:
            d = dict(row)
            title = (d.get("title") or "")[:40]
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET status='rejected', archive_reason='质检未通过', archive_reason_at=?, reviewed_at=?, archive_type='archived' WHERE id=?",
                    (now, now, d["id"])
                )
            migration_report["2_gate1_fail→archived"] = migration_report.get("2_gate1_fail→archived", 0) + 1
            detail.append(f"  id={d['id']} gate1=fail -> archived | {title}")

        # 3. gate2 D 档 -> 归档 (skip if already rejected)
        g2d_rows = conn.execute(
            "SELECT * FROM articles WHERE gate2_tier='D' AND status!='rejected'"
        ).fetchall()
        logger.info(f"3. Gate2 D档 待归档: {len(g2d_rows)} 篇")
        for row in g2d_rows:
            d = dict(row)
            title = (d.get("title") or "")[:40]
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET status='rejected', archive_reason='D档淘汰', archive_reason_at=?, reviewed_at=?, archive_type='archived' WHERE id=?",
                    (now, now, d["id"])
                )
            migration_report["3_gate2_D→archived"] = migration_report.get("3_gate2_D→archived", 0) + 1
            detail.append(f"  id={d['id']} gate2=D -> archived | {title}")

        # 4. 否决命中 -> 归档 (skip if already rejected)
        veto_rows = conn.execute(
            "SELECT * FROM articles WHERE veto_hit=1 AND status!='rejected'"
        ).fetchall()
        logger.info(f"4. 否决命中 待归档: {len(veto_rows)} 篇")
        for row in veto_rows:
            d = dict(row)
            title = (d.get("title") or "")[:40]
            reason = f"否决: {d.get('veto_rule','')}" if d.get("veto_rule") else "否决检查命中"
            if not dry_run:
                conn.execute(
                    "UPDATE articles SET status='rejected', archive_reason=?, archive_reason_at=?, reviewed_at=?, archive_type='archived' WHERE id=?",
                    (reason[:100], now, now, d["id"])
                )
            migration_report["4_veto→archived"] = migration_report.get("4_veto→archived", 0) + 1
            detail.append(f"  id={d['id']} veto -> archived | {title}")

    # Summary
    logger.info(f"\n=== 迁移报告 ===")
    total = 0
    for k, v in sorted(migration_report.items()):
        logger.info(f"  {k}: {v}")
        total += v
    logger.info(f"  总计: {total}")

    if dry_run:
        logger.info("DRY RUN - 未写入数据库")
    else:
        # Log task
        db.log_task_run("migrate_archive_type", migration_report, f"迁移 {total} 篇文章的 archive_type")

    logger.info(f"\n明细 (前30条):")
    for d in detail[:30]:
        logger.info(d)
    if len(detail) > 30:
        logger.info(f"  ... 共 {len(detail)} 条")

    return migration_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="存量数据 archive_type 迁移")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
