#!/bin/bash
# Celery Worker 启动脚本
#
# 功能:
# - 启动Celery Worker进程
# - 处理异步任务队列
#
# 使用方法:
#   chmod +x backend/scripts/start_celery_worker.sh
#   ./backend/scripts/start_celery_worker.sh

# 进入项目根目录
cd "$(dirname "$0")/../.." || exit

# 激活虚拟环境(如果存在)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 设置日志级别
LOG_LEVEL=${LOG_LEVEL:-INFO}

# 设置并发数
CONCURRENCY=${CONCURRENCY:-2}

# 启动Celery Worker
echo "🚀 启动 Celery Worker..."
echo "   日志级别: $LOG_LEVEL"
echo "   并发数: $CONCURRENCY"
echo ""

celery -A backend.core.celery_app worker \
    --loglevel=$LOG_LEVEL \
    --concurrency=$CONCURRENCY \
    --max-tasks-per-child=1000 \
    --pool=prefork \
    --queues=default,steam,buff \
    --hostname=worker@%h

# 说明:
# -A backend.core.celery_app: 指定Celery应用模块
# --loglevel: 日志级别(DEBUG, INFO, WARNING, ERROR, CRITICAL)
# --concurrency: 并发进程数
# --max-tasks-per-child: 每个Worker进程最多处理的任务数(防止内存泄漏)
# --pool: 并发池类型(prefork=多进程, threads=多线程, solo=单进程)
# --queues: 监听的队列列表
# --hostname: Worker主机名
