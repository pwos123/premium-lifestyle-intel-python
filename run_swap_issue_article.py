#!/usr/bin/env python3
"""Swap one article inside an existing issue and optionally regenerate its H5."""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import load_config
from src.database import Database
from src.report_generator import generate_report
from services.issue_builder import get_card_readiness


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_issue_ids(raw: str) -> list[int]:
    try:
        return [int(x) for x in json.loads(raw or "[]")]
    except Exception as exc:
        raise ValueError(f"issue.article_ids 不是有效 JSON: {exc}") from exc


def _backup_db(db_path: str, issue_id: int) -> str:
    src = Path(db_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = src.parent / f"content_before_issue{issue_id}_article_swap_{ts}.db"
    shutil.copy2(src, dst)
    return str(dst)


def swap_issue_article(
    issue_id: int,
    old_article_id: int,
    new_article_id: int,
    *,
    dry_run: bool = False,
    regenerate: bool = True,
    force_locked: bool = False,
) -> dict:
    config = load_config()
    db_path = config["database"]["path"]
    db = Database(db_path)
    backup_path = ""

    with _connect(db_path) as conn:
        issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if not issue:
            raise ValueError(f"issue 不存在: {issue_id}")
        if issue["locked_at"] and not force_locked:
            raise ValueError(f"issue {issue_id} 已锁定 locked_at={issue['locked_at']}，如确需修复请加 --force-locked")

        issue_ids = _load_issue_ids(issue["article_ids"])
        if old_article_id not in issue_ids:
            raise ValueError(f"old article #{old_article_id} 不在 issue {issue_id} 的 article_ids 中")
        if new_article_id in issue_ids and new_article_id != old_article_id:
            raise ValueError(f"new article #{new_article_id} 已在 issue {issue_id} 中")

        old_article = conn.execute("SELECT * FROM articles WHERE id=?", (old_article_id,)).fetchone()
        new_article = conn.execute("SELECT * FROM articles WHERE id=?", (new_article_id,)).fetchone()
        if not old_article:
            raise ValueError(f"old article 不存在: {old_article_id}")
        if not new_article:
            raise ValueError(f"new article 不存在: {new_article_id}")
        readiness = get_card_readiness(dict(new_article))
        if not readiness.get("ready"):
            raise ValueError(
                "new article #{} 未达到入刊成卡状态: {} / {}".format(
                    new_article_id,
                    readiness.get("label") or readiness.get("status"),
                    readiness.get("reason") or readiness.get("reason_code") or "",
                )
            )

        sort_order = issue_ids.index(old_article_id)
        next_ids = [new_article_id if aid == old_article_id else aid for aid in issue_ids]

        result = {
            "issue_id": issue_id,
            "issue_number": issue["issue_number"],
            "old_article_id": old_article_id,
            "new_article_id": new_article_id,
            "sort_order": sort_order,
            "old_title": old_article["translated_title"] or old_article["title"],
            "new_title": new_article["translated_title"] or new_article["title"],
            "will_regenerate": regenerate,
            "dry_run": dry_run,
        }

        if dry_run:
            result["article_ids_window"] = next_ids[max(sort_order - 1, 0):sort_order + 2]
            return result

        backup_path = _backup_db(db_path, issue_id)
        now = datetime.now().isoformat()
        with conn:
            conn.execute("UPDATE issues SET article_ids=? WHERE id=?", (json.dumps(next_ids), issue_id))
            conn.execute(
                """UPDATE articles
                   SET status='candidate', issue_id=NULL, issue_sort_order=NULL, reviewed_at=?
                   WHERE id=?""",
                (now, old_article_id),
            )
            conn.execute(
                """UPDATE articles
                   SET status='in_issue', issue_id=?, issue_sort_order=?, reviewed_at=?,
                       archive_reason=NULL, archive_reason_at=NULL
                   WHERE id=?""",
                (issue_id, sort_order, now, new_article_id),
            )

    output_path = ""
    if regenerate:
        issue = db.get_issue(issue_id)
        articles = db.get_issue_articles(issue_id)
        output_path = generate_report(
            articles,
            config,
            issue_number=issue.get("issue_number", ""),
            report_type=issue.get("report_type") or "daily",
            report_date=issue.get("report_date") or "",
            editor_note=issue.get("editor_note") or "",
        )
        db.update_issue(issue_id, {"html_path": output_path})

    result["backup_path"] = backup_path
    result["output_path"] = output_path
    return result


def main():
    parser = argparse.ArgumentParser(description="替换已存在 issue 中的一张卡")
    parser.add_argument("--issue-id", type=int, required=True)
    parser.add_argument("--old-article-id", type=int, required=True)
    parser.add_argument("--new-article-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-regenerate", action="store_true", help="只换绑 DB，不重生 H5")
    parser.add_argument("--force-locked", action="store_true", help="允许修复 locked issue")
    args = parser.parse_args()
    result = swap_issue_article(
        args.issue_id,
        args.old_article_id,
        args.new_article_id,
        dry_run=args.dry_run,
        regenerate=not args.no_regenerate,
        force_locked=args.force_locked,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
