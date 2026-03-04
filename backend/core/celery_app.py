#!/usr/bin/env python3
"""
Celery 应用配置

创建和配置Celery应用实例,用于异步任务队列和定时调度。

使用DragonflyDB作为Broker和Backend:
- Broker: 消息队列,用于传递任务
- Backend: 结果存储,用于保存任务执行结果

DragonflyDB特点:
- 完全兼容Redis协议
- 性能更高(25倍于Redis)
- 内存效率更高
- 支持持久化
"""

import os
from celery import Celery
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 从环境变量读取配置
DRAGONFLYDB_HOST = os.getenv('DRAGONFLYDB_HOST', 'localhost')
DRAGONFLYDB_PORT = os.getenv('DRAGONFLYDB_PORT', '6379')
DRAGONFLYDB_PASSWORD = os.getenv('DRAGONFLYDB_PASSWORD', '')
DRAGONFLYDB_DB = os.getenv('DRAGONFLYDB_DB', '0')

# 构建连接URL
if DRAGONFLYDB_PASSWORD:
    BROKER_URL = f"redis://:{DRAGONFLYDB_PASSWORD}@{DRAGONFLYDB_HOST}:{DRAGONFLYDB_PORT}/{DRAGONFLYDB_DB}"
else:
    BROKER_URL = f"redis://{DRAGONFLYDB_HOST}:{DRAGONFLYDB_PORT}/{DRAGONFLYDB_DB}"

# 创建Celery应用实例
celery_app = Celery(
    'cs_item_scraper',
    broker=BROKER_URL,
    backend=BROKER_URL,
    include=[
        'backend.scrapers.celery_tasks',  # 导入任务模块
    ]
)

# Celery配置
celery_app.config_from_object('backend.config.celery_config')

# 任务路由(可选,用于将不同类型的任务发送到不同的队列)
celery_app.conf.task_routes = {
    'backend.scrapers.celery_tasks.scrape_steam_price': {'queue': 'steam'},
    'backend.scrapers.celery_tasks.scrape_buff_price': {'queue': 'buff'},
    'backend.scrapers.celery_tasks.scrape_youpin_price': {'queue': 'default'},
    'backend.scrapers.celery_tasks.scrape_all_platforms': {'queue': 'default'},
    'backend.scrapers.celery_tasks.sync_base_items': {'queue': 'default'},
    'backend.scrapers.celery_tasks.sync_csqaq_all_prices': {'queue': 'default'},
    'backend.scrapers.celery_tasks.monitor_market_maker_behavior': {'queue': 'default'},
    'backend.scrapers.celery_tasks.dispatch_high_priority_verify_queue': {'queue': 'default'},
    'backend.scrapers.celery_tasks.refresh_item_baselines': {'queue': 'default'},
    'backend.scrapers.celery_tasks.verify_and_alert_task': {'queue': 'verify'},
}


if __name__ == '__main__':
    celery_app.start()
