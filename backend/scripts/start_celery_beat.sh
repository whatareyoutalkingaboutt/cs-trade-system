#!/bin/bash
# Celery Beat 启动脚本
#
# 功能:
# - 启动Celery Beat定时调度器
# - 按照配置定时发起采集任务
#
# 使用方法:
#   chmod +x backend/scripts/start_celery_beat.sh
#   ./backend/scripts/start_celery_beat.sh

# 进入项目根目录
cd "$(dirname "$0")/../.." || exit

# 激活虚拟环境(如果存在)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 设置日志级别
LOG_LEVEL=${LOG_LEVEL:-INFO}

# 启动Celery Beat
echo "⏰ 启动 Celery Beat..."
echo "   日志级别: $LOG_LEVEL"
echo ""

celery -A backend.core.celery_app beat \
    --loglevel=$LOG_LEVEL \
    --scheduler celery.beat:PersistentScheduler

# 说明:
# -A backend.core.celery_app: 指定Celery应用模块
# --loglevel: 日志级别
# --scheduler: 调度器类型(PersistentScheduler会将调度状态持久化到文件)
