from __future__ import annotations

import os
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from itertools import permutations
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import and_, func, select

from backend.core.cache import (
    ARBITRAGE_TTL_SECONDS,
    allow_rate_limit,
    cache_arbitrage_opportunities,
    get_dragonfly_client,
)
from backend.core.database import get_sessionmaker
from backend.models import Item, PlatformConfig, PriceHistory
from backend.scrapers.csqaq_scraper import CSQAQScraper
from backend.services.notification_service import notify_arbitrage_opportunities
from backend.services.steamdt_price_service import load_csqaq_goods_snapshot


DEFAULT_FEE_RATES: dict[str, tuple[float, float]] = {
    "steam": (0.0, 0.15),
    "buff": (0.025, 0.025),
    "youpin": (0.0, 0.01),
    "c5game": (0.02, 0.02),
}
DEFAULT_MAX_AGE_MINUTES = 60
DEFAULT_MIN_PROFIT_AMOUNT = 0.0
DEFAULT_MIN_PROFIT_RATE = 0.0
DEFAULT_SCORE_BY = "net_profit"
DEFAULT_PUBLISH_CHANNEL = "arbitrage:opportunities:channel"
DEFAULT_PUBLISH_LIMIT = 50

REFRESH_LOCK_KEY = "arbitrage:refresh_lock"
REFRESH_LOCK_SECONDS = 30

