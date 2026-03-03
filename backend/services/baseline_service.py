from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, select

from backend.core.cache import BASELINE_TTL_SECONDS, cache_item_baseline
from backend.core.database import get_sessionmaker
from backend.models import Item, PriceHistory


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def refresh_item_baselines(
    only_active: bool = True,
    limit: Optional[int] = None,
    ttl_seconds: int = BASELINE_TTL_SECONDS,
) -> dict:
    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_1h = now - timedelta(hours=1)

    session = get_sessionmaker()()
    try:
        item_stmt = select(Item.id, Item.market_hash_name)
        if only_active:
            item_stmt = item_stmt.where(Item.is_active.is_(True))
        item_stmt = item_stmt.order_by(Item.priority.desc(), Item.id.asc())
        if limit is not None and limit > 0:
            item_stmt = item_stmt.limit(int(limit))
        item_rows = session.execute(item_stmt).all()
        if not item_rows:
            return {
                "status": "ok",
                "items_selected": 0,
                "items_cached": 0,
                "timestamp": now.isoformat(),
            }

        item_ids = [int(row.id) for row in item_rows]

        avg_price_rows = session.execute(
            select(
                PriceHistory.item_id,
                PriceHistory.platform,
                func.avg(PriceHistory.price).label("avg_price_7d"),
            )
            .where(
                PriceHistory.item_id.in_(item_ids),
                PriceHistory.platform.in_(("buff", "youpin")),
                PriceHistory.time >= cutoff_7d,
            )
            .group_by(PriceHistory.item_id, PriceHistory.platform)
        ).all()

        avg_volume_rows = session.execute(
            select(
                PriceHistory.item_id,
                PriceHistory.platform,
                func.avg(PriceHistory.volume).label("avg_volume_1h"),
            )
            .where(
                PriceHistory.item_id.in_(item_ids),
                PriceHistory.platform.in_(("buff", "youpin")),
                PriceHistory.time >= cutoff_1h,
            )
            .group_by(PriceHistory.item_id, PriceHistory.platform)
        ).all()
    finally:
        session.close()

    price_map: dict[int, dict[str, Optional[float]]] = {}
    for row in avg_price_rows:
        item_id = int(row.item_id)
        platform = str(row.platform)
        price_map.setdefault(item_id, {})[platform] = _safe_float(row.avg_price_7d)

    volume_map: dict[int, dict[str, Optional[float]]] = {}
    for row in avg_volume_rows:
        item_id = int(row.item_id)
        platform = str(row.platform)
        volume_map.setdefault(item_id, {})[platform] = _safe_float(row.avg_volume_1h)

    cached = 0
    for row in item_rows:
        item_id = int(row.id)
        market_hash_name = str(row.market_hash_name or "").strip()
        if not market_hash_name:
            continue

        price_by_platform = {
            "buff": price_map.get(item_id, {}).get("buff"),
            "youpin": price_map.get(item_id, {}).get("youpin"),
        }
        volume_by_platform = {
            "buff": volume_map.get(item_id, {}).get("buff"),
            "youpin": volume_map.get(item_id, {}).get("youpin"),
        }
        overall_price_candidates = [
            value for value in price_by_platform.values() if value is not None
        ]
        overall_price_7d = (
            round(sum(overall_price_candidates) / len(overall_price_candidates), 4)
            if overall_price_candidates
            else None
        )
        payload = {
            "item_id": item_id,
            "market_hash_name": market_hash_name,
            "as_of": now.isoformat(),
            "window": {
                "price_avg": "7d",
                "volume_avg": "1h",
            },
            "price_7d_avg": price_by_platform,
            "volume_1h_avg": volume_by_platform,
            "overall_price_7d_avg": overall_price_7d,
        }
        cache_item_baseline(
            market_hash_name=market_hash_name,
            baseline_payload=payload,
            ttl=ttl_seconds,
        )
        cached += 1

    logger.info(
        "[Baseline] refreshed item baselines: selected={}, cached={}",
        len(item_rows),
        cached,
    )
    return {
        "status": "ok",
        "items_selected": len(item_rows),
        "items_cached": cached,
        "timestamp": now.isoformat(),
    }
