"""
定时任务调度器 — 每日抓取 + 自动前两关 + 图片清理
所有子进程输出写入 /data/output/ 独立日志文件
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
LOG_DIR = Path("/data/output")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _today():
    return datetime.now().strftime("%Y%m%d")


def _run_script(script_name, log_name, timeout=600):
    """运行脚本，输出写入日志文件，返回(returncode, stderr_tail)"""
    log_path = LOG_DIR / f"{log_name}_{_today()}.log"
    logger.info(f"▶ {script_name} → {log_path}")
    try:
        with open(log_path, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{datetime.now().isoformat()} — {script_name}\n")
            f.write(f"{'='*60}\n")
            f.flush()
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / script_name)],
                stdout=f, stderr=subprocess.STDOUT,
                cwd=str(PROJECT_ROOT), timeout=timeout,
            )
        if result.returncode == 0:
            logger.info(f"✅ {script_name} 完成 → {log_path}")
            return True, ""
        else:
            tail = _tail(log_path, 5)
            logger.error(f"❌ {script_name} 失败(rc={result.returncode}) → {log_path}")
            for t in tail:
                logger.error(f"  {t}")
            return False, tail
    except subprocess.TimeoutExpired:
        logger.error(f"❌ {script_name} 超时(>{timeout}s)")
        return False, ["超时"]
    except Exception as e:
        logger.error(f"❌ {script_name} 异常: {e}")
        return False, [str(e)]


def _tail(path, n=5):
    try:
        with open(path) as f:
            lines = f.readlines()
        return [l.rstrip()[-200:] for l in lines[-n:]]
    except:
        return []


def run_gate1():
    ok, _ = _run_script("run_gate1.py", "gates", timeout=1200)
    return ok


def run_gate2():
    ok, _ = _run_script("run_gate2.py", "gates", timeout=900)
    return ok


def _database():
    from src.config import load_config
    from src.database import Database

    config = load_config()
    return Database(config["database"]["path"])


def _count_gate1_left():
    return _database().count_gate1_candidates()


def _count_gate2_left():
    return _database().count_gate2_candidates()


def _log_pipeline(stage: str, status: str, **stats):
    """Record daily pipeline milestones for briefings and diagnosis."""
    payload = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "stage": stage,
        "status": status,
        **stats,
    }
    try:
        _database().log_task_run("daily_pipeline", payload, f"{stage}:{status}")
    except Exception:
        logger.exception("记录 daily_pipeline 状态失败")


def _run_until_converged(name, run_once, count_left, max_rounds=5):
    """Run one gate repeatedly until its backlog is empty or no progress is made."""
    before = count_left()
    if before == 0:
        logger.info(f"{name} 无 backlog，跳过")
        return True

    for round_no in range(1, max_rounds + 1):
        logger.info(f"{name} 第 {round_no}/{max_rounds} 轮开始: backlog={before}")
        ok = run_once()
        after = count_left()
        logger.info(f"{name} 第 {round_no}/{max_rounds} 轮结束: before={before} after={after} processed_or_changed={max(before - after, 0)}")

        if not ok:
            logger.error(f"⛔ {name} 第 {round_no} 轮失败，停止收敛")
            return False
        if after == 0:
            logger.info(f"✅ {name} backlog 已收敛为 0")
            return True
        if after >= before:
            logger.error(f"⛔ {name} backlog 未减少({before} -> {after})，停止以避免重复空转")
            return False
        before = after

    logger.error(f"⛔ {name} 达到最大轮数后仍有 backlog={before}")
    return False


def daily_crawl():
    """每日抓取 + 自动前两关"""
    try:
        logger.info("⏰ 开始每日定时任务链...")
        _log_pipeline("daily_crawl", "started")

        # 信源健康检查 (非阻塞，失败不影响主流程)
        _log_pipeline("verify", "started")
        verify_ok, verify_tail = _run_script("run_verify_sites.py", "verify", timeout=120)
        _log_pipeline("verify", "done" if verify_ok else "failed", stderr_tail=verify_tail)

        # 抓取
        _log_pipeline("crawl", "started")
        ok, _ = _run_script("run_crawl.py", "crawl", timeout=3600)
        if not ok:
            logger.error("⛔ 抓取失败，跳过前两关")
            _log_pipeline("crawl", "failed")
            _log_pipeline("daily_crawl", "failed", failed_stage="crawl")
            return
        _log_pipeline("crawl", "done", gate1_left=_count_gate1_left())

        # 仅自动前两关; Gate3 已停用。每关循环收敛，避免抓取尾巴漏跑。
        logger.info("🔄 开始自动前两关收敛...")
        _log_pipeline("gate1", "started", gate1_left=_count_gate1_left())
        if _run_until_converged("Gate1", run_gate1, _count_gate1_left, max_rounds=5):
            _log_pipeline("gate1", "done", gate1_left=_count_gate1_left(), gate2_left=_count_gate2_left())
            _log_pipeline("gate2", "started", gate2_left=_count_gate2_left())
            if _run_until_converged("Gate2", run_gate2, _count_gate2_left, max_rounds=5):
                _log_pipeline("gate2", "done", gate2_left=_count_gate2_left())
                logger.info("⏭️ Gate3 已停用，跳过")
            else:
                logger.error("⛔ Gate2 未完全收敛，请查看 gates 日志")
                _log_pipeline("gate2", "failed", gate2_left=_count_gate2_left())
        else:
            logger.error("⛔ Gate1 未完全收敛，跳过 Gate2")
            _log_pipeline("gate1", "failed", gate1_left=_count_gate1_left())

        logger.info("✅ 每日定时任务链结束")
        _log_pipeline("daily_crawl", "done", gate1_left=_count_gate1_left(), gate2_left=_count_gate2_left())
    except Exception:
        logger.exception("⛔ 每日定时任务链异常退出")
        _log_pipeline("daily_crawl", "exception")


def weekly_report():
    """周五生成周报"""
    _run_script("run_report.py", "weekly_report", timeout=1200)


def review_reminder():
    logger.info("🔔 提醒：请进行人工审核！")


def image_cleanup():
    """每日图片清理"""
    _run_script("run_image_cleanup.py", "image_cleanup", timeout=300)


def image_compress():
    """批量图片压缩 — 仅手动触发"""
    _run_script("run_image_compress.py", "image_compress", timeout=1800)


def start_scheduler():
    """启动调度器"""
    if not logging.getLogger().handlers:
        # 确保日志目录存在
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _sched_log = LOG_DIR / "scheduler.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(str(_sched_log), encoding="utf-8"),
            ],
        )

    logger.info("=" * 50)
    logger.info("高品质图文推荐系统 — 调度器启动")
    logger.info(f"日志目录: {LOG_DIR}")
    logger.info("=" * 50)

    schedule.every().day.at("01:00").do(daily_crawl)
    logger.info("📅 每日 01:00 UTC (09:00 CST) — 抓取 + 前两关收敛")

    schedule.every().wednesday.at("02:00").do(review_reminder)
    logger.info("📅 每周三 02:00 UTC — 审核提醒")

    schedule.every().day.at("19:00").do(image_cleanup)
    logger.info("📅 每日 19:00 UTC (次日03:00 CST) — 图片清理")

    logger.info("")
    logger.info("调度器运行中...")
    logger.info("")

    while True:
        try:
            schedule.run_pending()
        except Exception:
            logger.exception("⛔ 调度循环异常")
        time.sleep(60)


if __name__ == "__main__":
    start_scheduler()