ARBITRAGE_SOURCE = os.getenv("ARBITRAGE_SOURCE", "csqaq").strip().lower()
ARBITRAGE_DIRECTION = os.getenv("ARBITRAGE_DIRECTION", "youpin_to_buff").strip().lower()
ARBITRAGE_MIN_LIQUIDITY = int(os.getenv("ARBITRAGE_MIN_LIQUIDITY", "10"))
ARBITRAGE_MAX_SPREAD_RATIO_PCT = float(os.getenv("ARBITRAGE_MAX_SPREAD_RATIO_PCT", "15.0"))
ARBITRAGE_WITHDRAWAL_RATE = float(os.getenv("ARBITRAGE_WITHDRAWAL_RATE", "0.99"))
ARBITRAGE_MIN_BUFF_BUY_ORDERS = int(os.getenv("ARBITRAGE_MIN_BUFF_BUY_ORDERS", "30"))
ARBITRAGE_MAX_BUFF_SELL_BUY_RATIO = float(os.getenv("ARBITRAGE_MAX_BUFF_SELL_BUY_RATIO", "8.0"))
ARBITRAGE_MIN_BUFF_BUY_TO_YOUPIN_SELL_RATIO = float(
    os.getenv("ARBITRAGE_MIN_BUFF_BUY_TO_YOUPIN_SELL_RATIO", "0.2")
)
ARBITRAGE_RECHECK_ROI_PCT = float(os.getenv("ARBITRAGE_RECHECK_ROI_PCT", "20.0"))
ARBITRAGE_RECHECK_MAX_PER_RUN = int(os.getenv("ARBITRAGE_RECHECK_MAX_PER_RUN", "3"))
ARBITRAGE_STRICT_RECHECK = os.getenv("ARBITRAGE_STRICT_RECHECK", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ARBITRAGE_RECHECK_RATE_LIMIT_KEY = "quota:csqaq:verify:sec"
ARBITRAGE_LIQUIDITY_TRAP_MIN_DUAL_DAILY_VOLUME = float(
    os.getenv("ARBITRAGE_LIQUIDITY_TRAP_MIN_DUAL_DAILY_VOLUME", "10")
)
ARBITRAGE_MAIN_POOL_MIN_DUAL_DAILY_VOLUME = float(
    os.getenv("ARBITRAGE_MAIN_POOL_MIN_DUAL_DAILY_VOLUME", "1500")
)
ARBITRAGE_TIER_LIGHT_MIN_SPREAD_PCT = float(os.getenv("ARBITRAGE_TIER_LIGHT_MIN_SPREAD_PCT", "3"))
ARBITRAGE_TIER_MEDIUM_MIN_SPREAD_PCT = float(os.getenv("ARBITRAGE_TIER_MEDIUM_MIN_SPREAD_PCT", "5"))
ARBITRAGE_TIER_ANOMALY_MIN_SPREAD_PCT = float(os.getenv("ARBITRAGE_TIER_ANOMALY_MIN_SPREAD_PCT", "8"))
ARBITRAGE_DRAWDOWN_STOP_SPREAD_PCT = float(os.getenv("ARBITRAGE_DRAWDOWN_STOP_SPREAD_PCT", "1.2"))
ARBITRAGE_STICKER_MIN_NET_PROFIT = float(os.getenv("ARBITRAGE_STICKER_MIN_NET_PROFIT", "0.5"))
ARBITRAGE_CASE_CONFIRM_ENABLED = os.getenv("ARBITRAGE_CASE_CONFIRM_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ARBITRAGE_CASE_CONFIRM_CONSECUTIVE_HOURS = int(os.getenv("ARBITRAGE_CASE_CONFIRM_CONSECUTIVE_HOURS", "2"))
ARBITRAGE_CASE_CONFIRM_LOOKBACK_HOURS = int(os.getenv("ARBITRAGE_CASE_CONFIRM_LOOKBACK_HOURS", "6"))


@dataclass(frozen=True)
class PriceSnapshot:
    item_id: int
    item_name: str
    item_name_en: Optional[str]
    platform: str
    price: float
    currency: str
    time: datetime
    volume: Optional[int] = None
    sell_listings: Optional[int] = None
    buy_orders: Optional[int] = None


@dataclass(frozen=True)
class ArbitrageOpportunity:
    item_id: int
    item_name: str
    item_name_en: Optional[str]
    buy_platform: str
    sell_platform: str
    buy_price: float
    sell_price: float
    buy_fee_rate: float
    sell_fee_rate: float
    buy_cost: float
    sell_revenue: float
    net_profit: float
    profit_rate: float
    currency: str
    buy_time: datetime
    sell_time: datetime
    calculated_at: datetime
    spread_ratio_pct: Optional[float] = None
    buy_liquidity: Optional[int] = None
    sell_liquidity: Optional[int] = None
    verify_status: Optional[str] = None
    strategy: Optional[str] = None
    cross_spread_pct: Optional[float] = None
    signal_tier: Optional[str] = None
    recommended_position: Optional[str] = None
    stop_add: Optional[bool] = None
    dual_daily_volume: Optional[float] = None
    item_category: Optional[str] = None


def _to_float(value) -> float:
    return float(value) if value is not None else 0.0


def _round_currency(value: float) -> float:
    return round(value, 2)


def _load_platform_fees(session, platforms: Optional[Iterable[str]] = None) -> dict[str, tuple[float, float]]:
    stmt = select(PlatformConfig.platform, PlatformConfig.buy_fee_rate, PlatformConfig.sell_fee_rate)
    if platforms:
        stmt = stmt.where(PlatformConfig.platform.in_(platforms))
    rows = session.execute(stmt).all()

    fee_map: dict[str, tuple[float, float]] = {**DEFAULT_FEE_RATES}
    for platform, buy_fee, sell_fee in rows:
        fee_map[str(platform)] = (_to_float(buy_fee), _to_float(sell_fee))
    return fee_map


def _load_item_name_map(
    session,
    item_ids: Optional[set[int]] = None,
) -> dict[int, dict[str, str]]:
    stmt = select(Item.id, Item.market_hash_name, Item.name_cn, Item.type)
    if item_ids:
        stmt = stmt.where(Item.id.in_(item_ids))
    rows = session.execute(stmt).all()

    item_name_map: dict[int, dict[str, str]] = {}
    for item_id, market_hash_name, name_cn, item_type in rows:
        item_id_int = int(item_id)
        item_name_en = str(market_hash_name or "").strip()
        item_name_cn = str(name_cn or "").strip()
        item_name_map[item_id_int] = {
            "display": item_name_cn or item_name_en,
            "english": item_name_en,
            "type": str(item_type or "").strip(),
        }
    return item_name_map


def _latest_price_snapshots(
    session,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    platforms: Optional[Iterable[str]] = None,
    item_ids: Optional[Iterable[int]] = None,
) -> list[PriceSnapshot]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    subquery = (
        select(
            PriceHistory.item_id.label("item_id"),
            PriceHistory.platform.label("platform"),
            func.max(PriceHistory.time).label("max_time"),
        )
        .where(PriceHistory.time >= cutoff)
        .group_by(PriceHistory.item_id, PriceHistory.platform)
        .subquery()
    )

    stmt = (
        select(
            PriceHistory.item_id,
            Item.market_hash_name,
            Item.name_cn,
            PriceHistory.platform,
            PriceHistory.price,
            PriceHistory.currency,
            PriceHistory.time,
            PriceHistory.volume,
            PriceHistory.sell_listings,
            PriceHistory.buy_orders,
        )
        .join(Item, Item.id == PriceHistory.item_id)
        .join(
            subquery,
            and_(
                PriceHistory.item_id == subquery.c.item_id,
                PriceHistory.platform == subquery.c.platform,
                PriceHistory.time == subquery.c.max_time,
            ),
        )
    )

    if platforms:
        stmt = stmt.where(PriceHistory.platform.in_(platforms))
    if item_ids:
        stmt = stmt.where(PriceHistory.item_id.in_(item_ids))

    rows = session.execute(stmt).all()
    snapshots: list[PriceSnapshot] = []
    for item_id, item_name_en, item_name_cn, platform, price, currency, time_value, volume, sell_listings, buy_orders in rows:
        normalized_name_en = str(item_name_en or "").strip()
        normalized_name_cn = str(item_name_cn or "").strip()
        snapshots.append(
            PriceSnapshot(
                item_id=int(item_id),
                item_name=normalized_name_cn or normalized_name_en,
                item_name_en=normalized_name_en or None,
                platform=str(platform),
                price=_to_float(price),
                currency=str(currency),
                time=time_value,
                volume=int(volume) if volume is not None else None,
                sell_listings=int(sell_listings) if sell_listings is not None else None,
                buy_orders=int(buy_orders) if buy_orders is not None else None,
            )
        )
    return snapshots


def _build_opportunities(
    snapshots: Iterable[PriceSnapshot],
    fee_map: dict[str, tuple[float, float]],
    min_profit_amount: float,
    min_profit_rate: float,
    include_all_pairs: bool,
) -> list[ArbitrageOpportunity]:
    grouped: dict[int, dict[str, PriceSnapshot]] = {}
    for snap in snapshots:
        grouped.setdefault(snap.item_id, {})[snap.platform] = snap

    opportunities: list[ArbitrageOpportunity] = []
    calculated_at = datetime.now(timezone.utc)

    for item_id, platforms in grouped.items():
        if len(platforms) < 2:
            continue

        candidate_pairs = []
        for buy_platform, sell_platform in permutations(platforms.keys(), 2):
            buy_snapshot = platforms[buy_platform]
            sell_snapshot = platforms[sell_platform]

            if buy_snapshot.currency != sell_snapshot.currency:
                continue
            if buy_snapshot.price <= 0 or sell_snapshot.price <= 0:
                continue

            buy_fee_rate, _ = fee_map.get(buy_platform, DEFAULT_FEE_RATES.get(buy_platform, (0.0, 0.0)))
            _, sell_fee_rate = fee_map.get(sell_platform, DEFAULT_FEE_RATES.get(sell_platform, (0.0, 0.0)))

            buy_cost = buy_snapshot.price * (1 + buy_fee_rate)
            sell_revenue = sell_snapshot.price * (1 - sell_fee_rate)
            net_profit = sell_revenue - buy_cost
            if buy_cost <= 0:
                continue

            profit_rate = (net_profit / buy_cost) * 100

            opportunity = ArbitrageOpportunity(
                item_id=item_id,
                item_name=buy_snapshot.item_name,
                item_name_en=buy_snapshot.item_name_en,
                buy_platform=buy_platform,
                sell_platform=sell_platform,
                buy_price=buy_snapshot.price,
                sell_price=sell_snapshot.price,
                buy_fee_rate=buy_fee_rate,
                sell_fee_rate=sell_fee_rate,
                buy_cost=buy_cost,
                sell_revenue=sell_revenue,
                net_profit=net_profit,
                profit_rate=profit_rate,
                currency=buy_snapshot.currency,
                buy_time=buy_snapshot.time,
                sell_time=sell_snapshot.time,
                calculated_at=calculated_at,
                buy_liquidity=buy_snapshot.sell_listings,
                sell_liquidity=sell_snapshot.buy_orders,
                strategy="legacy_bidirectional",
            )
            candidate_pairs.append(opportunity)

        if not candidate_pairs:
            continue

        filtered = [
            opp
            for opp in candidate_pairs
            if opp.net_profit > 0
            and opp.net_profit >= min_profit_amount
            and opp.profit_rate >= min_profit_rate
        ]
        if not filtered:
            continue

        if include_all_pairs:
            opportunities.extend(filtered)
            continue

        best = max(filtered, key=lambda opp: opp.net_profit)
        opportunities.append(best)

    return opportunities


def rank_opportunities(
    opportunities: Iterable[ArbitrageOpportunity],
    sort_by: str = DEFAULT_SCORE_BY,
) -> list[ArbitrageOpportunity]:
    if sort_by not in {"net_profit", "profit_rate"}:
        raise ValueError("sort_by must be 'net_profit' or 'profit_rate'")
    return sorted(
        opportunities,
        key=lambda opp: getattr(opp, sort_by),
        reverse=True,
    )


def _safe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        try:
            ts = datetime.fromisoformat(value)
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _hour_bucket(ts: datetime) -> datetime:
    value = ts.astimezone(timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


def _cross_spread_pct(buy_price: Optional[float], sell_price: Optional[float]) -> Optional[float]:
    if buy_price is None or sell_price is None or buy_price <= 0:
        return None
    return (sell_price - buy_price) / buy_price * 100.0


def _passes_buff_liquidity_guard(
    youpin_sell_num: Optional[int],
    buff_buy_num: Optional[int],
    buff_sell_num: Optional[int],
) -> bool:
    buff_buy = int(buff_buy_num or 0)
    if buff_buy < ARBITRAGE_MIN_BUFF_BUY_ORDERS:
        return False

    buff_sell = int(buff_sell_num or 0)
    if buff_sell > 0 and (buff_sell / max(1, buff_buy)) > ARBITRAGE_MAX_BUFF_SELL_BUY_RATIO:
        return False

    youpin_sell = int(youpin_sell_num or 0)
    if youpin_sell > 0:
        buy_to_sell_ratio = buff_buy / max(1, youpin_sell)
        if buy_to_sell_ratio < ARBITRAGE_MIN_BUFF_BUY_TO_YOUPIN_SELL_RATIO:
            return False

    return True


def _resolve_signal_tier(cross_spread_pct: Optional[float]) -> tuple[Optional[str], Optional[str], Optional[float]]:
    if cross_spread_pct is None:
        return None, None, None
    if cross_spread_pct < ARBITRAGE_TIER_LIGHT_MIN_SPREAD_PCT:
        return None, None, None
    if cross_spread_pct < ARBITRAGE_TIER_MEDIUM_MIN_SPREAD_PCT:
        return "light", "0.25x", ARBITRAGE_TIER_LIGHT_MIN_SPREAD_PCT
    if cross_spread_pct < ARBITRAGE_TIER_ANOMALY_MIN_SPREAD_PCT:
        return "medium", "0.5x", ARBITRAGE_TIER_MEDIUM_MIN_SPREAD_PCT
    return "anomaly", "blocked", ARBITRAGE_TIER_ANOMALY_MIN_SPREAD_PCT


def _normalize_item_category(
    item_name: Optional[str],
    item_name_en: Optional[str],
    item_type: Optional[str],
) -> str:
    text = " ".join(
        [
            str(item_name or ""),
            str(item_name_en or ""),
            str(item_type or ""),
        ]
    ).strip().lower()
    if not text:
        return "other"

    if "sticker" in text or "印花" in text or "贴纸" in text:
        return "sticker"

    if "武器箱" in text or "case" in text:
        return "case"

    return "other"


def _load_dual_daily_volume_map(session, item_ids: set[int]) -> dict[int, float]:
    if not item_ids:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = session.execute(
        select(
            PriceHistory.item_id,
            PriceHistory.platform,
            func.avg(PriceHistory.volume).label("avg_volume"),
        )
        .where(
            PriceHistory.item_id.in_(item_ids),
            PriceHistory.platform.in_(("buff", "youpin")),
            PriceHistory.time >= cutoff,
        )
        .group_by(PriceHistory.item_id, PriceHistory.platform)
    ).all()

    per_item: dict[int, dict[str, float]] = {}
    for item_id, platform, avg_volume in rows:
        key = int(item_id)
        platform_key = str(platform)
        per_item.setdefault(key, {})[platform_key] = float(avg_volume or 0.0)

    result: dict[int, float] = {}
    for item_id, platform_map in per_item.items():
        result[item_id] = float(platform_map.get("buff", 0.0) + platform_map.get("youpin", 0.0))
    return result


def _load_hourly_cross_spread_series(
    session,
    item_id: int,
    lookback_hours: int,
) -> list[tuple[datetime, float]]:
    series_map = _load_hourly_cross_spread_series_map(session, {item_id}, lookback_hours)
    return series_map.get(item_id, [])


def _load_hourly_cross_spread_series_map(
    session,
    item_ids: set[int],
    lookback_hours: int,
) -> dict[int, list[tuple[datetime, float]]]:
    if not item_ids:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))
    rows = session.execute(
        select(PriceHistory.item_id, PriceHistory.time, PriceHistory.platform, PriceHistory.price)
        .where(
            PriceHistory.item_id.in_(item_ids),
            PriceHistory.platform.in_(("buff", "youpin")),
            PriceHistory.time >= cutoff,
        )
        .order_by(PriceHistory.item_id.asc(), PriceHistory.time.desc())
    ).all()

    bucket_prices: dict[int, dict[datetime, dict[str, float]]] = {}
    for item_id, time_value, platform, price_value in rows:
        if price_value is None:
            continue
        item_key = int(item_id)
        bucket = _hour_bucket(time_value)
        platform_key = str(platform)
        slot = bucket_prices.setdefault(item_key, {}).setdefault(bucket, {})
        # Keep latest tick for each platform in the hour bucket.
        if platform_key not in slot:
            slot[platform_key] = float(price_value)

    series_map: dict[int, list[tuple[datetime, float]]] = {}
    for item_key, per_bucket in bucket_prices.items():
        series: list[tuple[datetime, float]] = []
        for bucket, prices in per_bucket.items():
            buff_price = prices.get("buff")
            youpin_price = prices.get("youpin")
            spread_pct = _cross_spread_pct(youpin_price, buff_price)
            if spread_pct is None:
                continue
            series.append((bucket, spread_pct))
        series.sort(key=lambda row: row[0], reverse=True)
        series_map[item_key] = series
    return series_map


def _case_spread_confirmed_from_series(
    series: list[tuple[datetime, float]],
    required_spread_pct: float,
) -> bool:
    if not ARBITRAGE_CASE_CONFIRM_ENABLED:
        return True

    need = max(1, ARBITRAGE_CASE_CONFIRM_CONSECUTIVE_HOURS)
    if len(series) < need:
        return False

    window = series[:need]
    for idx, (bucket, spread_pct) in enumerate(window):
        if spread_pct < required_spread_pct:
            return False
        if idx > 0:
            prev_bucket = window[idx - 1][0]
            if prev_bucket - bucket > timedelta(hours=1, minutes=5):
                return False
    return True


def _case_spread_confirmed(
    session,
    item_id: int,
    required_spread_pct: float,
) -> bool:
    series = _load_hourly_cross_spread_series(
        session=session,
        item_id=item_id,
        lookback_hours=max(ARBITRAGE_CASE_CONFIRM_LOOKBACK_HOURS, ARBITRAGE_CASE_CONFIRM_CONSECUTIVE_HOURS + 1),
    )
    return _case_spread_confirmed_from_series(series, required_spread_pct)


def _should_stop_add_on_drawdown_from_series(series: list[tuple[datetime, float]]) -> bool:
    if not series:
        return False
    current_spread = series[0][1]
    max_spread_24h = max(spread for _, spread in series)
    return (
        max_spread_24h >= ARBITRAGE_TIER_LIGHT_MIN_SPREAD_PCT
        and current_spread < ARBITRAGE_DRAWDOWN_STOP_SPREAD_PCT
    )


def _should_stop_add_on_drawdown(session, item_id: int) -> bool:
    series = _load_hourly_cross_spread_series(session=session, item_id=item_id, lookback_hours=24)
    return _should_stop_add_on_drawdown_from_series(series)


def _build_csqaq_oneway_opportunities(
    session,
    rows: Iterable[dict],
    fee_map: dict[str, tuple[float, float]],
    min_profit_amount: float,
    min_profit_rate: float,
    item_ids: Optional[Iterable[int]],
    item_name_map: Optional[dict[int, dict[str, str]]] = None,
    dual_daily_volume_map: Optional[dict[int, float]] = None,
) -> list[ArbitrageOpportunity]:
    item_filter = {int(item_id) for item_id in item_ids} if item_ids else None
    opportunities: list[ArbitrageOpportunity] = []
    pending: list[tuple[ArbitrageOpportunity, Optional[float], str]] = []
    calculated_at = datetime.now(timezone.utc)
    redis_client = get_dragonfly_client()
    tags_map = redis_client.hgetall("items:market_maker_tags") or {}

    buy_fee_rate, _ = fee_map.get("youpin", DEFAULT_FEE_RATES["youpin"])
    _, sell_fee_rate = fee_map.get("buff", DEFAULT_FEE_RATES["buff"])

    for row in rows:
        item_id = _safe_int(row.get("id"))
        if item_id is None:
            continue
        if item_filter is not None and item_id not in item_filter:
            continue
        item_tag = tags_map.get(str(item_id))
        if item_tag == "[高危黑名单]":
            continue

        name_meta = (item_name_map or {}).get(item_id, {})
        item_name_en = str(
            row.get("market_hash_name")
            or name_meta.get("english")
            or ""
        ).strip()
        item_name = str(name_meta.get("display") or item_name_en).strip()
        if not item_name:
            continue
        item_type = str(name_meta.get("type") or "").strip()
        item_category = _normalize_item_category(item_name=item_name, item_name_en=item_name_en, item_type=item_type)

        youpin_ask = _safe_float(row.get("yyyp_sell_price"))
        buff_bid = _safe_float(row.get("buff_buy_price"))
        buff_ask = _safe_float(row.get("buff_sell_price"))
        buff_sell_liquidity = _safe_int(row.get("buff_sell_num"))
        buy_liquidity = _safe_int(row.get("yyyp_sell_num"))
        sell_liquidity = _safe_int(row.get("buff_buy_num"))

        if ARBITRAGE_DIRECTION == "youpin_to_buff":
            if youpin_ask is None or buff_bid is None:
                continue
            if youpin_ask <= 0 or buff_bid <= 0:
                continue
        else:
            continue

        if (buy_liquidity or 0) < ARBITRAGE_MIN_LIQUIDITY:
            continue
        if (sell_liquidity or 0) <= 0:
            continue
        if not _passes_buff_liquidity_guard(
            youpin_sell_num=buy_liquidity,
            buff_buy_num=sell_liquidity,
            buff_sell_num=buff_sell_liquidity,
        ):
            continue

        dual_daily_volume = float((dual_daily_volume_map or {}).get(item_id, 0.0))
        if dual_daily_volume < ARBITRAGE_LIQUIDITY_TRAP_MIN_DUAL_DAILY_VOLUME:
            continue
        if dual_daily_volume < ARBITRAGE_MAIN_POOL_MIN_DUAL_DAILY_VOLUME:
            continue

        spread_ratio_pct = None
        if buff_ask is not None and buff_bid is not None and buff_ask > 0:
            spread_ratio_pct = (buff_ask - buff_bid) / buff_ask * 100.0
            if spread_ratio_pct > ARBITRAGE_MAX_SPREAD_RATIO_PCT:
                continue

        cross_spread_pct = _cross_spread_pct(youpin_ask, buff_bid)
        signal_tier, recommended_position, tier_required_spread = _resolve_signal_tier(cross_spread_pct)
        if signal_tier is None:
            continue
        if signal_tier == "anomaly":
            # >8% 属于异常窗口，仅拦截不入主策略池。
            continue

        buy_cost = youpin_ask * (1 + buy_fee_rate)
        if buy_cost <= 0:
            continue
        sell_revenue = buff_bid * (1 - sell_fee_rate) * ARBITRAGE_WITHDRAWAL_RATE
        net_profit = sell_revenue - buy_cost
        profit_rate = (net_profit / buy_cost) * 100.0

        if net_profit <= 0:
            continue
        if net_profit < min_profit_amount or profit_rate < min_profit_rate:
            continue
        if item_category == "sticker" and net_profit < ARBITRAGE_STICKER_MIN_NET_PROFIT:
            continue

        ts = _parse_timestamp(row.get("updated_at"))
        verify_status = "pending_recheck" if profit_rate >= ARBITRAGE_RECHECK_ROI_PCT else "not_required"
        strategy_parts = ["youpin_buy_to_buff_bid", f"tier_{signal_tier}", f"category_{item_category}"]
        if item_tag:
            strategy_parts.append(str(item_tag))
        strategy_str = "_".join(strategy_parts)
        pending.append(
            (
                ArbitrageOpportunity(
                    item_id=item_id,
                    item_name=item_name,
                    item_name_en=item_name_en or None,
                    buy_platform="youpin",
                    sell_platform="buff",
                    buy_price=youpin_ask,
                    sell_price=buff_bid,
                    buy_fee_rate=buy_fee_rate,
                    sell_fee_rate=sell_fee_rate,
                    buy_cost=buy_cost,
                    sell_revenue=sell_revenue,
                    net_profit=net_profit,
                    profit_rate=profit_rate,
                    currency="CNY",
                    buy_time=ts,
                    sell_time=ts,
                    calculated_at=calculated_at,
                    spread_ratio_pct=round(spread_ratio_pct, 4) if spread_ratio_pct is not None else None,
                    buy_liquidity=buy_liquidity,
                    sell_liquidity=sell_liquidity,
                    verify_status=verify_status,
                    strategy=strategy_str,
                    cross_spread_pct=round(cross_spread_pct, 4) if cross_spread_pct is not None else None,
                    signal_tier=signal_tier,
                    recommended_position=recommended_position,
                    stop_add=False,
                    dual_daily_volume=round(dual_daily_volume, 2),
                    item_category=item_category,
                ),
                tier_required_spread,
                item_category,
            )
        )

    if not pending:
        return opportunities

    pending_item_ids = {opp.item_id for opp, _, _ in pending}
    series_map_24h = _load_hourly_cross_spread_series_map(
        session=session,
        item_ids=pending_item_ids,
        lookback_hours=24,
    )

    for opp, tier_required_spread, item_category in pending:
        series = series_map_24h.get(opp.item_id, [])
        if item_category == "case" and tier_required_spread is not None:
            if not _case_spread_confirmed_from_series(series, required_spread_pct=tier_required_spread):
                continue
        if _should_stop_add_on_drawdown_from_series(series):
            continue
        opportunities.append(opp)

    return opportunities


def _verify_high_roi_opportunities(
    opportunities: list[ArbitrageOpportunity],
    min_profit_amount: float,
    min_profit_rate: float,
) -> list[ArbitrageOpportunity]:
    if not opportunities:
        return opportunities

    high_roi_indexes = [
        idx for idx, opp in enumerate(opportunities)
        if opp.profit_rate >= ARBITRAGE_RECHECK_ROI_PCT
    ]
    if not high_roi_indexes:
        return opportunities

    if not allow_rate_limit(ARBITRAGE_RECHECK_RATE_LIMIT_KEY, limit=1, window_seconds=1):
        if ARBITRAGE_STRICT_RECHECK:
            return [opp for opp in opportunities if opp.profit_rate < ARBITRAGE_RECHECK_ROI_PCT]
        return [
            replace(opp, verify_status="skipped_rate_limit")
            if opp.profit_rate >= ARBITRAGE_RECHECK_ROI_PCT
            else opp
            for opp in opportunities
        ]

    try:
        with CSQAQScraper() as scraper:
            rows = scraper.get_all_goods_info()
    except Exception as exc:
        logger.warning("[Arbitrage] High ROI recheck failed: {}", exc)
        if ARBITRAGE_STRICT_RECHECK:
            return [opp for opp in opportunities if opp.profit_rate < ARBITRAGE_RECHECK_ROI_PCT]
        return [
            replace(opp, verify_status="recheck_failed")
            if opp.profit_rate >= ARBITRAGE_RECHECK_ROI_PCT
            else opp
            for opp in opportunities
        ]

    row_map: dict[int, dict] = {}
    for row in rows:
        row_id = _safe_int(row.get("id"))
        if row_id is not None and row_id not in row_map:
            row_map[row_id] = row

    high_roi_item_ids = {opportunities[idx].item_id for idx in high_roi_indexes}
    session = get_sessionmaker()()
    try:
        item_meta_map = _load_item_name_map(session, item_ids=high_roi_item_ids)
        dual_daily_volume_map = _load_dual_daily_volume_map(session, high_roi_item_ids)

        checked = 0
        result: list[ArbitrageOpportunity] = []
        for idx, opp in enumerate(opportunities):
            if idx not in high_roi_indexes:
                result.append(opp)
                continue

            if checked >= ARBITRAGE_RECHECK_MAX_PER_RUN:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="skipped_verify_limit"))
                continue
            checked += 1

            row = row_map.get(opp.item_id)
            if not row:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_missing"))
                continue

            youpin_ask = _safe_float(row.get("yyyp_sell_price"))
            buff_bid = _safe_float(row.get("buff_buy_price"))
            buff_ask = _safe_float(row.get("buff_sell_price"))
            buff_sell_liquidity = _safe_int(row.get("buff_sell_num"))
            buy_liquidity = _safe_int(row.get("yyyp_sell_num"))
            sell_liquidity = _safe_int(row.get("buff_buy_num"))
            if youpin_ask is None or buff_bid is None or youpin_ask <= 0 or buff_bid <= 0:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_invalid"))
                continue
            if not _passes_buff_liquidity_guard(
                youpin_sell_num=buy_liquidity,
                buff_buy_num=sell_liquidity,
                buff_sell_num=buff_sell_liquidity,
            ):
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_buff_liquidity_reject"))
                continue

            spread_ratio_pct = None
            if buff_ask is not None and buff_ask > 0:
                spread_ratio_pct = (buff_ask - buff_bid) / buff_ask * 100.0
                if spread_ratio_pct > ARBITRAGE_MAX_SPREAD_RATIO_PCT:
                    if ARBITRAGE_STRICT_RECHECK:
                        continue
                    result.append(replace(opp, verify_status="verify_spread_reject"))
                    continue

            buy_cost = youpin_ask * (1 + opp.buy_fee_rate)
            sell_revenue = buff_bid * (1 - opp.sell_fee_rate) * ARBITRAGE_WITHDRAWAL_RATE
            net_profit = sell_revenue - buy_cost
            profit_rate = (net_profit / buy_cost) * 100.0 if buy_cost > 0 else -9999
            if net_profit <= 0 or net_profit < min_profit_amount or profit_rate < min_profit_rate:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_profit_reject"))
                continue

            cross_spread_pct = _cross_spread_pct(youpin_ask, buff_bid)
            signal_tier, recommended_position, tier_required_spread = _resolve_signal_tier(cross_spread_pct)
            if signal_tier is None:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_tier_reject"))
                continue
            if signal_tier == "anomaly":
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_anomaly_intercept"))
                continue

            item_meta = item_meta_map.get(opp.item_id, {})
            item_type = str(item_meta.get("type") or "")
            item_category = _normalize_item_category(
                item_name=opp.item_name,
                item_name_en=opp.item_name_en,
                item_type=item_type,
            )
            dual_daily_volume = float(dual_daily_volume_map.get(opp.item_id, 0.0))
            if dual_daily_volume < ARBITRAGE_LIQUIDITY_TRAP_MIN_DUAL_DAILY_VOLUME:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_liquidity_trap"))
                continue
            if dual_daily_volume < ARBITRAGE_MAIN_POOL_MIN_DUAL_DAILY_VOLUME:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_liquidity_reject"))
                continue
            if item_category == "sticker" and net_profit < ARBITRAGE_STICKER_MIN_NET_PROFIT:
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_sticker_profit_reject"))
                continue
            if item_category == "case" and tier_required_spread is not None:
                if not _case_spread_confirmed(
                    session=session,
                    item_id=opp.item_id,
                    required_spread_pct=tier_required_spread,
                ):
                    if ARBITRAGE_STRICT_RECHECK:
                        continue
                    result.append(replace(opp, verify_status="verify_case_confirm_reject"))
                    continue
            if _should_stop_add_on_drawdown(session=session, item_id=opp.item_id):
                if ARBITRAGE_STRICT_RECHECK:
                    continue
                result.append(replace(opp, verify_status="verify_drawdown_stop_add"))
                continue

            ts = _parse_timestamp(row.get("updated_at"))
            result.append(
                replace(
                    opp,
                    buy_price=youpin_ask,
                    sell_price=buff_bid,
                    buy_cost=buy_cost,
                    sell_revenue=sell_revenue,
                    net_profit=net_profit,
                    profit_rate=profit_rate,
                    buy_time=ts,
                    sell_time=ts,
                    spread_ratio_pct=round(spread_ratio_pct, 4) if spread_ratio_pct is not None else opp.spread_ratio_pct,
                    verify_status="verified",
                    cross_spread_pct=round(cross_spread_pct, 4) if cross_spread_pct is not None else opp.cross_spread_pct,
                    signal_tier=signal_tier,
                    recommended_position=recommended_position,
                    stop_add=False,
                    dual_daily_volume=round(dual_daily_volume, 2),
                    item_category=item_category,
                )
            )
        return result
    finally:
        session.close()


