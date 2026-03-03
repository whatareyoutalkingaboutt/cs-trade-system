#!/usr/bin/env python3
"""
Celery 任务定义

定义所有的异步任务,包括:
- 数据采集任务
- 心跳检测任务
- 缓存清理任务
- 数据分析任务
"""

import os
import json
import gc
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from loguru import logger
from sqlalchemy import text

# 导入Celery应用实例
from backend.core.celery_app import celery_app
from backend.core.cache import (
    acquire_lock,
    allow_rate_limit,
    enqueue_high_priority_verify_candidate,
    get_dragonfly_client,
    get_high_priority_verify_queue_size,
    pop_high_priority_verify_candidates,
    release_lock,
)
from backend.core.database import get_sessionmaker
from backend.models import Item

# 导入爬虫
from backend.scrapers.steam_scraper import SteamMarketScraper
from backend.scrapers.buff_scraper import BuffScraper
from backend.scrapers.steamdt_price_scraper import SteamDTPriceScraper
from backend.scrapers.youpin_scraper import YoupinScraper
from backend.services.base_sync_service import sync_base_items
from backend.services.baseline_service import refresh_item_baselines
from backend.services.price_service import PriceRecord, write_price, write_prices_batch
from backend.services.steamdt_price_service import load_csqaq_goods_snapshot
from backend.services.arbitrage_service import (
    ARBITRAGE_RECHECK_RATE_LIMIT_KEY,
    ARBITRAGE_RECHECK_ROI_PCT,
    analyze_and_cache_opportunities,
    publish_opportunity_payloads,
    refresh_cache_if_needed,
    verify_single_high_roi_candidate,
)
from backend.services.anomaly_service import (
    detect_market_maker_behavior,
    detect_price_anomalies,
    run_data_integrity_check,
)
from backend.services.notification_service import notify_arbitrage_opportunities


def _fetch_youpin_with_fallback(item_name: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with YoupinScraper() as scraper:
            direct = scraper.get_price(item_name)
            if direct and direct.get("lowest_price") is not None:
                return (
                    {
                        "price": direct.get("lowest_price"),
                        "currency": direct.get("currency", "CNY"),
                        "timestamp": direct.get("timestamp"),
                        "volume": direct.get("volume"),
                        "sell_listings": direct.get("sell_listings"),
                    },
                    "direct_scraper",
                )
    except Exception as exc:
        logger.warning(f"[Task] Youpin直连失败: {item_name} - {exc}")

    try:
        with SteamDTPriceScraper() as scraper:
            steamdt = scraper.get_price(item_name)
            if steamdt and steamdt.get("youpin_price") is not None:
                return (
                    {
                        "price": steamdt.get("youpin_price"),
                        "currency": steamdt.get("currency", "CNY"),
                        "timestamp": steamdt.get("timestamp"),
                        "volume": steamdt.get("youpin_volume"),
                    },
                    "steamdt",
                )
    except Exception as exc:
        logger.warning(f"[Task] Youpin SteamDT保底失败: {item_name} - {exc}")

    return None, None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _compute_verify_candidate_score(candidate: Dict[str, Any]) -> float:
    profit_rate = _to_float(candidate.get("profit_rate"))
    net_profit = _to_float(candidate.get("net_profit"))
    buy_liquidity = _to_float(candidate.get("buy_liquidity"))
    sell_liquidity = _to_float(candidate.get("sell_liquidity"))
    dual_daily_volume = _to_float(candidate.get("dual_daily_volume"))

    age_seconds = 0.0
    ts_raw = candidate.get("calculated_at") or candidate.get("sell_time") or candidate.get("buy_time")
    if isinstance(ts_raw, str):
        try:
            ts_value = datetime.fromisoformat(ts_raw)
            if ts_value.tzinfo is None:
                ts_value = ts_value.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - ts_value.astimezone(timezone.utc)).total_seconds())
        except ValueError:
            age_seconds = 0.0

    return (
        (profit_rate * 1000.0)
        + (net_profit * 100.0)
        + (min(dual_daily_volume, 20000.0) * 0.1)
        + (min(buy_liquidity + sell_liquidity, 10000.0) * 0.5)
        - (age_seconds * 0.01)
    )


