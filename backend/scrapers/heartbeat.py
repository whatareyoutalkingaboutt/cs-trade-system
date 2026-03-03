#!/usr/bin/env python3
"""
心跳检测系统

功能:
- 定期写入心跳信号(每1分钟)
- 记录系统健康状态
- 用于监控和高可用管理

心跳信息包括:
- 时间戳
- Worker ID
- 系统状态(healthy/unhealthy)
- 任务统计
- 系统资源使用情况

数据存储:
- DragonflyDB: 实时心跳(快速检测)
- TimescaleDB: 历史心跳(长期分析)
"""

import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from loguru import logger
from sqlalchemy import text

from backend.core.cache import get_dragonfly_client
from backend.core.database import get_sessionmaker

try:
    import psutil
except ModuleNotFoundError:  # pragma: no cover - compatibility fallback
    psutil = None


class HeartbeatManager:
    """
    心跳管理器

    负责生成和写入心跳信号
    """

    def __init__(self, worker_id: Optional[str] = None):
        """
        初始化心跳管理器

        参数:
            worker_id: Worker ID(默认从环境变量读取或使用主机名)
        """
        self.worker_id = worker_id or os.getenv('WORKER_ID') or os.uname().nodename
        logger.info("💓 [Heartbeat] 初始化心跳管理器: Worker ID = {}", self.worker_id)

    def generate_heartbeat(self) -> Dict[str, Any]:
        """
        生成心跳数据

        返回:
            心跳数据字典:
            {
                'worker_id': str,
                'timestamp': str,
                'status': str,
                'uptime': float,
                'cpu_percent': float,
                'memory_percent': float,
                'disk_percent': float,
                'tasks_completed': int,
                'tasks_failed': int
            }
        """
        try:
            if psutil is None:
                logger.warning("⚠️ [Heartbeat] psutil not installed, fallback to zero resource metrics")
                cpu_percent = 0.0
                memory_percent = 0.0
                disk_percent = 0.0
                uptime = 0.0
            else:
                # 获取系统资源使用情况
                cpu_percent = psutil.cpu_percent(interval=1)
                memory_percent = psutil.virtual_memory().percent
                disk_percent = psutil.disk_usage('/').percent

                # 获取系统启动时间
                boot_time = psutil.boot_time()
                uptime = datetime.now().timestamp() - boot_time

            # 构建心跳数据
            heartbeat = {
                'worker_id': self.worker_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': self._determine_status(cpu_percent, memory_percent, disk_percent),
                'uptime': uptime,
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'disk_percent': disk_percent,
                # 若接入 Celery 统计, 可从外部覆盖这两个字段
                'tasks_completed': 0,
                'tasks_failed': 0
            }

            logger.debug("💓 [Heartbeat] 生成心跳: {}", heartbeat)
            return heartbeat

        except Exception as e:
            logger.error("❌ [Heartbeat] 生成心跳失败: {}", e)
            # 返回最小心跳数据
            return {
                'worker_id': self.worker_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'status': 'error',
                'error': str(e)
            }

    def _determine_status(
        self,
        cpu_percent: float,
        memory_percent: float,
        disk_percent: float
    ) -> str:
        """
        根据资源使用情况判断系统状态

        参数:
            cpu_percent: CPU使用率
            memory_percent: 内存使用率
            disk_percent: 磁盘使用率

        返回:
            'healthy', 'warning', 'critical'
        """
        # 阈值配置
        CPU_WARNING = 80
        CPU_CRITICAL = 95
        MEMORY_WARNING = 80
        MEMORY_CRITICAL = 95
        DISK_WARNING = 80
        DISK_CRITICAL = 95

        # 检查是否达到临界值
        if (cpu_percent >= CPU_CRITICAL or
            memory_percent >= MEMORY_CRITICAL or
            disk_percent >= DISK_CRITICAL):
            return 'critical'

        # 检查是否达到警告值
        if (cpu_percent >= CPU_WARNING or
            memory_percent >= MEMORY_WARNING or
            disk_percent >= DISK_WARNING):
            return 'warning'

        # 正常状态
        return 'healthy'

    def write_to_cache(self, heartbeat: Dict[str, Any]) -> bool:
        """
        写入心跳到DragonflyDB

        参数:
            heartbeat: 心跳数据

        返回:
            True: 成功
            False: 失败
        """
        try:
            client = get_dragonfly_client()
            key = f"heartbeat:worker:{self.worker_id}"
            mapping = {
                "timestamp": str(heartbeat.get("timestamp", "")),
                "status": str(heartbeat.get("status", "unknown")),
                "worker_id": self.worker_id,
                "uptime": str(heartbeat.get("uptime", "")),
                "cpu_percent": str(heartbeat.get("cpu_percent", "")),
                "memory_percent": str(heartbeat.get("memory_percent", "")),
                "disk_percent": str(heartbeat.get("disk_percent", "")),
                "tasks_completed": str(heartbeat.get("tasks_completed", 0)),
                "tasks_failed": str(heartbeat.get("tasks_failed", 0)),
            }
            client.hset(key, mapping=mapping)
            ttl_seconds = max(60, int(os.getenv("HEARTBEAT_TTL_SECONDS", "180")))
            client.expire(key, ttl_seconds)

            logger.debug("💓 [Heartbeat] 写入缓存成功: key={}", key)
            return True

        except Exception as e:
            logger.error("❌ [Heartbeat] 写入缓存失败: {}", e)
            return False

    def write_to_database(self, heartbeat: Dict[str, Any]) -> bool:
        """
        写入心跳到TimescaleDB

        参数:
            heartbeat: 心跳数据

        返回:
            True: 成功
            False: 失败
        """
        session = get_sessionmaker()()
        try:
            ts_raw = str(heartbeat.get("timestamp") or datetime.now(timezone.utc).isoformat())
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            metadata = {
                "source": "scrapers.heartbeat.HeartbeatManager",
                "uptime": heartbeat.get("uptime"),
                "disk_percent": heartbeat.get("disk_percent"),
                "tasks_completed": heartbeat.get("tasks_completed", 0),
                "tasks_failed": heartbeat.get("tasks_failed", 0),
            }
            session.execute(
                text(
                    """
                    INSERT INTO system_heartbeats
                        (time, component, instance_id, status, cpu_percent, memory_percent, active_tasks, metadata)
                    VALUES
                        (:time, :component, :instance_id, :status, :cpu_percent, :memory_percent, :active_tasks, CAST(:metadata AS JSONB))
                    """
                ),
                {
                    "time": ts,
                    "component": "celery_worker",
                    "instance_id": self.worker_id,
                    "status": str(heartbeat.get("status", "unknown")),
                    "cpu_percent": heartbeat.get("cpu_percent"),
                    "memory_percent": heartbeat.get("memory_percent"),
                    "active_tasks": 0,
                    "metadata": json.dumps(metadata, ensure_ascii=True),
                },
            )
            session.commit()

            logger.debug("💓 [Heartbeat] 写入数据库成功: worker_id={}", self.worker_id)
            return True

        except Exception as e:
            session.rollback()
            logger.error("❌ [Heartbeat] 写入数据库失败: {}", e)
            return False
        finally:
            session.close()

    def write_heartbeat(self) -> Dict[str, Any]:
        """
        生成并写入心跳信号

        返回:
            心跳数据
        """
        logger.info("💓 [Heartbeat] 开始写入心跳...")

        # 1. 生成心跳数据
        heartbeat = self.generate_heartbeat()

        # 2. 写入DragonflyDB(用于快速检测)
        cache_success = self.write_to_cache(heartbeat)

        # 3. 写入TimescaleDB(用于历史分析)
        db_success = self.write_to_database(heartbeat)

        # 4. 记录结果
        if cache_success and db_success:
            logger.success("✅ [Heartbeat] 心跳写入成功: {}", heartbeat.get("status"))
        elif cache_success or db_success:
            logger.warning("⚠️ [Heartbeat] 心跳部分写入成功")
        else:
            logger.error("❌ [Heartbeat] 心跳写入失败")

        return heartbeat


