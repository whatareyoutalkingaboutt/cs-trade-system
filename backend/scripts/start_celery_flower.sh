#!/bin/bash
# Celery Flower 启动脚本
#
# Flower: Celery的Web监控工具
# - 实时监控Worker状态
# - 查看任务执行历史
# - 任务统计和分析
#
# 使用方法:
#   chmod +x backend/scripts/start_celery_flower.sh
#   ./backend/scripts/start_celery_flower.sh
#
# 访问: http://localhost:5555

# 进入项目根目录
cd "$(dirname "$0")/../.." || exit

# 激活虚拟环境(如果存在)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 设置端口
PORT=${PORT:-5555}

# 启动Flower
echo "🌸 启动 Celery Flower..."
echo "   访问地址: http://localhost:$PORT"
echo ""

celery -A backend.core.celery_app flower \
    --port=$PORT \
    --url_prefix=flower

# 说明:
# -A backend.core.celery_app: 指定Celery应用模块
# --port: Web端口
# --url_prefix: URL前缀(可选)
