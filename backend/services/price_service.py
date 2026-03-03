from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from loguru import logger
from sqlalchemy import insert, select

from backend.core.cache import cache_latest_price, cache_latest_price_snapshot, get_latest_price_snapshot
from backend.core.database import get_sessionmaker
from backend.models import Item, PriceHistory


QUALITY_SCORE_BY_SOURCE = {
    "scraper": 100,
    "historical_import": 95,
    "interpolated": 80,
    "estimated": 60,
    "manual_import": 90,
    "steamdt": 95,
    "third_party_realtime": 95,
}
ESTIMATED_SOURCES = {"interpolated", "estimated"}


@dataclass(frozen=True)
class PriceRecord:
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    platform: str = ""
    price: float = 0.0
    currency: str = "CNY"
    volume: Optional[int] = None
    sell_listings: Optional[int] = None
    buy_orders: Optional[int] = None
    time: Optional[datetime] = None
    data_source: str = "scraper"
    is_estimated: Optional[bool] = None
    is_baseline: bool = False
    quality_score: Optional[int] = None


def _resolve_item_id(session, item_id: Optional[int], item_name: Optional[str]) -> int:
    if item_id is not None:
        return item_id
    if not item_name:
        raise ValueError("item_id or item_name is required")
    value = session.execute(
        select(Item.id).where(Item.market_hash_name == item_name)
    ).scalar_one_or_none()
    if value is None:
        raise ValueError(f"item_name not found: {item_name}")
    return value


def _parse_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _resolve_item_name_by_id(session, item_id: int) -> str:
    value = session.execute(
        select(Item.market_hash_name).where(Item.id == item_id)
    ).scalar_one_or_none()
    if value is None:
        raise ValueError(f"item_id not found: {item_id}")
    return str(value)


def _quality_fields(
    data_source: str,
    quality_score: Optional[int],
    is_estimated: Optional[bool],
    is_baseline: bool,
) -> tuple[int, bool, bool]:
    resolved_score = quality_score
    if resolved_score is None:
        resolved_score = QUALITY_SCORE_BY_SOURCE.get(data_source, 100)
    resolved_estimated = is_estimated
    if resolved_estimated is None:
        resolved_estimated = data_source in ESTIMATED_SOURCES
    return resolved_score, resolved_estimated, is_baseline


def _cache_latest(
    item_id: int,
    market_hash_name: str,
    platform: str,
    price: float,
    currency: str,
    timestamp: datetime,
    volume: Optional[int],
    sell_listings: Optional[int],
    buy_orders: Optional[int],
    data_source: str,
    quality_score: int,
    is_estimated: bool,
    is_baseline: bool,
) -> None:
    payload = {
        "item_id": str(item_id),
        "market_hash_name": market_hash_name,
        "platform": platform,
        "price": str(price),
        "currency": currency,
        "timestamp": timestamp.isoformat(),
        "data_source": data_source,
        "quality_score": str(quality_score),
        "is_estimated": str(is_estimated),
        "is_baseline": str(is_baseline),
    }
    if volume is not None:
        payload["volume"] = str(volume)
    if sell_listings is not None:
        payload["sell_listings"] = str(sell_listings)
    if buy_orders is not None:
        payload["buy_orders"] = str(buy_orders)
    cache_latest_price(item_id, payload, platform=platform)

    snapshot_payload = get_latest_price_snapshot(market_hash_name) or {}
    if not isinstance(snapshot_payload, dict):
        snapshot_payload = {}
    snapshot_payload["item_id"] = str(item_id)
    snapshot_payload["market_hash_name"] = market_hash_name
    snapshot_payload["updated_at"] = timestamp.isoformat()
    platform_payload: dict[str, Any] = {
        "price": float(price),
        "currency": currency,
        "timestamp": timestamp.isoformat(),
    }
    if volume is not None:
        platform_payload["volume"] = int(volume)
    if sell_listings is not None:
        platform_payload["sell_listings"] = int(sell_listings)
    if buy_orders is not None:
        platform_payload["buy_orders"] = int(buy_orders)
    snapshot_payload[platform] = platform_payload
    cache_latest_price_snapshot(market_hash_name, snapshot_payload)