def _schedule_verify_task(candidate: Dict[str, Any]) -> bool:
    try:
        verify_and_alert_task.apply_async(
            kwargs={
                "opportunity": candidate,
                "min_profit_amount": float(os.getenv("ARBITRAGE_MIN_PROFIT_AMOUNT", "0") or 0),
                "min_profit_rate": float(os.getenv("ARBITRAGE_MIN_PROFIT_RATE", "0") or 0),
            },
            queue="verify",
        )
        return True
    except Exception as exc:
        logger.warning("[Task] enqueue verify task failed, item_id={}: {}", candidate.get("item_id"), exc)
        return False


def _dispatch_high_priority_verify_queue(max_dispatch: int = 1) -> Dict[str, int]:
    dispatch_limit = max(0, int(max_dispatch))
    if dispatch_limit <= 0:
        return {"popped": 0, "dispatched": 0, "requeued": 0, "pending": 0}

    try:
        candidates = pop_high_priority_verify_candidates(limit=dispatch_limit)
    except Exception as exc:
        logger.warning("[Task] pop high-priority verify queue failed: {}", exc)
        return {"popped": 0, "dispatched": 0, "requeued": 0, "pending": 0}

    dispatched = 0
    requeued = 0
    for candidate in candidates:
        if _schedule_verify_task(candidate):
            dispatched += 1
            continue
        try:
            if enqueue_high_priority_verify_candidate(
                candidate,
                score=_compute_verify_candidate_score(candidate),
            ):
                requeued += 1
        except Exception as exc:
            logger.warning(
                "[Task] requeue verify candidate failed, item_id={}: {}",
                candidate.get("item_id"),
                exc,
            )

    pending = 0
    try:
        pending = get_high_priority_verify_queue_size()
    except Exception as exc:
        logger.warning("[Task] get verify queue size failed: {}", exc)

    return {
        "popped": len(candidates),
        "dispatched": dispatched,
        "requeued": requeued,
        "pending": pending,
    }


# ==================== 单平台采集任务 ====================

