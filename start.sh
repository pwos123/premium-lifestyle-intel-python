#!/bin/bash
set -e

# 确保数据目录
mkdir -p /data/content /data/images /data/output

# 后台启动调度器
echo "[start] 启动定时调度器..."
(
  while true; do
    echo "[$(date -Iseconds)] [scheduler-supervisor] 启动 scheduler.py" >> /data/output/scheduler_supervisor.log
    python -u -m src.scheduler >> /data/output/scheduler_supervisor.log 2>&1
    code=$?
    echo "[$(date -Iseconds)] [scheduler-supervisor] scheduler.py 退出 code=${code}，5秒后重启" >> /data/output/scheduler_supervisor.log
    sleep 5
  done
) &

# 启动 Web 服务
echo "[start] 启动 Web 服务 (端口 ${PORT:-8080})..."
exec gunicorn app:app \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 1 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile -
