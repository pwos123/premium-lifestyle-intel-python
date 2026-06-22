"""
SQLite 数据库模型与 CRUD 操作
"""

import json
import sqlite3
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    translated_title TEXT,
    translated_content TEXT,
    source TEXT,
    content TEXT,
    summary TEXT,
    images TEXT DEFAULT '[]',
    category TEXT,
    score INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    recommend_reason TEXT,
    scenario TEXT,
    pros TEXT DEFAULT '[]',
    cons TEXT DEFAULT '[]',
    recommend_level TEXT DEFAULT '了解',
    is_relevant INTEGER DEFAULT 1,
    model_votes TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    reviewed_at DATETIME,
    carryover_count INTEGER DEFAULT 0,
    evergreen INTEGER DEFAULT 0,
    issue_id INTEGER,
    dj_feedback TEXT,
    expiry_date TEXT,
    issue_sort_order INTEGER
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start DATE,
    week_end DATE,
    html_path TEXT,
    article_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number TEXT NOT NULL UNIQUE,
    created_date DATE NOT NULL,
    status TEXT DEFAULT 'draft',
    html_path TEXT,
    article_ids TEXT DEFAULT '[]',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    published_at DATETIME
);

CREATE TABLE IF NOT EXISTS task_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_name TEXT NOT NULL,
    run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    stats TEXT DEFAULT '{}',
    summary TEXT
);

CREATE TABLE IF NOT EXISTS issue_article_replacements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    old_article_id INTEGER NOT NULL,
    new_article_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    replaced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(score);