@celery_app.task(
    name='backend.scrapers.celery_tasks.scrape_steam_price',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def scrape_steam_price(self, item_name: str, use_proxy: bool = True) -> Optional[Dict[str, Any]]:
    """
    采集Steam Market价格(单个饰品)

    参数:
        item_name: 饰品名称
        use_proxy: 是否使用代理

    返回:
        价格数据字典或None

    特性:
        - 自动重试(最多3次)
        - 失败后60秒重试
    """
    logger.info(f"[Task] 开始采集Steam价格: {item_name}")

    try:
        with SteamMarketScraper(use_proxy=use_proxy) as scraper:
            price_data = scraper.get_price(item_name)

        if price_data is None and use_proxy:
            logger.info("[Task] Steam价格代理失败,尝试直连: {}", item_name)
            with SteamMarketScraper(use_proxy=False) as scraper:
                price_data = scraper.get_price(item_name)

        if price_data:
            try:
                record = PriceRecord(
                    item_name=item_name,
                    platform="steam",
                    price=price_data.get("lowest_price") or 0.0,
                    currency=price_data.get("currency", "CNY"),
                    volume=price_data.get("volume"),
                    time=price_data.get("timestamp"),
                    data_source="scraper",
                )
                write_price(record)
                refresh_cache_if_needed()
            except Exception as write_error:
                logger.warning(f"[Task] Steam价格写入失败: {item_name} - {write_error}")

            logger.success(f"[Task] Steam价格采集成功: {item_name}")
            return price_data

        logger.warning(f"[Task] Steam价格采集失败: {item_name}")
        raise self.retry(exc=Exception("Failed to get price"))

    except Exception as e:
        logger.error(f"[Task] Steam价格采集异常: {item_name} - {e}")
        raise


@celery_app.task(
    name='backend.scrapers.celery_tasks.scrape_buff_price',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def scrape_buff_price(self, item_name: str) -> Optional[Dict[str, Any]]:
    """
    采集Buff价格(单个饰品)

    参数:
        item_name: 饰品名称

    返回:
        价格数据字典或None
    """
    logger.info(f"[Task] 开始采集Buff价格: {item_name}")

    try:
        with BuffScraper() as scraper:
            price_data = scraper.get_price(item_name)

            if price_data:
                try:
                    record = PriceRecord(
                        item_name=item_name,
                        platform="buff",
                        price=price_data.get("lowest_price") or 0.0,
                        currency=price_data.get("currency", "CNY"),
                        volume=price_data.get("volume"),
                        sell_listings=price_data.get("sell_listings"),
                        buy_orders=price_data.get("buy_orders"),
                        time=price_data.get("timestamp"),
                        data_source="direct_scraper",
                    )
                    write_price(record)
                    refresh_cache_if_needed()
                except Exception as write_error:
                    logger.warning(f"[Task] Buff价格写入失败: {item_name} - {write_error}")

                logger.success(f"[Task] Buff价格采集成功: {item_name}")
                return price_data
            else:
                logger.warning(f"[Task] Buff价格采集失败: {item_name}")
                raise self.retry(exc=Exception("Failed to get price"))

    except Exception as e:
        logger.error(f"[Task] Buff价格采集异常: {item_name} - {e}")
        raise


@celery_app.task(
    name='backend.scrapers.celery_tasks.scrape_youpin_price',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def scrape_youpin_price(self, item_name: str) -> Optional[Dict[str, Any]]:
    """
    采集Youpin价格(单个饰品)

    参数:
        item_name: 饰品名称

    返回:
        价格数据字典或None
    """
    logger.info(f"[Task] 开始采集Youpin价格: {item_name}")

    try:
        youpin_payload, data_source = _fetch_youpin_with_fallback(item_name)
        if youpin_payload is None:
            logger.warning(f"[Task] Youpin价格采集失败: {item_name}")
            raise self.retry(exc=Exception("Failed to get price"))

        try:
            record = PriceRecord(
                item_name=item_name,
                platform="youpin",
                price=youpin_payload.get("price") or 0.0,
                currency=youpin_payload.get("currency", "CNY"),
                volume=youpin_payload.get("volume"),
                sell_listings=youpin_payload.get("sell_listings"),
                time=youpin_payload.get("timestamp"),
                data_source=data_source or "steamdt",
            )
            write_price(record)
            refresh_cache_if_needed()
        except Exception as write_error:
            logger.warning(f"[Task] Youpin价格写入失败: {item_name} - {write_error}")

        logger.success(f"[Task] Youpin价格采集成功: {item_name}")
        return youpin_payload

    except Exception as e:
        logger.error(f"[Task] Youpin价格采集异常: {item_name} - {e}")
        raise

# ==================== 多平台采集任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.scrape_all_platforms')
def scrape_all_platforms(item_name: str) -> Dict[str, Any]:
    """
    同时采集所有平台的价格

    参数:
        item_name: 饰品名称

    返回:
        包含所有平台价格的字典:
        {
            'item_name': str,
            'steam': dict or None,
        'buff': dict or None,
        'youpin': dict or None,
        'timestamp': str
        }
    """
    logger.info(f"[Task] 开始采集所有平台价格: {item_name}")

    result = {
        'item_name': item_name,
        'steam': None,
        'buff': None,
        'youpin': None,
        'timestamp': datetime.now().isoformat()
    }

    # 1. 采集Steam价格(同步调用，避免 task.get)
    try:
        with SteamMarketScraper(use_proxy=True) as scraper:
            steam_data = scraper.get_price(item_name)
        if steam_data is None:
            with SteamMarketScraper(use_proxy=False) as scraper:
                steam_data = scraper.get_price(item_name)
        if steam_data:
            try:
                record = PriceRecord(
                    item_name=item_name,
                    platform="steam",
                    price=steam_data.get("lowest_price") or 0.0,
                    currency=steam_data.get("currency", "CNY"),
                    volume=steam_data.get("volume"),
                    time=steam_data.get("timestamp"),
                    data_source="scraper",
                )
                write_price(record)
                refresh_cache_if_needed()
            except Exception as write_error:
                logger.warning(f"[Task] Steam价格写入失败: {item_name} - {write_error}")
        result['steam'] = steam_data
    except Exception as e:
        logger.error(f"[Task] Steam采集失败: {e}")

    # 2. 采集Buff价格(同步调用)
    try:
        with BuffScraper() as scraper:
            buff_data = scraper.get_price(item_name)
        if buff_data:
            try:
                record = PriceRecord(
                    item_name=item_name,
                    platform="buff",
                    price=buff_data.get("lowest_price") or 0.0,
                    currency=buff_data.get("currency", "CNY"),
                    volume=buff_data.get("volume"),
                    sell_listings=buff_data.get("sell_listings"),
                    buy_orders=buff_data.get("buy_orders"),
                    time=buff_data.get("timestamp"),
                    data_source="direct_scraper",
                )
                write_price(record)
                refresh_cache_if_needed()
            except Exception as write_error:
                logger.warning(f"[Task] Buff价格写入失败: {item_name} - {write_error}")
        result['buff'] = buff_data
    except Exception as e:
        logger.error(f"[Task] Buff采集失败: {e}")

    # 3. 采集Youpin价格(直连优先, SteamDT保底)
    try:
        youpin_payload, youpin_source = _fetch_youpin_with_fallback(item_name)
        if youpin_payload is not None:
            try:
                record = PriceRecord(
                    item_name=item_name,
                    platform="youpin",
                    price=youpin_payload.get("price") or 0.0,
                    currency=youpin_payload.get("currency", "CNY"),
                    volume=youpin_payload.get("volume"),
                    sell_listings=youpin_payload.get("sell_listings"),
                    time=youpin_payload.get("timestamp"),
                    data_source=youpin_source or "steamdt",
                )
                write_price(record)
                refresh_cache_if_needed()
            except Exception as write_error:
                logger.warning(f"[Task] Youpin价格写入失败: {item_name} - {write_error}")
        result['youpin'] = youpin_payload
    except Exception as e:
        logger.error(f"[Task] Youpin采集失败: {e}")

    logger.success(f"[Task] 所有平台价格采集完成: {item_name}")
    return result


# ==================== 批量采集任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.scrape_items_by_priority')
def scrape_items_by_priority(priority: str) -> Dict[str, Any]:
    """
    按优先级采集饰品价格

    参数:
        priority: 优先级('high', 'medium', 'low')

    返回:
        采集结果统计:
        {
            'priority': str,
            'total_items': int,
            'success_count': int,
            'failed_count': int,
            'timestamp': str
        }
    """
    logger.info(f"[Task] 开始按优先级采集: {priority}")

    item_names = get_items_by_priority(priority)

    total = len(item_names)
    success = 0
    failed = 0

    for item_name in item_names:
        try:
            # 异步发起采集任务
            scrape_all_platforms.delay(item_name)
            success += 1
        except Exception as e:
            logger.error(f"[Task] 发起采集任务失败: {item_name} - {e}")
            failed += 1

    result = {
        'priority': priority,
        'total_items': total,
        'success_count': success,
        'failed_count': failed,
        'timestamp': datetime.now().isoformat()
    }

    logger.success(f"[Task] 优先级采集完成: {priority} - {success}/{total} 成功")
    return result


def get_items_by_priority(priority: str, limit: int = 200) -> List[str]:
    """
    按优先级从数据库读取启用中的饰品列表

    参数:
        priority: 优先级('high', 'medium', 'low')

    返回:
        饰品名称列表
    """
    normalized = (priority or "").strip().lower()
    session = get_sessionmaker()()
    try:
        query = session.query(Item.market_hash_name).filter(Item.is_active.is_(True))
        if normalized == "high":
            query = query.filter(Item.priority >= 8)
        elif normalized == "medium":
            query = query.filter(Item.priority >= 5, Item.priority <= 7)
        elif normalized == "low":
            query = query.filter(Item.priority <= 4)
        else:
            logger.warning(f"[Task] 未知优先级: {priority}")
            return []

        rows = (
            query.order_by(Item.priority.desc(), Item.id.asc())
            .limit(limit)
            .all()
        )
        return [row.market_hash_name for row in rows if row.market_hash_name]
    finally:
        session.close()


# ==================== Base 全量同步任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.sync_base_items')
def sync_base_items_task(page_size: int = 1000, max_pages: Optional[int] = None) -> Dict[str, Any]:
    """
    同步 SteamDT base 全量饰品库

    参数:
        page_size: 每页数量
        max_pages: 最大页数(用于调试)
    """
    logger.info("[Task] 开始同步 SteamDT base 饰品库...")
    result = sync_base_items(page_size=page_size, max_pages=max_pages)
    logger.success(
        "[Task] base 同步完成: "
        f"total={result.get('total', 0)}, "
        f"created={result.get('created', 0)}, "
        f"updated={result.get('updated', 0)}"
    )
    return result


@celery_app.task(
    name='backend.scrapers.celery_tasks.verify_and_alert_task',
    rate_limit='1/s',
)
def verify_and_alert_task(
    opportunity: Dict[str, Any],
    min_profit_amount: float = 0.0,
    min_profit_rate: float = 0.0,
) -> Dict[str, Any]:
    """
    高 ROI 机会二次复核后再报警。

    设计要点:
    - 任务级限频: 1次/秒
    - 全局额度门控: Redis 1次/秒
    - 仅复核通过才发布/通知
    """
    if not isinstance(opportunity, dict):
        return {
            "status": "skipped",
            "reason": "invalid_payload",
            "timestamp": datetime.now().isoformat(),
        }

    if not allow_rate_limit(ARBITRAGE_RECHECK_RATE_LIMIT_KEY, limit=1, window_seconds=1):
        return {
            "status": "skipped",
            "reason": "rate_limited",
            "item_id": opportunity.get("item_id"),
            "timestamp": datetime.now().isoformat(),
        }

    try:
        verified = verify_single_high_roi_candidate(
            opportunity_payload=opportunity,
            min_profit_amount=float(min_profit_amount or 0.0),
            min_profit_rate=float(min_profit_rate or 0.0),
        )
    except Exception as exc:
        logger.warning("[Task] verify_and_alert_task failed: {}", exc)
        return {
            "status": "error",
            "item_id": opportunity.get("item_id"),
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        }

    if not verified:
        return {
            "status": "rejected",
            "item_id": opportunity.get("item_id"),
            "timestamp": datetime.now().isoformat(),
        }

    published = publish_opportunity_payloads([verified], limit=1)
    notify_result = notify_arbitrage_opportunities(
        [verified],
        min_profit_rate=float(os.getenv("ARBITRAGE_VERIFY_NOTIFY_MIN_PROFIT_RATE", str(ARBITRAGE_RECHECK_ROI_PCT))),
        max_items=1,
    )
    return {
        "status": "verified_and_alerted",
        "item_id": verified.get("item_id"),
        "published_count": published,
        "notify_result": notify_result,
        "timestamp": datetime.now().isoformat(),
    }


@celery_app.task(name='backend.scrapers.celery_tasks.dispatch_high_priority_verify_queue')
def dispatch_high_priority_verify_queue(max_dispatch: int = 1) -> Dict[str, Any]:
    result = _dispatch_high_priority_verify_queue(max_dispatch=max_dispatch)
    result["timestamp"] = datetime.now().isoformat()
    return result


@celery_app.task(name='backend.scrapers.celery_tasks.refresh_item_baselines')
def refresh_item_baselines_task(
    only_active: bool = True,
    limit: Optional[int] = None,
    ttl_seconds: int = 7200,
) -> Dict[str, Any]:
    env_only_active = os.getenv("BASELINE_ONLY_ACTIVE", "").strip().lower()
    if env_only_active in {"1", "true", "yes", "on"}:
        only_active = True
    elif env_only_active in {"0", "false", "no", "off"}:
        only_active = False

    env_limit = os.getenv("BASELINE_REFRESH_LIMIT", "").strip()
    if env_limit:
        try:
            parsed = int(env_limit)
            limit = parsed if parsed > 0 else None
        except ValueError:
            pass

    env_ttl = os.getenv("BASELINE_TTL_SECONDS", "").strip()
    if env_ttl:
        try:
            ttl_seconds = max(60, int(env_ttl))
        except ValueError:
            pass

    return refresh_item_baselines(
        only_active=only_active,
        limit=limit,
        ttl_seconds=max(60, int(ttl_seconds)),
    )


@celery_app.task(name='backend.scrapers.celery_tasks.sync_csqaq_all_prices')
def sync_csqaq_all_prices(
    batch_size: int = 1000,
    max_buffer: int = 5000,
    only_active: bool = True,
    min_priority: Optional[int] = None,
    refresh_arbitrage: bool = True,
) -> Dict[str, Any]:
    """
    全量同步 CSQAQ 价格快照到 price_history（2GB 内存保护版）。

    设计要点:
    - 单任务互斥锁，避免并发重复写入
    - 有损缓冲区，超过上限直接丢弃后续切片
    - 批量写入，降低 DB IO 压力
    """
    lock_token = acquire_lock("lock:sync_csqaq_all_prices", ttl_seconds=280)
    if not lock_token:
        return {
            "status": "skipped",
            "reason": "lock_held",
            "timestamp": datetime.now().isoformat(),
        }

    queue_max = max(1, int(max_buffer))
    chunk_size = max(1, int(batch_size))
    env_batch = os.getenv("CSQAQ_SYNC_BATCH_SIZE", "").strip()
    if env_batch:
        try:
            chunk_size = max(1, int(env_batch))
        except ValueError:
            pass
    env_buffer = os.getenv("CSQAQ_SYNC_MAX_BUFFER", "").strip()
    if env_buffer:
        try:
            queue_max = max(1, int(env_buffer))
        except ValueError:
            pass

    env_only_active = os.getenv("CSQAQ_SYNC_ONLY_ACTIVE", "").strip().lower()
    if env_only_active in {"1", "true", "yes", "on"}:
        only_active = True
    elif env_only_active in {"0", "false", "no", "off"}:
        only_active = False
    queue: deque[PriceRecord] = deque()

    counters = {
        "rows_total": 0,
        "rows_parsed": 0,
        "rows_skipped": 0,
        "records_enqueued": 0,
        "records_written": 0,
        "records_dropped": 0,
        "flush_failures": 0,
    }

    def _flush_once() -> None:
        if not queue:
            return
        batch: list[PriceRecord] = []
        while queue and len(batch) < chunk_size:
            batch.append(queue.popleft())
        if not batch:
            return
        try:
            written = write_prices_batch(batch)
            counters["records_written"] += int(written)
        except Exception as exc:
            counters["flush_failures"] += 1
            counters["records_dropped"] += len(batch)
            logger.warning("[Task] CSQAQ flush failed, dropping batch: {}", exc)

    try:
        rows = load_csqaq_goods_snapshot(use_cache=False)
        counters["rows_total"] = len(rows)
        if not rows:
            return {
                "status": "ok",
                "message": "empty_snapshot",
                **counters,
                "timestamp": datetime.now().isoformat(),
            }

        session = get_sessionmaker()()
        try:
            item_rows = session.query(Item.id, Item.market_hash_name, Item.priority, Item.is_active).all()
        finally:
            session.close()

        item_map = {}
        for row in item_rows:
            item_id, market_hash_name, priority, is_active = row
            item_map[int(item_id)] = {
                "name": str(market_hash_name),
                "priority": int(priority or 0),
                "is_active": bool(is_active),
            }

        effective_min_priority = min_priority
        if effective_min_priority is None:
            raw = os.getenv("CSQAQ_SYNC_MIN_PRIORITY", "").strip()
            if raw:
                try:
                    effective_min_priority = int(raw)
                except ValueError:
                    effective_min_priority = None

        for row in rows:
            counters["rows_parsed"] += 1
            try:
                item_id = int(row.get("id"))
            except (TypeError, ValueError):
                counters["rows_skipped"] += 1
                continue

            meta = item_map.get(item_id)
            if not meta:
                counters["rows_skipped"] += 1
                continue
            if only_active and not meta["is_active"]:
                counters["rows_skipped"] += 1
                continue
            if effective_min_priority is not None and meta["priority"] < effective_min_priority:
                counters["rows_skipped"] += 1
                continue

            timestamp = row.get("updated_at")
            records: list[PriceRecord] = []
            buff_price = row.get("buff_sell_price")
            youpin_price = row.get("yyyp_sell_price")

            if buff_price is not None:
                records.append(
                    PriceRecord(
                        item_id=item_id,
                        item_name=meta["name"],
                        platform="buff",
                        price=float(buff_price),
                        currency="CNY",
                        volume=int(row.get("buff_sell_num") or 0),
                        sell_listings=int(row.get("buff_sell_num") or 0),
                        buy_orders=int(row.get("buff_buy_num") or 0),
                        time=timestamp,
                        data_source="csqaq_api",
                    )
                )
            if youpin_price is not None:
                records.append(
                    PriceRecord(
                        item_id=item_id,
                        item_name=meta["name"],
                        platform="youpin",
                        price=float(youpin_price),
                        currency="CNY",
                        volume=int(row.get("yyyp_sell_num") or 0),
                        sell_listings=int(row.get("yyyp_sell_num") or 0),
                        buy_orders=int(row.get("yyyp_buy_num") or 0),
                        time=timestamp,
                        data_source="csqaq_api",
                    )
                )

            for record in records:
                if len(queue) >= queue_max:
                    counters["records_dropped"] += 1
                    continue
                queue.append(record)
                counters["records_enqueued"] += 1

            if len(queue) >= chunk_size:
                _flush_once()

        while queue:
            _flush_once()

        # 显式释放全量快照大对象，降低 2G 内存环境下的驻留峰值
        rows.clear()
        del rows
        gc.collect()

        market_maker_result = None
        try:
            market_maker_result = detect_market_maker_behavior()
        except Exception as exc:
            logger.warning("[Task] Market maker detection failed: {}", exc)

        arbitrage_result = None
        if refresh_arbitrage:
            try:
                arbitrage_result = analyze_and_cache_opportunities(
                    verify_high_roi=False,
                    defer_high_roi_verify=True,
                )
                verify_candidates = arbitrage_result.pop("deferred_verify_candidates", [])
                verify_limit = max(
                    0,
                    int(os.getenv("ARBITRAGE_RECHECK_MAX_PER_RUN", "3")),
                )
                verify_enqueued_to_queue = 0
                verify_enqueued_direct_fallback = 0
                for candidate in verify_candidates[:verify_limit]:
                    score = _compute_verify_candidate_score(candidate)
                    queued = False
                    try:
                        queued = enqueue_high_priority_verify_candidate(candidate, score=score)
                    except Exception as exc:
                        logger.warning(
                            "[Task] enqueue high-priority verify candidate failed, item_id={}: {}",
                            candidate.get("item_id"),
                            exc,
                        )

                    if queued:
                        verify_enqueued_to_queue += 1
                        continue
                    if _schedule_verify_task(candidate):
                        verify_enqueued_direct_fallback += 1

                dispatch_per_run = max(
                    0,
                    int(os.getenv("ARBITRAGE_VERIFY_QUEUE_DISPATCH_PER_RUN", "1")),
                )
                dispatch_result = _dispatch_high_priority_verify_queue(max_dispatch=dispatch_per_run)
                arbitrage_result["verify_candidates"] = len(verify_candidates)
                arbitrage_result["verify_enqueued"] = (
                    verify_enqueued_to_queue + verify_enqueued_direct_fallback
                )
                arbitrage_result["verify_enqueued_to_queue"] = verify_enqueued_to_queue
                arbitrage_result["verify_enqueued_direct_fallback"] = verify_enqueued_direct_fallback
                arbitrage_result["verify_dispatched"] = dispatch_result.get("dispatched", 0)
                arbitrage_result["verify_queue_pending"] = dispatch_result.get("pending", 0)
            except Exception as exc:
                arbitrage_result = {"error": str(exc)}
                logger.warning("[Task] CSQAQ sync finished but arbitrage refresh failed: {}", exc)

        return {
            "status": "ok",
            **counters,
            "market_maker_result": market_maker_result,
            "arbitrage_result": arbitrage_result,
            "timestamp": datetime.now().isoformat(),
        }
    finally:
        if lock_token:
            release_lock("lock:sync_csqaq_all_prices", lock_token)


# ==================== 心跳检测任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.write_heartbeat')
def write_heartbeat() -> Dict[str, Any]:
    """
    写入心跳信号

    功能:
    - 每1分钟执行一次
    - 写入当前时间戳到DragonflyDB
    - 写入系统状态到TimescaleDB

    返回:
        心跳信息:
        {
            'timestamp': str,
            'status': 'healthy',
            'worker_id': str
        }
    """
    logger.info("[Task] 写入心跳信号...")
    now = datetime.now(timezone.utc)
    worker_id = os.getenv('WORKER_ID', 'worker-1')
    heartbeat = {
        'timestamp': now.isoformat(),
        'status': 'healthy',
        'worker_id': worker_id,
    }

    cache_ok = False
    db_ok = False

    try:
        client = get_dragonfly_client()
        cache_key = f"heartbeat:worker:{worker_id}"
        client.hset(
            cache_key,
            mapping={
                "timestamp": heartbeat["timestamp"],
                "status": heartbeat["status"],
                "worker_id": worker_id,
            },
        )
        client.expire(cache_key, 180)
        cache_ok = True
    except Exception as exc:
        logger.warning("[Task] Heartbeat cache write failed: {}", exc)

    session = get_sessionmaker()()
    try:
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
                "time": now,
                "component": "celery_worker",
                "instance_id": worker_id,
                "status": "healthy",
                "cpu_percent": None,
                "memory_percent": None,
                "active_tasks": 0,
                "metadata": json.dumps({"source": "celery_tasks.write_heartbeat"}, ensure_ascii=True),
            },
        )
        session.commit()
        db_ok = True
    except Exception as exc:
        session.rollback()
        logger.warning("[Task] Heartbeat DB write failed: {}", exc)
    finally:
        session.close()

    heartbeat["cache_written"] = cache_ok
    heartbeat["db_written"] = db_ok
    if cache_ok or db_ok:
        logger.success("[Task] 心跳信号写入完成")
        return heartbeat

    raise RuntimeError("heartbeat persistence failed")


# ==================== 缓存清理任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.cleanup_cache')
def cleanup_cache() -> Dict[str, Any]:
    """
    清理过期缓存

    功能:
    - 每天凌晨3点执行
    - 清理DragonflyDB中的过期数据
    - 清理临时文件

    返回:
        清理结果:
        {
            'cache_cleaned': int,
            'files_deleted': int,
            'timestamp': str
        }
    """
    logger.info("[Task] 开始清理过期缓存...")
    now = datetime.now(timezone.utc)
    result = {
        'cache_cleaned': 0,
        'files_deleted': 0,
        'timestamp': now.isoformat(),
    }

    try:
        stale_seconds = max(60, int(os.getenv("HEARTBEAT_STALE_SECONDS", "600")))
        cutoff = now - timedelta(seconds=stale_seconds)
        client = get_dragonfly_client()
        for key in client.scan_iter(match="heartbeat:worker:*", count=200):
            payload = client.hgetall(key)
            ts_raw = payload.get("timestamp") if payload else None
            if not ts_raw:
                client.delete(key)
                result["cache_cleaned"] += 1
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                client.delete(key)
                result["cache_cleaned"] += 1
                continue
            if ts < cutoff:
                client.delete(key)
                result["cache_cleaned"] += 1

        temp_dir = Path("/tmp")
        tmp_cutoff = datetime.now() - timedelta(days=1)
        for file_path in temp_dir.glob("cs_item_scraper_*"):
            try:
                if file_path.is_file():
                    modified_at = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if modified_at < tmp_cutoff:
                        file_path.unlink(missing_ok=True)
                        result["files_deleted"] += 1
            except Exception as exc:
                logger.debug("[Task] Skip temp cleanup for {}: {}", file_path, exc)

        logger.success(
            "[Task] 缓存清理完成: cache_cleaned={}, files_deleted={}",
            result["cache_cleaned"],
            result["files_deleted"],
        )
        return result
    except Exception as exc:
        logger.error("[Task] 缓存清理失败: {}", exc)
        raise


# ==================== 数据分析任务 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.analyze_arbitrage_opportunities')
def analyze_arbitrage_opportunities() -> Dict[str, Any]:
    """
    分析套利机会

    功能:
    - 对比Steam和Buff价格
    - 计算价差和利润率
    - 筛选出有效的套利机会

    返回:
        套利机会列表
    """
    logger.info("[Task] 开始分析套利机会...")

    result = analyze_and_cache_opportunities()

    logger.success(
        "[Task] 套利分析完成: "
        f"found={result.get('opportunities_found', 0)}, "
        f"cached={result.get('cached_count', 0)}"
    )
    return result


@celery_app.task(name='backend.scrapers.celery_tasks.detect_price_anomalies')
def detect_price_anomalies_task() -> Dict[str, Any]:
    """
    检测价格异常

    功能:
    - 检测暴涨/暴跌
    - 检测超历史最高价
    - 发布告警事件
    """
    logger.info("[Task] 开始检测价格异常...")

    result = detect_price_anomalies()

    logger.success(
        "[Task] 价格异常检测完成: "
        f"anomalies={result.get('anomalies_found', 0)}, "
        f"published={result.get('published_count', 0)}"
    )
    return result


@celery_app.task(name='backend.scrapers.celery_tasks.check_data_integrity')
def check_data_integrity_task() -> Dict[str, Any]:
    """
    数据完整性检查

    功能:
    - 检测数据缺口
    - 生成质量报告
    - 写入缺口日志
    """
    logger.info("[Task] 开始数据完整性检查...")

    result = run_data_integrity_check()

    logger.success(
        "[Task] 数据完整性检查完成: "
        f"gaps={result.get('gaps_found', 0)}, "
        f"missing_items={len(result.get('missing_items', []))}"
    )
    return result


# ==================== 工具函数 ====================

@celery_app.task(name='backend.scrapers.celery_tasks.test_task')
def test_task(message: str = "Hello from Celery!") -> str:
    """
    测试任务

    用于验证Celery配置是否正常工作
    """
    logger.info(f"[Task] 测试任务执行: {message}")
    return f"Task completed: {message}"