class HeartbeatMonitor:
    """
    心跳监控器

    检测其他Worker的心跳状态,用于故障检测
    """

    def __init__(self, timeout: int = 120):
        """
        初始化心跳监控器

        参数:
            timeout: 心跳超时时间(秒),超过此时间未收到心跳则认为Worker失联
        """
        self.timeout = timeout
        logger.info("👀 [HeartbeatMonitor] 初始化心跳监控器: 超时时间 = {}秒", timeout)

    def check_worker_alive(self, worker_id: str) -> bool:
        """
        检查Worker是否存活

        参数:
            worker_id: Worker ID

        返回:
            True: 存活
            False: 失联
        """
        try:
            client = get_dragonfly_client()
            payload = client.hgetall(f"heartbeat:worker:{worker_id}")
            ts_raw = payload.get("timestamp") if payload else None
            if not ts_raw:
                logger.debug("👀 [HeartbeatMonitor] Worker {}: 无心跳", worker_id)
                return False

            last_heartbeat_time = datetime.fromisoformat(ts_raw)
            if last_heartbeat_time.tzinfo is None:
                last_heartbeat_time = last_heartbeat_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta_seconds = (now - last_heartbeat_time).total_seconds()
            is_alive = delta_seconds <= self.timeout
            logger.debug("👀 [HeartbeatMonitor] Worker {}: {} ({}s)", worker_id, "存活" if is_alive else "超时", int(delta_seconds))
            return is_alive

        except Exception as e:
            logger.error("❌ [HeartbeatMonitor] 检查Worker失败: worker_id={}, err={}", worker_id, e)
            return False

    def get_all_workers(self) -> list:
        """
        获取所有Worker列表

        返回:
            Worker ID列表
        """
        try:
            client = get_dragonfly_client()
            workers = []
            prefix = "heartbeat:worker:"
            for key in client.scan_iter(match=f"{prefix}*", count=200):
                if not key.startswith(prefix):
                    continue
                worker_id = key[len(prefix):]
                if worker_id:
                    workers.append(worker_id)
            deduped_workers = sorted(set(workers))
            logger.debug("👀 [HeartbeatMonitor] 获取Worker列表: {}", deduped_workers)
            return deduped_workers

        except Exception as e:
            logger.error("❌ [HeartbeatMonitor] 获取Worker列表失败: {}", e)
            return []

    def check_all_workers(self) -> Dict[str, bool]:
        """
        检查所有Worker的状态

        返回:
            Worker状态字典: {worker_id: is_alive}
        """
        workers = self.get_all_workers()
        status = {}

        for worker_id in workers:
            status[worker_id] = self.check_worker_alive(worker_id)

        logger.info("👀 [HeartbeatMonitor] Worker状态: {}", status)
        return status


# ==================== 使用示例 ====================

def main():
    """主函数"""
    # 配置日志
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )

    # 创建心跳管理器
    manager = HeartbeatManager()

    # 写入心跳
    heartbeat = manager.write_heartbeat()

    # 显示心跳信息
    print("\n📊 心跳信息:")
    print(f"   Worker ID: {heartbeat['worker_id']}")
    print(f"   状态: {heartbeat['status']}")
    print(f"   CPU: {heartbeat.get('cpu_percent', 'N/A')}%")
    print(f"   内存: {heartbeat.get('memory_percent', 'N/A')}%")
    print(f"   磁盘: {heartbeat.get('disk_percent', 'N/A')}%")


if __name__ == '__main__':
    main()