CREATE INDEX IF NOT EXISTS idx_articles_crawled_at ON articles(crawled_at);
"""


class Database:
    def __init__(self, db_path: str = "data/content.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(DB_SCHEMA)
            self._migrate(conn)
            self._normalize_voided_issue_numbers(conn)
            # Create indexes for new columns (safe to run after migration)
            for idx_sql in [
                'CREATE INDEX IF NOT EXISTS idx_articles_issue_id ON articles(issue_id)',
                'CREATE INDEX IF NOT EXISTS idx_articles_evergreen ON articles(evergreen)',
                'CREATE INDEX IF NOT EXISTS idx_articles_carryover_count ON articles(carryover_count)',
            ]:
                try:
                    conn.execute(idx_sql)
                except:
                    pass
            logger.info(f"数据库初始化完成: {self.db_path}")

    @staticmethod
    def _migrate(conn: sqlite3.Connection):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
        if "translated_title" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN translated_title TEXT")
        if "translated_content" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN translated_content TEXT")
        if "is_relevant" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN is_relevant INTEGER DEFAULT 1")
        # 三关打分字段
        _gate_fields = [
            ("gate1_verdict", "TEXT"), ("gate1_failed_checks", "TEXT DEFAULT '[]'"),
            ("gate1_needs_human", "INTEGER DEFAULT 0"), ("gate1_checked_at", "DATETIME"),
            ("gate2_tier", "TEXT"), ("gate2_veto", "TEXT"),
            ("gate2_dim_excitement", "INTEGER"), ("gate2_dim_feasibility", "INTEGER"),
            ("gate2_dim_density", "INTEGER"), ("gate2_fit_reasons", "TEXT DEFAULT '[]'"),
            ("gate2_one_line", "TEXT"), ("gate2_checked_at", "DATETIME"),
            ("gate2_status", "TEXT DEFAULT 'pending'"),
            ("gate2_error", "TEXT"),
            ("gate2_attempt_count", "INTEGER DEFAULT 0"),
            ("gate3_rank", "INTEGER"), ("gate3_rationale", "TEXT"),
            ("gate3_group", "TEXT"), ("gate3_selected", "INTEGER DEFAULT 0"),
            ("gate3_status", "TEXT"), ("gate3_checked_at", "DATETIME"),
            ("veto_hit", "INTEGER DEFAULT 0"), ("veto_rule", "TEXT"),
            ("fit_keywords_hit", "TEXT"), ("pending_human", "INTEGER DEFAULT 0"),
            ("archive_reason", "TEXT"), ("archive_reason_at", "DATETIME"),
            ("carryover_count", "INTEGER DEFAULT 0"), ("evergreen", "INTEGER DEFAULT 0"),
            ("issue_id", "INTEGER"), ("dj_feedback", "TEXT"),
            ("expiry_date", "TEXT"), ("issue_sort_order", "INTEGER"),
            ("archive_type", "TEXT"), ("regroup_count", "INTEGER DEFAULT 0"),
            ("summary_flagged", "INTEGER DEFAULT 0"),
            ("feedback_detail", "TEXT"),
            ("card_json", "TEXT"),
            ("facts_used", "TEXT DEFAULT '[]'"),
            ("card_status", "TEXT DEFAULT 'none'"),
            ("card_review_reason", "TEXT"),
            ("card_updated_at", "DATETIME"),
            ("card_attempt_count", "INTEGER DEFAULT 0"),
        ]
        for _col, _typ in _gate_fields:
            if _col not in columns:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {_col} {_typ}")

        # issues 表迁移: report_type / report_date / editor_note (日刊专用)
        issue_cols = {row[1] for row in conn.execute("PRAGMA table_info(issues)").fetchall()}
        _issue_fields = [
            ("report_type", "TEXT DEFAULT 'daily'"),
            ("report_date", "TEXT"),
            ("editor_note", "TEXT DEFAULT ''"),
            ("locked_at", "TEXT"),
        ]
        for _col, _typ in _issue_fields:
            if _col not in issue_cols:
                conn.execute(f"ALTER TABLE issues ADD COLUMN {_col} {_typ}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS issue_article_replacements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                old_article_id INTEGER NOT NULL,
                new_article_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                replaced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # --- 文章 CRUD ---

    def insert_article(self, article: dict) -> Optional[int]:
        """插入文章，返回 ID；URL 重复则返回 None"""
        if "url" in article:
            article["url"] = _normalize_url(article["url"])
        # 序列化 JSON 字段
        for field in ("images", "tags", "pros", "cons", "model_votes"):
            if field in article and not isinstance(article[field], str):
                article[field] = json.dumps(article[field], ensure_ascii=False)

        columns = ", ".join(article.keys())
        placeholders = ", ".join(["?"] * len(article))
        sql = f"INSERT OR IGNORE INTO articles ({columns}) VALUES ({placeholders})"
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(sql, list(article.values()))
                if cursor.rowcount > 0:
                    return cursor.lastrowid
                return None
        except Exception as e:
            logger.error(f"插入文章失败: {e}")
            return None

    def update_article(self, article_id: int, updates: dict):
        """更新文章字段"""
        for field in ("images", "tags", "pros", "cons", "model_votes", "gate1_failed_checks", "gate2_fit_reasons", "fit_keywords_hit"):
            if field in updates and not isinstance(updates[field], str):
                updates[field] = json.dumps(updates[field], ensure_ascii=False)

        set_clause = ", ".join([f"{k} = ?" for k in updates])
        sql = f"UPDATE articles SET {set_clause} WHERE id = ?"
        values = list(updates.values()) + [article_id]
        try:
            with self._get_conn() as conn:
                conn.execute(sql, values)
        except Exception as e:
            logger.error(f"更新文章失败: {e}")
            raise

    def get_article(self, article_id: int) -> Optional[dict]:
        """获取单篇文章"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
            return self._row_to_dict(row) if row else None

    def get_article_by_url(self, url: str) -> Optional[dict]:
        """通过 URL 获取文章"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM articles WHERE url = ?", (url,)).fetchone()
            return self._row_to_dict(row) if row else None

    def get_pending_articles(self, limit: int = 50) -> list[dict]:
        """获取待审核文章，按评分降序"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM articles WHERE status = 'pending' ORDER BY score DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_approved_articles(self, limit: int = 30) -> list[dict]:
        """获取周报候选文章，兼容旧状态 approved"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE status IN ('candidate', 'approved')
                     AND COALESCE(is_relevant, 1) = 1
                   ORDER BY score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_articles_for_review(self, limit: int = 30) -> list[dict]:
        """获取 top N 待审核文章"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE status = 'pending' AND score >= 60 AND COALESCE(is_relevant, 1) = 1
                   ORDER BY score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def review_article(self, article_id: int, status: str, archive_reason: str = None):
        """审核文章 (candidate / approved / rejected)
        rejected 时根据 archive_reason 自动设置 archive_type
        sunk 文章提升为 candidate 时清除沉库标记"""
        if status == "approved":
            status = "candidate"
        # 沉库 -> 候选: 清除沉库状态
        if status == "candidate":
            with self._get_conn() as conn:
                row = conn.execute("SELECT status FROM articles WHERE id=?", (article_id,)).fetchone()
                if row and row["status"] == "sunk":
                    conn.execute(
                        "UPDATE articles SET status='candidate', evergreen=0, archive_reason=NULL, archive_type=NULL, archive_reason_at=NULL, pending_human=0, summary_flagged=0, gate3_status=NULL, reviewed_at=? WHERE id=?",
                        (datetime.now().isoformat(), article_id)
                    )
                    return
        if archive_reason and status == "rejected":
            archive_type = _archive_type_for_reason(archive_reason)
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE articles SET status = ?, reviewed_at = ?, archive_reason = ?, archive_reason_at = ?, archive_type = ?, pending_human = 0, summary_flagged = 0, gate3_status = NULL WHERE id = ?",
                    (status, datetime.now().isoformat(), archive_reason, datetime.now().isoformat(), archive_type, article_id),
                )
        else:
            with self._get_conn() as conn:
                evergreen_sql = ", evergreen = 0" if status == "candidate" else ""
                conn.execute(
                    f"UPDATE articles SET status = ?, reviewed_at = ?, pending_human = 0, summary_flagged = 0, gate3_status = NULL{evergreen_sql} WHERE id = ?",
                    (status, datetime.now().isoformat(), article_id),
                )

    def batch_review(self, article_ids: list[int], status: str, archive_reason: str = None):
        """批量审核"""
        if not article_ids:
            return 0
        if status == "approved":
            status = "candidate"
        placeholders = ",".join(["?"] * len(article_ids))
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            if status == "rejected" and archive_reason:
                archive_type = _archive_type_for_reason(archive_reason)
                cursor = conn.execute(
                    f"""UPDATE articles
                           SET status = ?, reviewed_at = ?, archive_reason = ?,
                               archive_reason_at = ?, archive_type = ?,
                               pending_human = 0, summary_flagged = 0, gate3_status = NULL
                         WHERE id IN ({placeholders})""",
                    [status, now, archive_reason, now, archive_type] + article_ids,
                )
            else:
                evergreen_sql = ", evergreen = 0" if status == "candidate" else ""
                cursor = conn.execute(
                    f"UPDATE articles SET status = ?, reviewed_at = ?, pending_human = 0, summary_flagged = 0, gate3_status = NULL{evergreen_sql} WHERE id IN ({placeholders})",
                    [status, now] + article_ids,
                )
            return cursor.rowcount

    def batch_move_to_pending(self, article_ids: list[int]) -> int:
        """将未入刊候选批量移回待筛选池。"""
        if not article_ids:
            return 0
        placeholders = ",".join(["?"] * len(article_ids))
        with self._get_conn() as conn:
            cursor = conn.execute(
                f"""UPDATE articles
                       SET status='pending', reviewed_at=NULL, issue_id=NULL, issue_sort_order=NULL
                     WHERE id IN ({placeholders})
                       AND status IN ('candidate','approved')
                       AND issue_id IS NULL""",
                article_ids,
            )
            return cursor.rowcount

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            pending = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE gate2_tier='C'
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0"""
            ).fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM articles WHERE status='approved'").fetchone()[0]
            candidate = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE status IN ('candidate','approved')
                     AND COALESCE(evergreen,0)=0"""
            ).fetchone()[0]
            in_issue = conn.execute("SELECT COUNT(*) FROM articles WHERE status='in_issue'").fetchone()[0]
            published = conn.execute("SELECT COUNT(*) FROM articles WHERE status='published'").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM articles WHERE status='rejected'").fetchone()[0]
            pending_human = conn.execute("SELECT COUNT(*) FROM articles WHERE (pending_human=1 OR summary_flagged=1) AND status NOT IN ('rejected','sunk','in_issue','published')").fetchone()[0]
            dj_checked = conn.execute("SELECT COUNT(*) FROM articles WHERE dj_feedback='checked'").fetchone()[0]
            featured = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE gate2_tier IN ('A','B')
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0"""
            ).fetchone()[0]
            selectable = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE gate2_tier IN ('A','B','C')
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0"""
            ).fetchone()[0]
            evergreen = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE evergreen=1
                     AND status IN ('pending','candidate','approved')
                     AND issue_id IS NULL
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0"""
            ).fetchone()[0]
            irrelevant = conn.execute("SELECT COUNT(*) FROM articles WHERE COALESCE(is_relevant, 1)=0").fetchone()[0]
            issues = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE status='published' AND COALESCE(html_path,'') != ''"
            ).fetchone()[0]
            # 双轨计数
            archived_count = conn.execute("SELECT COUNT(*) FROM articles WHERE status='rejected' AND archive_type='archived'").fetchone()[0]
            sunk_count = conn.execute("SELECT COUNT(*) FROM articles WHERE status='sunk'").fetchone()[0]
            sunk_7d = conn.execute("SELECT COUNT(*) FROM articles WHERE status='sunk' AND archive_reason_at >= datetime('now', '-7 days')").fetchone()[0]
            return {
                "total": total,
                "pending": pending,
                "approved": approved,
                "candidate": candidate,
                "in_issue": in_issue,
                "published": published,
                "rejected": rejected,
                "pending_human": pending_human,
                "evergreen": evergreen,
                "dj_checked": dj_checked,
                "featured": featured,
                "selectable": selectable,
                "irrelevant": irrelevant,
                "issues": issues,
                "archived_count": archived_count,
                "sunk_count": sunk_count,
                "sunk_7d": sunk_7d,
            }

    def get_category_counts(self) -> dict:
        """获取仪表盘各分类可筛选文章数量（A/B/C 三档）。"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT category, COUNT(*) as cnt FROM articles
                   WHERE gate2_tier IN ('A','B','C')
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                   GROUP BY category"""
            ).fetchall()
            return {(row["category"] or "未分类"): row["cnt"] for row in rows}


    # --- 三关查询 ---

    def get_gate1_candidates(self, limit: int = 600) -> list[dict]:
        """获取待过第一关的文章"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM articles WHERE gate1_verdict IS NULL AND status='pending' ORDER BY crawled_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def count_gate1_candidates(self) -> int:
        """Count articles still waiting for Gate1."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM articles WHERE gate1_verdict IS NULL AND status='pending'"
            ).fetchone()[0]

    def get_gate2_candidates(self, limit: int = 300) -> list[dict]:
        """获取gate1=pass且通过否决检查,待过第二关的文章"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE gate1_verdict='pass'
                     AND (veto_hit IS NULL OR veto_hit=0)
                     AND gate2_tier IS NULL
                     AND COALESCE(gate2_status,'pending') != 'error'
                     AND status NOT IN ('rejected','published')
                   ORDER BY crawled_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def count_gate2_candidates(self) -> int:
        """Count articles still waiting for Gate2."""
        with self._get_conn() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE gate1_verdict='pass'
                     AND (veto_hit IS NULL OR veto_hit=0)
                     AND gate2_tier IS NULL
                     AND COALESCE(gate2_status,'pending') != 'error'
                     AND status NOT IN ('rejected','published')"""
            ).fetchone()[0]

    def get_gate2_error_candidates(self, limit: int = 50, max_attempts: int = 3) -> list[dict]:
        """获取 Gate2 解析/调用失败且可显式重试的文章。"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE gate1_verdict='pass'
                     AND (veto_hit IS NULL OR veto_hit=0)
                     AND gate2_tier IS NULL
                     AND COALESCE(gate2_status,'pending')='error'
                     AND COALESCE(gate2_attempt_count,0) < ?
                     AND status NOT IN ('rejected','published')
                   ORDER BY gate2_checked_at ASC, crawled_at DESC
                   LIMIT ?""",
                (max_attempts, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_gate3_candidates(self, limit: int = 100) -> list[dict]:
        """获取A/B档待过第三关的文章(排除待人工复核)"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE gate2_tier IN ('A','B')
                     AND gate3_selected=0
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                     AND status NOT IN ('rejected','published','sunk')
                   ORDER BY gate2_tier, crawled_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_gate3_selected(self, limit: int = 35) -> list[dict]:
        """获取精选待筛选文章.

        Gate3 已停用，精选池直接使用 A/B 档待筛选文章。
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE gate2_tier IN ('A','B')
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                   ORDER BY
                     CASE gate2_tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
                     gate2_checked_at DESC,
                     score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_articles_by_ids(self, article_ids: list[int]) -> list[dict]:
        """按传入顺序获取指定文章。"""
        if not article_ids:
            return []
        with self._get_conn() as conn:
            placeholders = ",".join(["?"] * len(article_ids))
            rows = conn.execute(
                f"SELECT * FROM articles WHERE id IN ({placeholders})",
                article_ids,
            ).fetchall()
            aid_to_article = {r["id"]: self._row_to_dict(r) for r in rows}
            return [aid_to_article[aid] for aid in article_ids if aid in aid_to_article]

    def get_archive_reason_stats(self, exclude_sunk: bool = True) -> dict:
        """获取近30天归档理由统计 + AI误判率
        exclude_sunk=True 时排除沉库，只统计终点站（已归档）
        """
        with self._get_conn() as conn:
            # 沉库 status 已独立为 'sunk'，不再混在 rejected 中

            # 归档理由分布(近30天)
            rows = conn.execute(
                """SELECT archive_reason, COUNT(*) as cnt FROM articles
                   WHERE status='rejected'
                     AND archive_reason IS NOT NULL AND archive_reason != ''
                     AND archive_reason_at >= datetime('now', '-30 days')
                     
                   GROUP BY archive_reason ORDER BY cnt DESC"""
            ).fetchall()
            reason_dist = {row["archive_reason"]: row["cnt"] for row in rows}

            # AI误判率: A/B档被人工归档的总数(近30天)
            misclassify = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE status='rejected'
                     AND gate2_tier IN ('A','B')
                     AND archive_reason_at >= datetime('now', '-30 days')"""
            ).fetchone()[0]

            # 总归档数(近30天)
            total_archived = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE status='rejected'
                     AND archive_reason_at >= datetime('now', '-30 days')"""
            ).fetchone()[0]

            # 沉库规模指标
            sunk_total = conn.execute("SELECT COUNT(*) FROM articles WHERE status='rejected' AND archive_type='sunk'").fetchone()[0]
            sunk_7d = conn.execute("SELECT COUNT(*) FROM articles WHERE status='sunk' AND archive_reason_at >= datetime('now', '-7 days')").fetchone()[0]

            return {
                "reason_distribution": reason_dist,
                "ai_misclassify_count": misclassify,
                "total_archived_30d": total_archived,
                "sunk_total": sunk_total,
                "sunk_7d": sunk_7d,
            }

    def get_gate_stats(self) -> dict:
        """获取三关漏斗统计"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM articles WHERE status='pending'").fetchone()[0]
            g1_pass = conn.execute("SELECT COUNT(*) FROM articles WHERE gate1_verdict='pass'").fetchone()[0]
            g1_fail = conn.execute("SELECT COUNT(*) FROM articles WHERE gate1_verdict='fail'").fetchone()[0]
            g1_human = conn.execute("SELECT COUNT(*) FROM articles WHERE gate1_needs_human=1").fetchone()[0]
            g2_a = conn.execute("SELECT COUNT(*) FROM articles WHERE gate2_tier='A'").fetchone()[0]
            g2_b = conn.execute("SELECT COUNT(*) FROM articles WHERE gate2_tier='B'").fetchone()[0]
            g2_c = conn.execute("SELECT COUNT(*) FROM articles WHERE gate2_tier='C'").fetchone()[0]
            g2_d = conn.execute("SELECT COUNT(*) FROM articles WHERE gate2_tier='D'").fetchone()[0]
            g3_sel = conn.execute(
                """SELECT COUNT(*) FROM articles
                   WHERE gate2_tier IN ('A','B')
                     AND status='pending'
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0"""
            ).fetchone()[0]
            return {
                "total_pending": total, "gate1_pass": g1_pass, "gate1_fail": g1_fail,
                "gate1_needs_human": g1_human,
                "gate2_A": g2_a, "gate2_B": g2_b, "gate2_C": g2_c, "gate2_D": g2_d,
                "gate3_selected": g3_sel,
            }

    def set_gate1_result(self, article_id: int, verdict: str, failed_checks: list, needs_human: bool):
        self.update_article(article_id, {
            "gate1_verdict": verdict, "gate1_failed_checks": json.dumps(failed_checks, ensure_ascii=False) if not isinstance(failed_checks, str) else failed_checks,
            "gate1_needs_human": 1 if needs_human else 0,
            "gate1_checked_at": __import__("datetime").datetime.now().isoformat(),
        })

    def set_gate2_result(self, article_id: int, tier: str, veto: str, dims: tuple, fit_reasons: list, one_line: str):
        attempts = int((self.get_article(article_id) or {}).get("gate2_attempt_count") or 0) + 1
        self.update_article(article_id, {
            "gate2_tier": tier, "gate2_veto": veto,
            "gate2_dim_excitement": dims[0], "gate2_dim_feasibility": dims[1], "gate2_dim_density": dims[2],
            "gate2_fit_reasons": json.dumps(fit_reasons, ensure_ascii=False) if not isinstance(fit_reasons, str) else fit_reasons, "gate2_one_line": one_line,
            "gate2_checked_at": __import__("datetime").datetime.now().isoformat(),
            "gate2_status": "done",
            "gate2_error": None,
            "gate2_attempt_count": attempts,
        })

    def set_gate2_error(self, article_id: int, error: str):
        attempts = int((self.get_article(article_id) or {}).get("gate2_attempt_count") or 0) + 1
        self.update_article(article_id, {
            "gate2_status": "error",
            "gate2_error": (error or "")[:500],
            "gate2_checked_at": __import__("datetime").datetime.now().isoformat(),
            "gate2_attempt_count": attempts,
        })

    def set_gate3_result(self, article_id: int, rank: int, rationale: str, group: str, selected: bool, status: str):
        updates = {
            "gate3_rank": rank, "gate3_rationale": rationale, "gate3_group": group,
            "gate3_selected": 1 if selected else 0, "gate3_status": status,
            "gate3_checked_at": __import__("datetime").datetime.now().isoformat(),
        }
        # gate3 选中不改变 status — 周报候选由人工操作，不在 gate3 自动入池
        self.update_article(article_id, updates)


    # --- 报告 CRUD ---

    def insert_report(self, week_start, week_end, html_path: str, article_count: int) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO reports (week_start, week_end, html_path, article_count) VALUES (?, ?, ?, ?)",
                (week_start, week_end, html_path, article_count),
            )
            return cursor.lastrowid

    # --- 工具方法 ---

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        # 反序列化 JSON 字段
        for field in ("images", "tags", "pros", "cons", "model_votes", "gate1_failed_checks", "gate2_fit_reasons", "fit_keywords_hit"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        if "evergreen" in d and d["evergreen"] is not None:
            d["evergreen"] = bool(d["evergreen"])
        return d


    # --- Issue CRUD ---

    def create_issue(self, issue_number: str, created_date: str, article_ids: list[int]) -> int:
        with self._get_conn() as conn:
            self._normalize_voided_issue_numbers(conn)
            try:
                cursor = conn.execute(
                    "INSERT INTO issues (issue_number, created_date, status, article_ids) VALUES (?, ?, 'draft', ?)",
                    (issue_number, created_date, json.dumps(article_ids)),
                )
            except sqlite3.IntegrityError:
                self._normalize_voided_issue_numbers(conn)
                cursor = conn.execute(
                    "INSERT INTO issues (issue_number, created_date, status, article_ids) VALUES (?, ?, 'draft', ?)",
                    (issue_number, created_date, json.dumps(article_ids)),
                )
            return cursor.lastrowid


    def get_issue_by_number(self, issue_number: str) -> Optional[dict]:
        """Get issue by issue_number string. Returns None for voided issues."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM issues WHERE issue_number = ?", (issue_number,)).fetchone()
            if row:
                d = self._row_to_dict(row)
                if d.get("status") == "voided":
                    return None
                d["article_ids"] = json.loads(d.get("article_ids", "[]"))
                return d
            return None

    def get_issue(self, issue_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            if isinstance(d.get("article_ids"), str):
                try:
                    d["article_ids"] = json.loads(d["article_ids"])
                except:
                    d["article_ids"] = []
            return d

    def get_next_issue_number(self) -> int:
        """获取下一个可用期刊序号。已作废期不占号, 优先复用最小空号。"""
        with self._get_conn() as conn:
            self._normalize_voided_issue_numbers(conn)
            rows = conn.execute(
                "SELECT issue_number FROM issues WHERE status!='voided' AND issue_number GLOB '[0-9]*' AND issue_number NOT LIKE '%-%'"
            ).fetchall()
            used = set()
            for row in rows:
                try:
                    used.add(int(row["issue_number"]))
                except (TypeError, ValueError):
                    pass
            next_num = 1
            while next_num in used:
                next_num += 1
            return next_num

    def get_display_number(self, issue_number: str = "", report_date: str = "") -> int:
        """按已发布刊计数: 在 status='published' 的刊中按日期升序, 本期排第几。
        issue_number 用于查本期日期; report_date 为后备(新刊未入库时)。
        返回值 >= 1。voided 刊不计入。"""
        with self._get_conn() as conn:
            # 确定本期的参考日期
            ref_date = None
            if issue_number:
                row = conn.execute(
                    "SELECT COALESCE(report_date, created_date) as ref_date FROM issues WHERE issue_number=?",
                    (issue_number,)
                ).fetchone()
                if row:
                    ref_date = row["ref_date"]
            if not ref_date and report_date:
                ref_date = report_date
            if not ref_date:
                from datetime import datetime
                ref_date = datetime.now().strftime("%Y-%m-%d")

            # 统计 published 且非 voided、日期 <= ref_date 的刊数
            count = conn.execute(
                "SELECT COUNT(*) FROM issues WHERE status='published' AND status!='voided' AND COALESCE(report_date, created_date) <= ?",
                (ref_date,)
            ).fetchone()[0]
            return max(count, 1)

    def get_all_issues(self) -> list[dict]:
        with self._get_conn() as conn:
            self._normalize_voided_issue_numbers(conn)
            rows = conn.execute(
                """SELECT * FROM issues
                   WHERE status != 'voided'
                   ORDER BY
                     CASE WHEN issue_number GLOB '[0-9]*' AND issue_number NOT LIKE '%-%'
                          THEN CAST(issue_number AS INTEGER) ELSE 0 END DESC,
                     COALESCE(published_at, created_at, created_date) DESC,
                     id DESC"""
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("article_ids"), str):
                    try:
                        d["article_ids"] = json.loads(d["article_ids"])
                    except:
                        d["article_ids"] = []
                # Count articles
                d["article_count"] = len(d["article_ids"])
                result.append(d)
            return result

    def update_issue(self, issue_id: int, updates: dict):
        if "article_ids" in updates and not isinstance(updates["article_ids"], str):
            updates["article_ids"] = json.dumps(updates["article_ids"])
        set_clause = ", ".join([f"{k} = ?" for k in updates])
        sql = f"UPDATE issues SET {set_clause} WHERE id = ?"
        values = list(updates.values()) + [issue_id]
        with self._get_conn() as conn:
            conn.execute(sql, values)

    def fail_issue_release_articles(self, issue_id: int, status: str = "pending") -> int:
        """Mark a failed issue and release articles without clearing review flags."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute("UPDATE issues SET status='failed' WHERE id=?", (issue_id,))
            cursor = conn.execute(
                """UPDATE articles
                   SET status=?,
                       issue_id=NULL,
                       issue_sort_order=NULL,
                       reviewed_at=?
                   WHERE issue_id=?""",
                (status, now, issue_id),
            )
            return cursor.rowcount

    def keep_issue_articles_release_rest(self, issue_id: int, keep_ids: list[int], status: str = "pending") -> int:
        """Keep only renderable articles in an issue and release the rest atomically."""
        now = datetime.now().isoformat()
        keep_ids = [int(aid) for aid in keep_ids]
        with self._get_conn() as conn:
            row = conn.execute("SELECT article_ids FROM issues WHERE id=?", (issue_id,)).fetchone()
            if not row:
                raise ValueError("期刊不存在")

            try:
                original_ids = [int(aid) for aid in json.loads(row["article_ids"] or "[]")]
            except Exception:
                original_ids = []
            keep_set = set(keep_ids)
            ordered_keep_ids = [aid for aid in original_ids if aid in keep_set]
            if not ordered_keep_ids and keep_ids:
                ordered_keep_ids = keep_ids

            conn.execute(
                "UPDATE issues SET article_ids=? WHERE id=?",
                (json.dumps(ordered_keep_ids), issue_id),
            )

            if ordered_keep_ids:
                placeholders = ",".join(["?"] * len(ordered_keep_ids))
                cursor = conn.execute(
                    f"""UPDATE articles
                        SET status=?,
                            issue_id=NULL,
                            issue_sort_order=NULL,
                            reviewed_at=?
                        WHERE issue_id=?
                          AND id NOT IN ({placeholders})""",
                    [status, now, issue_id] + ordered_keep_ids,
                )
            else:
                cursor = conn.execute(
                    """UPDATE articles
                       SET status=?,
                           issue_id=NULL,
                           issue_sort_order=NULL,
                           reviewed_at=?
                       WHERE issue_id=?""",
                    (status, now, issue_id),
                )

            for idx, aid in enumerate(ordered_keep_ids):
                conn.execute(
                    "UPDATE articles SET status='in_issue', issue_id=?, issue_sort_order=? WHERE id=?",
                    (issue_id, idx, aid),
                )
            return cursor.rowcount

    def replace_issue_article(
        self,
        issue_id: int,
        old_article_id: int,
        new_article_id: int,
        *,
        old_status: str = "candidate",
        reason: str = "",
    ) -> dict:
        """Replace one article in an issue, preserving the original position."""
        if old_status not in ("candidate", "pending", "rejected"):
            raise ValueError("old_status 必须是 candidate/pending/rejected")
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
            if not issue:
                raise ValueError("期刊不存在")
            try:
                issue_ids = [int(aid) for aid in json.loads(issue["article_ids"] or "[]")]
            except Exception as exc:
                raise ValueError(f"期刊 article_ids 格式错误: {exc}") from exc
            if old_article_id not in issue_ids:
                raise ValueError("旧文章不在此期刊中")
            if new_article_id in issue_ids and new_article_id != old_article_id:
                raise ValueError("新文章已在此期刊中")

            old_article = conn.execute("SELECT * FROM articles WHERE id=?", (old_article_id,)).fetchone()
            new_article = conn.execute("SELECT * FROM articles WHERE id=?", (new_article_id,)).fetchone()
            if not old_article:
                raise ValueError("旧文章不存在")
            if not new_article:
                raise ValueError("新文章不存在")
            if new_article["issue_id"] and int(new_article["issue_id"]) != issue_id:
                raise ValueError(f"新文章已在期刊#{new_article['issue_id']}中")

            position = issue_ids.index(old_article_id)
            next_ids = [new_article_id if aid == old_article_id else aid for aid in issue_ids]

            conn.execute(
                "UPDATE issues SET article_ids=? WHERE id=?",
                (json.dumps(next_ids), issue_id),
            )
            if old_status == "rejected":
                conn.execute(
                    """UPDATE articles
                       SET status='rejected',
                           issue_id=NULL,
                           issue_sort_order=NULL,
                           reviewed_at=?,
                           archive_reason=?,
                           archive_reason_at=?,
                           archive_type='archived'
                       WHERE id=?""",
                    (now, reason or "期刊内替换移出", now, old_article_id),
                )
            else:
                conn.execute(
                    """UPDATE articles
                       SET status=?,
                           issue_id=NULL,
                           issue_sort_order=NULL,
                           reviewed_at=?
                       WHERE id=?""",
                    (old_status, now, old_article_id),
                )
            conn.execute(
                """UPDATE articles
                   SET status='in_issue',
                       issue_id=?,
                       issue_sort_order=?,
                       reviewed_at=?,
                       evergreen=0,
                       pending_human=0,
                       summary_flagged=0,
                       gate3_status=NULL,
                       archive_reason=NULL,
                       archive_reason_at=NULL,
                       archive_type=NULL
                   WHERE id=?""",
                (issue_id, position, now, new_article_id),
            )
            conn.execute(
                """INSERT INTO issue_article_replacements
                   (issue_id, old_article_id, new_article_id, position, reason, replaced_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (issue_id, old_article_id, new_article_id, position, reason or "", now),
            )
            return {
                "issue_id": issue_id,
                "old_article_id": old_article_id,
                "new_article_id": new_article_id,
                "position": position,
                "article_ids": next_ids,
                "old_title": old_article["translated_title"] or old_article["title"] or "",
                "new_title": new_article["translated_title"] or new_article["title"] or "",
            }

    @staticmethod
    def _make_voided_issue_number(conn: sqlite3.Connection, issue_number: str, issue_id: int) -> str:
        base = str(issue_number or issue_id)
        if "-voided-" in base:
            base = base.split("-voided-", 1)[0]
        candidate = f"{base}-voided-{issue_id}"
        suffix = 2
        while conn.execute(
            "SELECT 1 FROM issues WHERE issue_number=? AND id!=?",
            (candidate, issue_id)
        ).fetchone():
            candidate = f"{base}-voided-{issue_id}-{suffix}"
            suffix += 1
        return candidate

    @classmethod
    def _normalize_voided_issue_numbers(cls, conn: sqlite3.Connection):
        """Release public numeric issue numbers held by voided rows.

        issue_number is UNIQUE, so a voided issue cannot keep "4" if the next
        valid issue should reuse public issue number 4.
        """
        rows = conn.execute(
            """SELECT id, issue_number FROM issues
               WHERE status='voided'
                 AND issue_number GLOB '[0-9]*'
                 AND issue_number NOT LIKE '%-%'"""
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE issues SET issue_number=? WHERE id=?",
                (cls._make_voided_issue_number(conn, row["issue_number"], row["id"]), row["id"])
            )

    def void_issue(self, issue_id: int) -> dict:
        """Void an issue atomically and return its articles to the candidate pool."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
            if not issue:
                raise ValueError("期刊不存在")

            self._normalize_voided_issue_numbers(conn)

            if issue["status"] == "voided":
                return {
                    "issue_id": issue_id,
                    "count": 0,
                    "article_ids": [],
                    "issue_number": issue["issue_number"],
                    "voided_number": issue["issue_number"],
                    "already_voided": True,
                }

            article_rows = conn.execute("SELECT id FROM articles WHERE issue_id=?", (issue_id,)).fetchall()
            article_ids = [r["id"] for r in article_rows]
            cursor = conn.execute(
                """UPDATE articles
                   SET status='candidate',
                       issue_id=NULL,
                       issue_sort_order=NULL,
                       reviewed_at=?,
                       pending_human=0,
                       summary_flagged=0,
                       gate3_status=NULL
                   WHERE issue_id=?""",
                (now, issue_id)
            )

            old_num = str(issue["issue_number"] or issue_id)
            void_num = self._make_voided_issue_number(conn, old_num, issue_id)
            conn.execute(
                "UPDATE issues SET status='voided', issue_number=? WHERE id=?",
                (void_num, issue_id)
            )
            return {
                "issue_id": issue_id,
                "count": cursor.rowcount,
                "article_ids": article_ids,
                "issue_number": old_num,
                "voided_number": void_num,
                "already_voided": False,
            }

    def publish_issue(self, issue_id: int, html_path: str):
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE issues SET status='published', html_path=?, published_at=? WHERE id=?",
                (html_path, now, issue_id)
            )
            # Mark all articles as in_issue + set issue_id
            row = conn.execute("SELECT article_ids FROM issues WHERE id=?", (issue_id,)).fetchone()
            if row:
                try:
                    aids = json.loads(row["article_ids"])
                except:
                    aids = []
                if aids:
                    placeholders = ",".join(["?"] * len(aids))
                    conn.execute(
                        f"UPDATE articles SET status='in_issue', issue_id=? WHERE id IN ({placeholders})",
                        [issue_id] + aids
                    )

    def get_issue_articles(self, issue_id: int) -> list[dict]:
        issue = self.get_issue(issue_id)
        if not issue:
            return []
        aids = issue["article_ids"]
        if not aids:
            return []
        with self._get_conn() as conn:
            placeholders = ",".join(["?"] * len(aids))
            rows = conn.execute(
                f"SELECT * FROM articles WHERE id IN ({placeholders})",
                aids
            ).fetchall()
            articles = [self._row_to_dict(r) for r in rows]
            # Sort by issue order
            aid_to_article = {a["id"]: a for a in articles}
            ordered = []
            for aid in aids:
                if aid in aid_to_article:
                    ordered.append(aid_to_article[aid])
            return ordered

    # --- Candidate pool queries ---

    def get_candidate_pool(self) -> list[dict]:
        """Get candidate articles sorted: channel group, carryover first, tier (A before B), candidate time.
        Excludes: vetoed, fit_reasons-pending, already in issue."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE (status='candidate' OR status='approved')
                     AND issue_id IS NULL
                     AND COALESCE(evergreen,0)=0
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                   ORDER BY
                     category,
                     CASE WHEN COALESCE(carryover_count,0) > 0 THEN 0 ELSE 1 END,
                     CASE gate2_tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
                     reviewed_at DESC,
                     COALESCE(carryover_count,0) DESC"""
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_evergreen_pool(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM articles
                   WHERE evergreen=1
                     AND status IN ('pending','candidate','approved')
                     AND issue_id IS NULL
                     AND COALESCE(pending_human,0)=0
                     AND COALESCE(summary_flagged,0)=0
                   ORDER BY category, reviewed_at DESC"""
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    # --- Lifecycle operations ---

    def mark_evergreen(self, article_id: int, value: bool = True):
        updates = {"evergreen": 1 if value else 0}
        if value:
            article = self.get_article(article_id) or {}
            if article.get("status") in ("candidate", "approved"):
                updates.update({
                    "status": "pending",
                    "reviewed_at": None,
                    "issue_id": None,
                    "issue_sort_order": None,
                })
        self.update_article(article_id, updates)

    def get_articles_feedback(self, article_ids: list[int]) -> list[dict]:
        """Return dj_feedback + feedback_detail for a list of article IDs."""
        if not article_ids:
            return []
        with self._get_conn() as conn:
            placeholders = ",".join(["?"] * len(article_ids))
            rows = conn.execute(
                f"SELECT id, dj_feedback, feedback_detail FROM articles WHERE id IN ({placeholders})",
                article_ids
            ).fetchall()
            return [{"id": r["id"], "dj_feedback": r["dj_feedback"] or "", "feedback_detail": r["feedback_detail"] or ""} for r in rows]

    def set_dj_feedback(self, article_id: int, feedback: str, detail: str = ""):
        if feedback not in ("checked", "skipped"):
            raise ValueError("dj_feedback must be 'checked' or 'skipped'")
        if detail and detail not in ("asap", "next_trip"):
            raise ValueError("feedback_detail must be 'asap' or 'next_trip'")
        updates = {"dj_feedback": feedback}
        if detail:
            updates["feedback_detail"] = detail
        self.update_article(article_id, updates)

    def assign_to_issue(self, article_ids: list[int], issue_id: int, sort_orders: list[int] = None):
        """Assign articles to an issue. Updates status and issue_id."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            for i, aid in enumerate(article_ids):
                sort_order = sort_orders[i] if sort_orders else i
                conn.execute(
                    "UPDATE articles SET status='in_issue', issue_id=?, issue_sort_order=?, reviewed_at=?, pending_human=0, summary_flagged=0, gate3_status=NULL WHERE id=?",
                    (issue_id, sort_order, now, aid)
                )

    def auto_archive(self, article_id: int, reason: str, archive_type: str = "archived"):
        """Archive/sink an article with reason. Idempotent.
        archive_type='archived' -> status='rejected' (终点站)
        archive_type='sunk' -> status='sunk' (沉库, 可回捞)
        """
        now = datetime.now().isoformat()
        final_status = "sunk" if archive_type == "sunk" else "rejected"
        with self._get_conn() as conn:
            row = conn.execute("SELECT status FROM articles WHERE id=?", (article_id,)).fetchone()
            if row and row["status"] not in ("rejected", "sunk", "published"):
                conn.execute(
                    "UPDATE articles SET status=?, archive_reason=?, archive_reason_at=?, reviewed_at=?, archive_type=? WHERE id=?",
                    (final_status, reason, now, now, archive_type, article_id)
                )
                return True
        return False

    def carryover_candidates(self, excluded_ids: list[int], carryover_limit: int = 2):
        """Increment carryover_count for unselected candidates. Returns count of sunk (顺延超限).
        carryover_limit: 连续落选上限, 默认2 (可外置配置)
        顺延超限 -> 沉库(sunk), 非终点站.

        当 carryover_sink_enabled=False 时, 只递增 carryover_count, 不沉库."""
        now = datetime.now().isoformat()
        archived_count = 0

        # 读取开关: carryover_sink_enabled
        try:
            from src.config import load_config
            cfg = load_config()
            sink_enabled = cfg.get("throttle", {}).get("carryover_sink_enabled", True)
        except Exception:
            sink_enabled = True

        with self._get_conn() as conn:
            placeholders = ",".join(["?"] * len(excluded_ids)) if excluded_ids else "0"
            # Get all unselected candidates (not evergreen)
            rows = conn.execute(
                f"""SELECT id, COALESCE(carryover_count,0) as carryover_count, COALESCE(evergreen,0) as evergreen
                    FROM articles WHERE status='candidate'
                    AND id NOT IN ({placeholders})""",
                excluded_ids
            ).fetchall()

            for row in rows:
                if row["evergreen"]:
                    continue  # Evergreen articles don't participate in carryover

                if not sink_enabled:
                    # 开关关闭: 永不沉库, 仅递增
                    new_count = row["carryover_count"] + 1
                    conn.execute(
                        "UPDATE articles SET carryover_count=? WHERE id=?",
                        (new_count, row["id"])
                    )
                else:
                    new_count = row["carryover_count"] + 1
                    if new_count >= carryover_limit:
                        conn.execute(
                            "UPDATE articles SET status='sunk', archive_reason='顺延超限', archive_reason_at=?, reviewed_at=?, archive_type='sunk' WHERE id=?",
                            (now, now, row["id"])
                        )
                        archived_count += 1
                    else:
                        conn.execute(
                            "UPDATE articles SET carryover_count=? WHERE id=?",
                            (new_count, row["id"])
                        )
        return archived_count

    # --- Expiry check ---

    def run_expiry_check(self, sink_c_tier: bool = False, c_tier_window_days: int = 3) -> dict:
        """Check candidate/evergreen articles for expired time-bound events. Returns stats.
        When sink_c_tier=True, also sinks C-tier articles older than c_tier_window_days.
        """
        now_str = datetime.now().strftime("%Y-%m-%d")
        stats = {"archived": 0, "nearing": 0, "checked": 0, "c_sunk": 0}
        with self._get_conn() as conn:
            # Check articles with expiry_date set
            rows = conn.execute(
                """SELECT id, title, expiry_date FROM articles
                   WHERE status IN ('candidate','approved','in_issue') AND (dj_feedback IS NULL OR dj_feedback != 'skipped')
                     AND expiry_date IS NOT NULL AND expiry_date != ''"""
            ).fetchall()

            stats["checked"] = len(rows)
            for row in rows:
                try:
                    exp_date = row["expiry_date"]
                    # Compare dates
                    if exp_date < now_str:
                        # Expired
                        conn.execute(
                            "UPDATE articles SET status='rejected', archive_reason='时效已过', archive_reason_at=datetime('now'), reviewed_at=datetime('now'), archive_type='archived' WHERE id=?",
                            (row["id"],)
                        )
                        stats["archived"] += 1
                    elif exp_date <= (datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d") if False else ""):
                        pass
                    # Check nearing (within 7 days)
                    from datetime import timedelta
                    exp_dt = datetime.strptime(exp_date, "%Y-%m-%d")
                    now_dt = datetime.now()
                    if exp_dt <= now_dt + timedelta(days=7) and exp_dt >= now_dt:
                        stats["nearing"] += 1
                except:
                    pass


            # C档超窗沉底 (B2)
            if sink_c_tier:
                c_rows = conn.execute(
                    """SELECT id FROM articles
                       WHERE gate2_tier='C' AND status='pending' AND pending_human=0
                         AND COALESCE(evergreen,0)=0
                         AND gate2_checked_at IS NOT NULL
                         AND date(gate2_checked_at) < date('now', ?)""",
                    (f'-{c_tier_window_days} days',)
                ).fetchall()
                for cr in c_rows:
                    conn.execute(
                        "UPDATE articles SET status='sunk', archive_reason='C档过窗', archive_reason_at=datetime('now'), reviewed_at=datetime('now'), archive_type='sunk' WHERE id=?",
                        (cr["id"],)
                    )
                    stats["c_sunk"] += 1

        return stats

    def log_task_run(self, task_name: str, stats: dict, summary: str = "") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO task_log (task_name, stats, summary) VALUES (?, ?, ?)",
                (task_name, json.dumps(stats), summary)
            )
            return cursor.lastrowid

    def get_latest_task_log(self, task_name: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM task_log WHERE task_name=? ORDER BY run_at DESC LIMIT 1",
                (task_name,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            if isinstance(d.get("stats"), str):
                try:
                    d["stats"] = json.loads(d["stats"])
                except:
                    d["stats"] = {}
            return d

    def get_archive_stats(self) -> dict:
        """Get archive stats with extended reasons"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT archive_reason, COUNT(*) as cnt FROM articles WHERE status='rejected' AND archive_reason IS NOT NULL GROUP BY archive_reason ORDER BY cnt DESC"
            ).fetchall()
            return {row["archive_reason"]: row["cnt"] for row in rows}

    def get_sunk_articles(self, limit: int = 200) -> list[dict]:
        """获取沉库文章列表"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM articles WHERE status='sunk' ORDER BY archive_reason_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_c_tier_in_window(self, window_days: int = 3, limit: int = 300) -> list[dict]:
        """获取窗口内的C档待筛选文章"""
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM articles
                   WHERE gate2_tier='C' AND status='pending' AND pending_human=0
                     AND COALESCE(evergreen,0)=0
                     AND gate2_checked_at IS NOT NULL
                     AND date(gate2_checked_at) >= date('now', '-{window_days} days')
                   ORDER BY gate2_checked_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def url_exists(self, url: str) -> bool:
        url = _normalize_url(url)
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
            return row is not None



TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid"}

def _normalize_url(url: str) -> str:
    """剥离 tracking 参数 (utm_*, fbclid 等), 返回规范 URL"""
    parsed = urlparse(url)
    if not parsed.query:
        return url
    qs = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in qs.items() if k not in TRACKING_PARAMS}
    new_query = urlencode(cleaned, doseq=True)
    return urlunparse(parsed._replace(query=new_query, fragment=""))
# --- 辅助函数 ---

def _archive_type_for_reason(reason: str) -> str:
    """根据归档原因判断 archive_type
    - 终点站(archived): 人工归档类、违规、质检fail、否决、D档、时效已过
    - 沉库(sunk): 顺延超限、小组赛两败、C档过窗
    """
    SUNK_REASONS = {"顺延超限", "C档过窗", "小组赛两败"}
    if reason in SUNK_REASONS:
        return "sunk"
    return "archived"