def _validate_record(record: PriceRecord) -> None:
    if not record.platform:
        raise ValueError("platform is required")


def write_price(record: PriceRecord) -> PriceHistory:
    _validate_record(record)
    session = get_sessionmaker()()
    try:
        item_id = _resolve_item_id(session, record.item_id, record.item_name)
        market_hash_name = (record.item_name or "").strip()
        if not market_hash_name:
            market_hash_name = _resolve_item_name_by_id(session, item_id)
        timestamp = _parse_time(record.time)
        quality_score, is_estimated, is_baseline = _quality_fields(
            record.data_source,
            record.quality_score,
            record.is_estimated,
            record.is_baseline,
        )

        price_row = PriceHistory(
            time=timestamp,
            item_id=item_id,
            platform=record.platform,
            price=record.price,
            currency=record.currency,
            volume=record.volume or 0,
            sell_listings=record.sell_listings,
            buy_orders=record.buy_orders,
            data_source=record.data_source,
            is_estimated=is_estimated,
            is_baseline=is_baseline,
            quality_score=quality_score,
        )
        session.add(price_row)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    try:
        _cache_latest(
            item_id=item_id,
            market_hash_name=market_hash_name,
            platform=record.platform,
            price=record.price,
            currency=record.currency,
            timestamp=timestamp,
            volume=record.volume,
            sell_listings=record.sell_listings,
            buy_orders=record.buy_orders,
            data_source=record.data_source,
            quality_score=quality_score,
            is_estimated=is_estimated,
            is_baseline=is_baseline,
        )
    except Exception as exc:
        logger.warning("Latest price cache update failed for item {}: {}", item_id, exc)

    return price_row


def write_prices_batch(records: Iterable[PriceRecord]) -> int:
    session = get_sessionmaker()()
    rows: list[dict[str, Any]] = []
    cache_payloads: list[dict[str, Any]] = []
    item_name_cache: dict[int, str] = {}
    try:
        for record in records:
            _validate_record(record)
            item_id = _resolve_item_id(session, record.item_id, record.item_name)
            market_hash_name = (record.item_name or "").strip()
            if not market_hash_name:
                market_hash_name = item_name_cache.get(item_id, "")
            if not market_hash_name:
                market_hash_name = _resolve_item_name_by_id(session, item_id)
                item_name_cache[item_id] = market_hash_name
            timestamp = _parse_time(record.time)
            quality_score, is_estimated, is_baseline = _quality_fields(
                record.data_source,
                record.quality_score,
                record.is_estimated,
                record.is_baseline,
            )
            rows.append(
                {
                    "time": timestamp,
                    "item_id": item_id,
                    "platform": record.platform,
                    "price": record.price,
                    "currency": record.currency,
                    "volume": record.volume or 0,
                    "sell_listings": record.sell_listings,
                    "buy_orders": record.buy_orders,
                    "data_source": record.data_source,
                    "is_estimated": is_estimated,
                    "is_baseline": is_baseline,
                    "quality_score": quality_score,
                }
            )
            cache_payloads.append(
                {
                    "item_id": item_id,
                    "market_hash_name": market_hash_name,
                    "platform": record.platform,
                    "price": record.price,
                    "currency": record.currency,
                    "timestamp": timestamp,
                    "volume": record.volume,
                    "sell_listings": record.sell_listings,
                    "buy_orders": record.buy_orders,
                    "data_source": record.data_source,
                    "quality_score": quality_score,
                    "is_estimated": is_estimated,
                    "is_baseline": is_baseline,
                }
            )

        if rows:
            session.execute(insert(PriceHistory), rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    for payload in cache_payloads:
        try:
            _cache_latest(**payload)
        except Exception as exc:
            logger.warning(
                "Latest price batch cache update failed for item {}: {}",
                payload.get("item_id"),
                exc,
            )

    return len(rows)