def _serialize_opportunity(opportunity: ArbitrageOpportunity) -> dict:
    payload = asdict(opportunity)
    payload["buy_price"] = _round_currency(payload["buy_price"])
    payload["sell_price"] = _round_currency(payload["sell_price"])
    payload["buy_cost"] = _round_currency(payload["buy_cost"])
    payload["sell_revenue"] = _round_currency(payload["sell_revenue"])
    payload["net_profit"] = _round_currency(payload["net_profit"])
    payload["profit_rate"] = round(payload["profit_rate"], 2)
    payload["buy_fee_rate"] = round(payload["buy_fee_rate"], 4)
    payload["sell_fee_rate"] = round(payload["sell_fee_rate"], 4)
    if payload.get("spread_ratio_pct") is not None:
        payload["spread_ratio_pct"] = round(float(payload["spread_ratio_pct"]), 4)
    if payload.get("cross_spread_pct") is not None:
        payload["cross_spread_pct"] = round(float(payload["cross_spread_pct"]), 4)
    if payload.get("dual_daily_volume") is not None:
        payload["dual_daily_volume"] = round(float(payload["dual_daily_volume"]), 2)
    payload["buy_time"] = opportunity.buy_time.isoformat()
    payload["sell_time"] = opportunity.sell_time.isoformat()
    payload["calculated_at"] = opportunity.calculated_at.isoformat()
    return payload


