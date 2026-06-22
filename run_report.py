#!/usr/bin/env python3
"""
日报/周报生成入口 — A/B 精选池 → 成卡撰写 → H5 渲染
用法: python run_report.py [--limit 35] [--skip-cards] [--daily]
"""

import argparse, logging, sys, webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.report_generator import generate_report
from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    config = load_config()

    parser = argparse.ArgumentParser(description="生成 H5 周报 (v3)")
    gate3_cfg = config.get("gates", {}).get("gate3", {})
    default_limit = gate3_cfg.get("daily_quota", 35)
    parser.add_argument("--limit", type=int, default=default_limit, help="最大文章数")
    parser.add_argument("--open", action="store_true", help="生成后自动打开")
    parser.add_argument("--skip-cards", action="store_true", help="跳过成卡撰写(使用已有 card_json)")
    parser.add_argument("--force-cards", action="store_true", help="强制重新生成全部卡片")
    parser.add_argument("--workers", type=int, default=1, help="并发线程数(默认1)")
    parser.add_argument("--daily", action="store_true", help="生成日报(默认周报)")
    parser.add_argument("--date", type=str, default="", help="指定日期 YYYY-MM-DD (仅日报模式)")
    args = parser.parse_args()

    db_path = config.get("database", {}).get("path", "data/content.db")
    db = Database(db_path)

    # Step 1: Card generation (unless skipped)
    editor_note = ""
    # Try reading editor_note from sidecar file
    editor_note = ""
    note_file = Path(config.get("report", {}).get("output_dir", "output")) / "editor_note.txt"
    if note_file.exists():
        editor_note = note_file.read_text(encoding="utf-8").strip()
        logger.info(f"读取本期看点: {editor_note[:60]}...")

    if not args.skip_cards:
        from run_generate_cards import run_card_generation
        logger.info("=== 第一步: 成卡撰写 ===")
        result = run_card_generation(limit=args.limit, dry_run=False, force=args.force_cards, workers=args.workers)
        if result:
            stats, editor_note, _ = result
            logger.info(f"成卡撰写完成: {stats}")
        else:
            logger.warning("成卡撰写返回空, 使用已有卡片继续")
    else:
        logger.info("跳过成卡撰写, 使用已有 card_json")

    # Step 2: Get articles for report
    articles = db.get_gate3_selected(limit=args.limit)
    if not articles:
        logger.warning("A/B 精选池为空, 尝试使用人工已选候选...")
        articles = db.get_approved_articles(limit=args.limit)

    if not articles:
        logger.error("数据库中没有候选文章")
        return

    # Merge gate fields for template compatibility
    for a in articles:
        a["tier"] = a.get("gate2_tier") or ""
        a["one_line"] = a.get("gate2_one_line") or ""
        a["rationale"] = a.get("gate3_rationale") or ""
        a["gate3_rank"] = a.get("gate3_rank") or 0

    report_label = "日报" if args.daily else "周报"
    logger.info(f"=== 第二步: H5 {report_label}渲染 ({len(articles)} 篇文章) ===")
    # Determine issue number for H5 feedback lookup
    issue_number = ""
    try:
        issues = db.get_all_issues()
        published = [i for i in issues if i.get("status") == "published"]
        if published:
            issue_number = str(published[-1].get("issue_number", ""))
    except:
        pass
    logger.info(f"使用 issue_number={issue_number} 渲染 H5")

    report_type = "daily" if args.daily else "weekly"
    output_path = generate_report(articles, config, editor_note=editor_note, issue_number=issue_number, report_type=report_type, report_date=args.date)

    if output_path:
        logger.info(f"✅ 周报已生成: {output_path}")
        if args.open:
            webbrowser.open(f"file://{Path(output_path).absolute()}")
    else:
        logger.error("周报生成失败")


if __name__ == "__main__":
    main()
