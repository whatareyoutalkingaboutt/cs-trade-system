#!/usr/bin/env python3
"""
Celery 配置文件

定义Celery的各种配置选项,包括:
- 序列化方式
- 时区设置
- 任务结果过期时间
- 并发设置
- 定时任务调度
"""

import os
from datetime import timedelta
from celery.schedules import crontab


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


ENABLE_LEGACY_MULTI_PLATFORM_SCRAPE = _env_flag("ENABLE_LEGACY_MULTI_PLATFORM_SCRAPE", default=False)

# ==================== 基础配置 ====================

# 时区设置
timezone = 'Asia/Shanghai'
enable_utc = False

# 任务序列化方式
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']

# ==================== 结果存储配置 ====================

# 任务结果过期时间(秒)
result_expires = 3600  # 1小时后过期

# 是否忽略任务结果(如果不需要获取任务返回值,可以设为True以提升性能)
task_ignore_result = False

# 是否追踪任务开始状态
task_track_started = True

# ==================== 任务执行配置 ====================

# 单个任务的最大执行时间(秒)
task_soft_time_limit = 300  # 5分钟软限制(会抛出异常)
task_time_limit = 600  # 10分钟硬限制(会杀死进程)

# 任务失败后是否重试
task_acks_late = True  # 任务执行完成后才确认(确保任务不会丢失)
task_reject_on_worker_lost = True  # Worker崩溃时拒绝任务(会重新入队)

# ==================== Worker配置 ====================

# Worker并发数(进程/线程数量)
# - 对于IO密集型任务(如网络请求),可以设置较高的并发数
# - 对于CPU密集型任务,建议设置为CPU核心数
worker_concurrency = max(1, int(os.getenv("CELERY_WORKER_CONCURRENCY", "2")))  # 2C2G 推荐 2

# Worker预加载任务模块(提升启动速度)
worker_prefetch_multiplier = 1  # 每次从队列获取的任务数

# Worker最大任务执行数(防止内存泄漏)
worker_max_tasks_per_child = 1000  # 执行1000个任务后重启Worker进程

# ==================== 日志配置 ====================

# Worker日志级别
worker_log_level = 'INFO'  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# 任务日志格式
worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'

# ==================== 定时任务配置 (Celery Beat) ====================

beat_schedule = {
    # 心跳检测(每1分钟)
    'system-heartbeat': {
        'task': 'backend.scrapers.celery_tasks.write_heartbeat',
        'schedule': timedelta(minutes=1),
        'options': {
            'queue': 'default',
        }
    },

    # 清理过期缓存(每天凌晨3点)
    'cleanup-expired-cache': {
        'task': 'backend.scrapers.celery_tasks.cleanup_cache',
        'schedule': crontab(hour=3, minute=0),
        'options': {
            'queue': 'default',
        }
    },

    # 价格异常检测(每15分钟)
    'detect-price-anomalies': {
        'task': 'backend.scrapers.celery_tasks.detect_price_anomalies',
        'schedule': timedelta(minutes=15),
        'options': {
            'queue': 'default',
            'expires': 300,
        }
    },

    # 数据完整性检查(每天凌晨2:30)
    'check-data-integrity': {
        'task': 'backend.scrapers.celery_tasks.check_data_integrity',
        'schedule': crontab(hour=2, minute=30),
        'options': {
            'queue': 'default',
            'expires': 3600,
        }
    },

    # SteamDT base 全量同步(每天凌晨4点)
    'sync-base-items': {
        'task': 'backend.scrapers.celery_tasks.sync_base_items',
        'schedule': crontab(hour=4, minute=0),
        'options': {
            'queue': 'default',
            'expires': 3600,
        }
    },

    # CSQAQ 全量价格快照同步(每5分钟)
    'sync-csqaq-all-prices': {
        'task': 'backend.scrapers.celery_tasks.sync_csqaq_all_prices',
        'schedule': timedelta(minutes=5),
        'options': {
            'queue': 'default',
            'expires': 240,
        }
    },

    # 庄家行为监控（每5分钟）
    'monitor-market-maker-behavior': {
        'task': 'backend.scrapers.celery_tasks.monitor_market_maker_behavior',
        'schedule': timedelta(minutes=5),
        'options': {
            'queue': 'default',
            'expires': 240,
        }
    },

    # 热门饰品榜单计算（每15分钟）
    'calculate-daily-rankings': {
        'task': 'backend.scrapers.celery_tasks.calculate_daily_rankings',
        'schedule': timedelta(minutes=15),
        'options': {
            'queue': 'default',
            'expires': 300,
        }
    },

    # 高优复核候选队列消费(每秒)
    'dispatch-high-priority-verify-queue': {
        'task': 'backend.scrapers.celery_tasks.dispatch_high_priority_verify_queue',
        'schedule': timedelta(seconds=max(1, int(os.getenv("VERIFY_QUEUE_DISPATCH_INTERVAL_SECONDS", "1")))),
        'kwargs': {
            'max_dispatch': 1,
        },
        'options': {
            'queue': 'default',
            'expires': 1,
        }
    },

    # 基准线缓存刷新（每小时）
    'refresh-item-baselines': {
        'task': 'backend.scrapers.celery_tasks.refresh_item_baselines',
        'schedule': timedelta(hours=1),
        'options': {
            'queue': 'default',
            'expires': 300,
        }
    },
}

if ENABLE_LEGACY_MULTI_PLATFORM_SCRAPE:
    beat_schedule.update(
        {
            # 高优先级饰品采集(每5分钟)
            'scrape-high-priority-items': {
                'task': 'backend.scrapers.celery_tasks.scrape_items_by_priority',
                'schedule': timedelta(minutes=5),
                'args': ('high',),  # 优先级: high (8-10)
                'options': {
                    'queue': 'default',
                    'expires': 60,  # 任务60秒后过期
                }
            },
            # 中优先级饰品采集(每30分钟)
            'scrape-medium-priority-items': {
                'task': 'backend.scrapers.celery_tasks.scrape_items_by_priority',
                'schedule': timedelta(minutes=30),
                'args': ('medium',),  # 优先级: medium (5-7)
                'options': {
                    'queue': 'default',
                    'expires': 300,
                }
            },
            # 低优先级饰品采集(每2小时)
            'scrape-low-priority-items': {
                'task': 'backend.scrapers.celery_tasks.scrape_items_by_priority',
                'schedule': timedelta(hours=2),
                'args': ('low',),  # 优先级: low (1-4)
                'options': {
                    'queue': 'default',
                    'expires': 600,
                }
            },
        }
    )

# ==================== 队列配置 ====================

# 定义多个队列,用于任务优先级和资源隔离
task_queues = {
    'default': {
        'exchange': 'default',
        'routing_key': 'default',
    },
    'steam': {
        'exchange': 'steam',
        'routing_key': 'steam',
    },
    'buff': {
        'exchange': 'buff',
        'routing_key': 'buff',
    },
    'verify': {
        'exchange': 'verify',
        'routing_key': 'verify',
    },
}

# 默认队列
task_default_queue = 'default'
task_default_exchange = 'default'
task_default_routing_key = 'default'

# ==================== 其他配置 ====================

# Beat调度器使用的数据库(存储定时任务的执行状态)
beat_scheduler = 'celery.beat:PersistentScheduler'

# Beat调度数据文件
beat_schedule_filename = 'celerybeat-schedule'

# 启用事件监控(用于Flower等监控工具)
worker_send_task_events = True
task_send_sent_event = True