def _publish_opportunities(
    opportunities: Iterable[ArbitrageOpportunity],
    channel: str = DEFAULT_PUBLISH_CHANNEL,
    limit: int = DEFAULT_PUBLISH_LIMIT,
) -> int:
    payload = {
        "type": "arbitrage_opportunities",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": [_serialize_opportunity(opp) for opp in list(opportunities)[:limit]],
    }
    client = get_dragonfly_client()
    client.publish(channel, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return len(payload["data"])


def analyze_arbitrage_opportunities(
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    min_profit_amount: float = DEFAULT_MIN_PROFIT_AMOUNT,
    min_profit_rate: float = DEFAULT_MIN_PROFIT_RATE,
    platforms: Optional[Iterable[str]] = None,
    item_ids: Optional[Iterable[int]] = None,
    include_all_pairs: bool = False,
    use_csqaq_cache: bool = True,
    verify_high_roi: bool = True,
) -> list[ArbitrageOpportunity]:
    session = get_sessionmaker()()
    try:
        fee_map = _load_platform_fees(session, platforms)
        use_csqaq_mode = (
            ARBITRAGE_SOURCE == "csqaq"
            and ARBITRAGE_DIRECTION == "youpin_to_buff"
        )
        if use_csqaq_mode:
            rows = load_csqaq_goods_snapshot(use_cache=use_csqaq_cache)
            row_item_ids = {
                row_id
                for row_id in (
                    _safe_int(row.get("id"))
                    for row in rows
                    if isinstance(row, dict)
                )
                if row_id is not None
            }
            item_name_map = _load_item_name_map(session, item_ids=row_item_ids)
            dual_daily_volume_map = _load_dual_daily_volume_map(session, row_item_ids)
            opportunities = _build_csqaq_oneway_opportunities(
                session=session,
                rows=rows,
                fee_map=fee_map,
                min_profit_amount=min_profit_amount,
                min_profit_rate=min_profit_rate,
                item_ids=item_ids,
                item_name_map=item_name_map,
                dual_daily_volume_map=dual_daily_volume_map,
            )
            if verify_high_roi:
                opportunities = _verify_high_roi_opportunities(
                    opportunities=opportunities,
                    min_profit_amount=min_profit_amount,
                    min_profit_rate=min_profit_rate,
                )
            return opportunities

        snapshots = _latest_price_snapshots(
            session,
            max_age_minutes=max_age_minutes,
            platforms=platforms,
            item_ids=item_ids,
        )
        return _build_opportunities(
            snapshots,
            fee_map,
            min_profit_amount=min_profit_amount,
            min_profit_rate=min_profit_rate,
            include_all_pairs=include_all_pairs,
        )
    finally:
        session.close()


def analyze_and_cache_opportunities(
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    min_profit_amount: float = DEFAULT_MIN_PROFIT_AMOUNT,
    min_profit_rate: float = DEFAULT_MIN_PROFIT_RATE,
    platforms: Optional[Iterable[str]] = None,
    item_ids: Optional[Iterable[int]] = None,
    include_all_pairs: bool = False,
    score_by: str = DEFAULT_SCORE_BY,
    limit: int = 200,
    ttl: int = ARBITRAGE_TTL_SECONDS,
    publish: bool = True,
    publish_channel: str = DEFAULT_PUBLISH_CHANNEL,
    publish_limit: int = DEFAULT_PUBLISH_LIMIT,
    notify: bool = True,
    notify_min_profit_rate: Optional[float] = None,
    verify_high_roi: bool = True,
    defer_high_roi_verify: bool = False,
    recheck_roi_threshold: float = ARBITRAGE_RECHECK_ROI_PCT,
) -> dict:
    opportunities = analyze_arbitrage_opportunities(
        max_age_minutes=max_age_minutes,
        min_profit_amount=min_profit_amount,
        min_profit_rate=min_profit_rate,
        platforms=platforms,
        item_ids=item_ids,
        include_all_pairs=include_all_pairs,
        verify_high_roi=verify_high_roi,
    )
    ranked = rank_opportunities(opportunities, sort_by=score_by)
    if limit:
        ranked = ranked[:limit]

    deferred_verify_candidates: list[dict] = []
    if defer_high_roi_verify:
        immediate_ranked: list[ArbitrageOpportunity] = []
        for opp in ranked:
            if (
                opp.profit_rate >= recheck_roi_threshold
                and (opp.verify_status in {None, "pending_recheck"})
            ):
                deferred_verify_candidates.append(_serialize_opportunity(opp))
            else:
                immediate_ranked.append(opp)
        ranked = immediate_ranked

    serialized_ranked = [_serialize_opportunity(opp) for opp in ranked]
    cache_payloads = [
        (getattr(opp, score_by), payload)
        for opp, payload in zip(ranked, serialized_ranked)
    ]
    cache_arbitrage_opportunities(cache_payloads, ttl=ttl)
    published_count = 0
    if publish:
        published_count = _publish_opportunities(
            ranked,
            channel=publish_channel,
            limit=publish_limit,
        )

    notify_result = None
    if notify and serialized_ranked:
        if notify_min_profit_rate is None:
            notify_result = notify_arbitrage_opportunities(serialized_ranked)
        else:
            notify_result = notify_arbitrage_opportunities(
                serialized_ranked,
                min_profit_rate=notify_min_profit_rate,
            )

    return {
        "opportunities_found": len(opportunities),
        "cached_count": len(cache_payloads),
        "score_by": score_by,
        "published_count": published_count,
        "publish_channel": publish_channel,
        "notify_result": notify_result,
        "deferred_verify_count": len(deferred_verify_candidates),
        "deferred_verify_candidates": deferred_verify_candidates,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def publish_opportunity_payloads(
    payloads: Iterable[dict],
    channel: str = DEFAULT_PUBLISH_CHANNEL,
    limit: int = DEFAULT_PUBLISH_LIMIT,
) -> int:
    rows = list(payloads)[:max(0, limit)]
    payload = {
        "type": "arbitrage_opportunities",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": rows,
    }
    client = get_dragonfly_client()
    client.publish(channel, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return len(rows)


def verify_single_high_roi_candidate(
    opportunity_payload: dict,
    min_profit_amount: float = DEFAULT_MIN_PROFIT_AMOUNT,
    min_profit_rate: float = DEFAULT_MIN_PROFIT_RATE,
) -> Optional[dict]:
    item_id = _safe_int(opportunity_payload.get("item_id"))
    if item_id is None:
        return None

    rows = load_csqaq_goods_snapshot(use_cache=False)
    target_row = None
    for row in rows:
        row_item_id = _safe_int(row.get("id"))
        if row_item_id == item_id:
            target_row = row
            break
    if not target_row:
        return None

    item_name = str(
        opportunity_payload.get("item_name")
        or target_row.get("market_hash_name")
        or ""
    ).strip()
    item_name_en = str(
        opportunity_payload.get("item_name_en")
        or target_row.get("market_hash_name")
        or ""
    ).strip()
    if not item_name:
        return None
    session = get_sessionmaker()()
    try:
        item_meta_map = _load_item_name_map(session, item_ids={item_id})
        item_meta = item_meta_map.get(item_id, {})
        item_type = str(item_meta.get("type") or "")
        dual_daily_volume_map = _load_dual_daily_volume_map(session, {item_id})
        dual_daily_volume = float(dual_daily_volume_map.get(item_id, 0.0))
    finally:
        session.close()

    buy_fee_rate = _safe_float(opportunity_payload.get("buy_fee_rate"))
    sell_fee_rate = _safe_float(opportunity_payload.get("sell_fee_rate"))
    if buy_fee_rate is None:
        buy_fee_rate = DEFAULT_FEE_RATES["youpin"][0]
    if sell_fee_rate is None:
        sell_fee_rate = DEFAULT_FEE_RATES["buff"][1]

    youpin_ask = _safe_float(target_row.get("yyyp_sell_price"))
    buff_bid = _safe_float(target_row.get("buff_buy_price"))
    buff_ask = _safe_float(target_row.get("buff_sell_price"))
    buff_sell_liquidity = _safe_int(target_row.get("buff_sell_num"))
    buy_liquidity = _safe_int(target_row.get("yyyp_sell_num"))
    sell_liquidity = _safe_int(target_row.get("buff_buy_num"))
    if youpin_ask is None or buff_bid is None or youpin_ask <= 0 or buff_bid <= 0:
        return None
    if (buy_liquidity or 0) < ARBITRAGE_MIN_LIQUIDITY or (sell_liquidity or 0) <= 0:
        return None
    if not _passes_buff_liquidity_guard(
        youpin_sell_num=buy_liquidity,
        buff_buy_num=sell_liquidity,
        buff_sell_num=buff_sell_liquidity,
    ):
        return None

    spread_ratio_pct = None
    if buff_ask is not None and buff_ask > 0:
        spread_ratio_pct = (buff_ask - buff_bid) / buff_ask * 100.0
        if spread_ratio_pct > ARBITRAGE_MAX_SPREAD_RATIO_PCT:
            return None
    cross_spread_pct = _cross_spread_pct(youpin_ask, buff_bid)
    signal_tier, recommended_position, tier_required_spread = _resolve_signal_tier(cross_spread_pct)
    if signal_tier is None or signal_tier == "anomaly":
        return None
    if dual_daily_volume < ARBITRAGE_LIQUIDITY_TRAP_MIN_DUAL_DAILY_VOLUME:
        return None
    if dual_daily_volume < ARBITRAGE_MAIN_POOL_MIN_DUAL_DAILY_VOLUME:
        return None

    buy_cost = youpin_ask * (1 + buy_fee_rate)
    if buy_cost <= 0:
        return None
    sell_revenue = buff_bid * (1 - sell_fee_rate) * ARBITRAGE_WITHDRAWAL_RATE
    net_profit = sell_revenue - buy_cost
    profit_rate = (net_profit / buy_cost) * 100.0
    if net_profit <= 0 or net_profit < min_profit_amount or profit_rate < min_profit_rate:
        return None
    item_category = _normalize_item_category(item_name=item_name, item_name_en=item_name_en, item_type=item_type)
    if item_category == "sticker" and net_profit < ARBITRAGE_STICKER_MIN_NET_PROFIT:
        return None

    session = get_sessionmaker()()
    try:
        if item_category == "case" and tier_required_spread is not None:
            if not _case_spread_confirmed(
                session=session,
                item_id=item_id,
                required_spread_pct=tier_required_spread,
            ):
                return None
        if _should_stop_add_on_drawdown(session=session, item_id=item_id):
            return None
    finally:
        session.close()

    ts = _parse_timestamp(target_row.get("updated_at"))
    verified = ArbitrageOpportunity(
        item_id=item_id,
        item_name=item_name,
        item_name_en=item_name_en or None,
        buy_platform="youpin",
        sell_platform="buff",
        buy_price=youpin_ask,
        sell_price=buff_bid,
        buy_fee_rate=buy_fee_rate,
        sell_fee_rate=sell_fee_rate,
        buy_cost=buy_cost,
        sell_revenue=sell_revenue,
        net_profit=net_profit,
        profit_rate=profit_rate,
        currency=str(opportunity_payload.get("currency") or "CNY"),
        buy_time=ts,
        sell_time=ts,
        calculated_at=datetime.now(timezone.utc),
        spread_ratio_pct=round(spread_ratio_pct, 4) if spread_ratio_pct is not None else None,
        buy_liquidity=buy_liquidity,
        sell_liquidity=sell_liquidity,
        verify_status="verified",
        strategy=str(opportunity_payload.get("strategy") or "youpin_buy_to_buff_bid"),
        cross_spread_pct=round(cross_spread_pct, 4) if cross_spread_pct is not None else None,
        signal_tier=signal_tier,
        recommended_position=recommended_position,
        stop_add=False,
        dual_daily_volume=round(dual_daily_volume, 2),
        item_category=item_category,
    )
    return _serialize_opportunity(verified)


def _try_acquire_refresh_lock(ttl: int = REFRESH_LOCK_SECONDS) -> bool:
    client = get_dragonfly_client()
    return bool(client.set(REFRESH_LOCK_KEY, datetime.now(timezone.utc).isoformat(), nx=True, ex=ttl))


def refresh_cache_if_needed(**kwargs) -> Optional[dict]:
    if not _try_acquire_refresh_lock():
        logger.debug("[Arbitrage] Refresh skipped (lock held).")
        return None
    logger.info("[Arbitrage] Refreshing opportunities cache...")
    return analyze_and_cache_opportunities(**kwargs)
