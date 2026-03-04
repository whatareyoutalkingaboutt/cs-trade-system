from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import func, select

from backend.config.historical_config import GAP_FILL_MAX_AGE_HOURS, GAP_TOLERANCE_MULTIPLIER, priority_to_group, COLLECTION_INTERVAL_SECONDS
from backend.core.database import get_sessionmaker
from backend.core.cache import get_dragonfly_client
from backend.models import DataGapLog, Item, PriceHistory
from backend.services.steamdt_price_service import load_csqaq_goods_snapshot


DEFAULT_HISTORY_DAYS = 30
DEFAULT_MAX_AGE_MINUTES = 60
DEFAULT_SPIKE_THRESHOLD = 0.5
DEFAULT_MAX_MULTIPLIER = 2.0
DEFAULT_ALERT_CHANNEL = "alerts:price_anomalies"
DEFAULT_GAP_WINDOW_HOURS = 24
DEFAULT_REPORT_DIR = "data/quality_reports"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


DEFAULT_BOLLINGER_WINDOW = _env_int("ANOMALY_BOLLINGER_WINDOW", 48)
DEFAULT_BOLLINGER_TOUCH_RATIO = _env_float("ANOMALY_BOLLINGER_TOUCH_RATIO", 1.02)
DEFAULT_INVENTORY_LOOKBACK_POINTS = _env_int("ANOMALY_INVENTORY_LOOKBACK_POINTS", 24)
DEFAULT_INVENTORY_SLOPE_THRESHOLD_PCT = _env_float("ANOMALY_INVENTORY_SLOPE_THRESHOLD_PCT", -8.0)
DEFAULT_FLASH_DROP_MIN_RATIO = _env_float("ANOMALY_FLASH_DROP_MIN_RATIO", 0.85)
DEFAULT_RECENT_MIN_POINTS = _env_int("ANOMALY_RECENT_MIN_POINTS", 24)
DEFAULT_WHALE_LOOKBACK_POINTS = _env_int("ANOMALY_WHALE_LOOKBACK_POINTS", 24)
DEFAULT_WHALE_STABLE_CV_MAX = _env_float("ANOMALY_WHALE_STABLE_CV_MAX", 0.25)
DEFAULT_WHALE_VOLUME_SPIKE_MULTIPLIER = _env_float("ANOMALY_WHALE_VOLUME_SPIKE_MULTIPLIER", 2.5)
MARKET_MAKER_TAGS_KEY = "items:market_maker_tags"
MM_ACCUM_AMPLITUDE_MAX = 0.05
MM_ACCUM_SUPPLY_SLOPE_7D_MAX = -0.15
MM_ACCUM_BID_WALL_RATIO_MIN = 3.0
MM_WASHOUT_SPREAD_MIN = _env_float("ANOMALY_MM_WASHOUT_SPREAD_MIN", 0.12)
MM_WASHOUT_SPREAD_MAX = _env_float("ANOMALY_MM_WASHOUT_SPREAD_MAX", 0.16)
MM_WASHOUT_TURNOVER_MULTIPLIER_MAX = _env_float("ANOMALY_MM_WASHOUT_TURNOVER_MULTIPLIER_MAX", 0.90)
MM_WASHOUT_PRICE_SLOPE_1H_MAX = _env_float("ANOMALY_MM_WASHOUT_PRICE_SLOPE_1H_MAX", -0.015)
MM_WASHOUT_SELL_SURGE_1H_MIN = _env_float("ANOMALY_MM_WASHOUT_SELL_SURGE_1H_MIN", 0.05)
MM_WASHOUT_7D_AMPLITUDE_MIN = _env_float("ANOMALY_MM_WASHOUT_7D_AMPLITUDE_MIN", 0.08)
MM_MARKUP_SUPPLY_SLOPE_1H_MAX = -0.10
MM_MARKUP_PRICE_SLOPE_1H_MIN = 0.05
MM_MARKUP_SPREAD_MAX = 0.03
MM_MARKUP_TURNOVER_MULTIPLIER_MIN = 2.0
MM_DISTRIBUTION_AMPLITUDE_MIN = 0.15
MM_DISTRIBUTION_HIGH_PRICE_RATIO = 0.95
MM_DISTRIBUTION_SUPPLY_SLOPE_1H_MIN = 0.05
MM_DISTRIBUTION_TURNOVER_MULTIPLIER_MAX = 0.70
MM_SPOOFING_BUY_WALL_DROP_MULTIPLIER = 0.40
MM_SPOOFING_SPREAD_MIN = 0.08
MM_SPOOFING_PRICE_DROP_RATIO = 0.995


@dataclass(frozen=True)
class PriceAnomaly:
    item_id: int
    item_name: str
    platform: str
    anomaly_type: str
    severity: str
    current_price: float
    reference_price: Optional[float]
    change_rate: Optional[float]
    historical_max: Optional[float]
    currency: str
    detected_at: datetime
    latest_time: datetime


def _serialize_anomaly(anomaly: PriceAnomaly) -> dict:
    payload = asdict(anomaly)
    payload["detected_at"] = anomaly.detected_at.isoformat()
    payload["latest_time"] = anomaly.latest_time.isoformat()
    if payload["change_rate"] is not None:
        payload["change_rate"] = round(payload["change_rate"], 4)
    if payload["current_price"] is not None:
        payload["current_price"] = round(payload["current_price"], 2)
    if payload["reference_price"] is not None:
        payload["reference_price"] = round(payload["reference_price"], 2)
    if payload["historical_max"] is not None:
        payload["historical_max"] = round(payload["historical_max"], 2)
    return payload


def _publish_anomalies(anomalies: Iterable[PriceAnomaly], channel: str) -> int:
    payload = {
        "type": "price_anomalies",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": [_serialize_anomaly(anomaly) for anomaly in anomalies],
    }
    client = get_dragonfly_client()
    client.publish(channel, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return len(payload["data"])


def _mean_std(values: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance)


def detect_price_anomalies(
    history_days: int = DEFAULT_HISTORY_DAYS,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    spike_threshold: float = DEFAULT_SPIKE_THRESHOLD,
    max_multiplier: float = DEFAULT_MAX_MULTIPLIER,
    publish: bool = True,
    channel: str = DEFAULT_ALERT_CHANNEL,
) -> dict:
    session = get_sessionmaker()()
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(minutes=max_age_minutes)
    cutoff_history = now - timedelta(days=history_days)

    latest_map: dict[tuple[int, str], dict] = {}
    previous_map: dict[tuple[int, str], dict] = {}
    max_excl_latest: dict[tuple[int, str], float] = {}
    history_points: dict[tuple[int, str], dict[str, list[float]]] = {}
    flash_dump_candidates: dict[int, list[PriceAnomaly]] = {}

    try:
        stmt = (
            select(
                PriceHistory.item_id,
                Item.market_hash_name,
                PriceHistory.platform,
                PriceHistory.time,
                PriceHistory.price,
                PriceHistory.currency,
                PriceHistory.volume,
                PriceHistory.sell_listings,
            )
            .join(Item, Item.id == PriceHistory.item_id)
            .where(PriceHistory.time >= cutoff_history)
            .order_by(PriceHistory.item_id, PriceHistory.platform, PriceHistory.time.desc())
        )

        for (
            item_id,
            item_name,
            platform,
            time_value,
            price_value,
            currency,
            volume_value,
            sell_listings_value,
        ) in session.execute(stmt).all():
            key = (int(item_id), str(platform))
            price = float(price_value) if price_value is not None else 0.0
            volume = float(volume_value or 0.0)
            sell_listings = float(sell_listings_value or 0.0)
            if key not in latest_map:
                latest_map[key] = {
                    "item_name": str(item_name),
                    "time": time_value,
                    "price": price,
                    "currency": str(currency),
                    "volume": volume,
                    "sell_listings": sell_listings,
                }
                continue

            if key not in previous_map:
                previous_map[key] = {
                    "time": time_value,
                    "price": price,
                }

            history = history_points.setdefault(
                key,
                {"prices": [], "volumes": [], "sell_listings": []},
            )
            if len(history["prices"]) < 120:
                history["prices"].append(price)
            if len(history["volumes"]) < 120:
                history["volumes"].append(volume)
            if len(history["sell_listings"]) < 120:
                history["sell_listings"].append(sell_listings)

            current_max = max_excl_latest.get(key)
            if current_max is None or price > current_max:
                max_excl_latest[key] = price

        anomalies: list[PriceAnomaly] = []
        for key, latest in latest_map.items():
            if latest["time"] < cutoff_recent:
                continue

            item_id, platform = key
            currency = latest["currency"]
            detected_at = now

            previous = previous_map.get(key)
            if previous and previous["price"] > 0:
                change_rate = (latest["price"] - previous["price"]) / previous["price"]
                if abs(change_rate) >= spike_threshold:
                    anomalies.append(
                        PriceAnomaly(
                            item_id=item_id,
                            item_name=latest["item_name"],
                            platform=platform,
                            anomaly_type="spike_up" if change_rate > 0 else "spike_down",
                            severity="warning" if abs(change_rate) < 1.0 else "critical",
                            current_price=latest["price"],
                            reference_price=previous["price"],
                            change_rate=change_rate,
                            historical_max=max_excl_latest.get(key),
                            currency=currency,
                            detected_at=detected_at,
                            latest_time=latest["time"],
                        )
                    )

            historical_max = max_excl_latest.get(key)
            if historical_max and historical_max > 0:
                if latest["price"] >= historical_max * max_multiplier:
                    anomalies.append(
                        PriceAnomaly(
                            item_id=item_id,
                            item_name=latest["item_name"],
                            platform=platform,
                            anomaly_type="exceeds_historical_max",
                            severity="critical",
                            current_price=latest["price"],
                            reference_price=None,
                            change_rate=None,
                            historical_max=historical_max,
                            currency=currency,
                            detected_at=detected_at,
                            latest_time=latest["time"],
                        )
                    )

            history = history_points.get(key, {})
            hist_prices = [value for value in history.get("prices", []) if value > 0]
            hist_volumes = [value for value in history.get("volumes", []) if value > 0]
            hist_sell_listings = [value for value in history.get("sell_listings", []) if value > 0]

            if len(hist_prices) >= DEFAULT_BOLLINGER_WINDOW and len(hist_sell_listings) >= DEFAULT_INVENTORY_LOOKBACK_POINTS:
                boll_slice = hist_prices[:DEFAULT_BOLLINGER_WINDOW]
                mean_price, std_price = _mean_std(boll_slice)
                lower_band = (
                    mean_price - 2.0 * std_price
                    if mean_price is not None and std_price is not None
                    else None
                )
                old_listing = hist_sell_listings[DEFAULT_INVENTORY_LOOKBACK_POINTS - 1]
                inventory_slope_pct = (
                    (latest["sell_listings"] - old_listing) / old_listing * 100.0
                    if old_listing > 0
                    else None
                )
                if (
                    lower_band is not None
                    and lower_band > 0
                    and inventory_slope_pct is not None
                    and latest["price"] <= lower_band * DEFAULT_BOLLINGER_TOUCH_RATIO
                    and inventory_slope_pct <= DEFAULT_INVENTORY_SLOPE_THRESHOLD_PCT
                ):
                    anomalies.append(
                        PriceAnomaly(
                            item_id=item_id,
                            item_name=latest["item_name"],
                            platform=platform,
                            anomaly_type="inventory_slope_bollinger_extreme",
                            severity="warning",
                            current_price=latest["price"],
                            reference_price=lower_band,
                            change_rate=inventory_slope_pct / 100.0,
                            historical_max=max_excl_latest.get(key),
                            currency=currency,
                            detected_at=detected_at,
                            latest_time=latest["time"],
                        )
                    )

            if len(hist_prices) >= DEFAULT_RECENT_MIN_POINTS:
                recent_min = min(hist_prices[:DEFAULT_RECENT_MIN_POINTS])
                if recent_min > 0 and latest["price"] <= recent_min * DEFAULT_FLASH_DROP_MIN_RATIO:
                    anomaly = PriceAnomaly(
                        item_id=item_id,
                        item_name=latest["item_name"],
                        platform=platform,
                        anomaly_type="flash_low_price",
                        severity="critical",
                        current_price=latest["price"],
                        reference_price=recent_min,
                        change_rate=(latest["price"] - recent_min) / recent_min,
                        historical_max=max_excl_latest.get(key),
                        currency=currency,
                        detected_at=detected_at,
                        latest_time=latest["time"],
                    )
                    anomalies.append(anomaly)
                    flash_dump_candidates.setdefault(item_id, []).append(anomaly)

            if len(hist_volumes) >= DEFAULT_WHALE_LOOKBACK_POINTS:
                volume_baseline_slice = hist_volumes[:DEFAULT_WHALE_LOOKBACK_POINTS]
                mean_volume, std_volume = _mean_std(volume_baseline_slice)
                if mean_volume and mean_volume > 0:
                    cv = (std_volume / mean_volume) if std_volume is not None else 0.0
                    current_volume = float(latest["volume"] or 0.0)
                    if (
                        cv <= DEFAULT_WHALE_STABLE_CV_MAX
                        and current_volume >= mean_volume * DEFAULT_WHALE_VOLUME_SPIKE_MULTIPLIER
                    ):
                        anomalies.append(
                            PriceAnomaly(
                                item_id=item_id,
                                item_name=latest["item_name"],
                                platform=platform,
                                anomaly_type="volume_spike_whale_entry",
                                severity="warning" if current_volume < mean_volume * 4 else "critical",
                                current_price=latest["price"],
                                reference_price=None,
                                change_rate=(current_volume / mean_volume) - 1.0,
                                historical_max=max_excl_latest.get(key),
                                currency=currency,
                                detected_at=detected_at,
                                latest_time=latest["time"],
                            )
                        )

        for item_id, rows in flash_dump_candidates.items():
            platforms = {row.platform for row in rows}
            if {"buff", "youpin"}.issubset(platforms):
                sample = rows[0]
                min_price = min(row.current_price for row in rows)
                min_ref = min((row.reference_price or row.current_price) for row in rows)
                anomalies.append(
                    PriceAnomaly(
                        item_id=item_id,
                        item_name=sample.item_name,
                        platform="cross",
                        anomaly_type="cross_platform_flash_dump",
                        severity="critical",
                        current_price=min_price,
                        reference_price=min_ref,
                        change_rate=(min_price - min_ref) / min_ref if min_ref > 0 else None,
                        historical_max=None,
                        currency=sample.currency,
                        detected_at=now,
                        latest_time=sample.latest_time,
                    )
                )

        published = 0
        if publish and anomalies:
            published = _publish_anomalies(anomalies, channel)

        return {
            "anomalies_found": len(anomalies),
            "published_count": published,
            "channel": channel,
            "timestamp": now.isoformat(),
        }
    finally:
        session.close()


def detect_market_maker_behavior() -> dict:
    session = get_sessionmaker()()
    now = datetime.now(timezone.utc)
    redis_client = get_dragonfly_client()

    try:
        rows = load_csqaq_goods_snapshot(use_cache=True)
        live_data = {
            int(row["id"]): row
            for row in rows
            if isinstance(row, dict) and row.get("id") is not None
        }
        if not live_data:
            redis_client.delete(MARKET_MAKER_TAGS_KEY)
            return {
                "tagged_items_count": 0,
                "tag_counts": {},
                "timestamp": now.isoformat(),
            }

        cutoff_7d = now - timedelta(days=7)
        stats_7d_rows = session.execute(
            select(
                PriceHistory.item_id,
                func.min(PriceHistory.price).label("min_7d"),
                func.max(PriceHistory.price).label("max_7d"),
            )
            .where(
                PriceHistory.platform == "buff",
                PriceHistory.time >= cutoff_7d,
            )
            .group_by(PriceHistory.item_id)
        ).all()
        range_7d_map = {
            int(row.item_id): (float(row.min_7d or 0), float(row.max_7d or 0))
            for row in stats_7d_rows
        }

        def _history_snapshot_map(cutoff: datetime, window: Optional[timedelta] = None) -> dict[int, dict]:
            ranked = (
                select(
                    PriceHistory.item_id.label("item_id"),
                    PriceHistory.price.label("price"),
                    PriceHistory.sell_listings.label("sell_listings"),
                    PriceHistory.buy_orders.label("buy_orders"),
                    PriceHistory.volume.label("volume"),
                    PriceHistory.time.label("time"),
                    func.row_number().over(
                        partition_by=PriceHistory.item_id,
                        order_by=PriceHistory.time.desc(),
                    ).label("rn"),
                )
                .where(
                    PriceHistory.platform == "buff",
                    PriceHistory.time <= cutoff,
                )
            )
            if window is not None:
                ranked = ranked.where(PriceHistory.time >= cutoff - window)
            ranked = ranked.subquery()
            rows = session.execute(
                select(
                    ranked.c.item_id,
                    ranked.c.price,
                    ranked.c.sell_listings,
                    ranked.c.buy_orders,
                    ranked.c.volume,
                )
                .where(ranked.c.rn == 1)
            ).all()
            return {
                int(row.item_id): {
                    "price": float(row.price) if row.price is not None else None,
                    "sell_listings": int(row.sell_listings or 0),
                    "buy_orders": int(row.buy_orders or 0),
                    "volume": int(row.volume or 0),
                }
                for row in rows
            }

        history_now_map = _history_snapshot_map(now, window=timedelta(minutes=30))
        history_10m_map = _history_snapshot_map(now - timedelta(minutes=10), window=timedelta(hours=1))
        history_1h_map = _history_snapshot_map(now - timedelta(hours=1), window=timedelta(hours=2))
        history_7d_map = _history_snapshot_map(now - timedelta(days=7), window=timedelta(days=1))

        anomalies_tags: dict[int, str] = {}
        tag_counts: dict[str, int] = {}

        for item_id, current in live_data.items():
            try:
                ask = float(current.get("buff_sell_price") or 0)
                bid = float(current.get("buff_buy_price") or 0)
                sell_num = int(current.get("buff_sell_num") or 0)
                buy_num = int(current.get("buff_buy_num") or 0)
            except (TypeError, ValueError):
                continue

            if ask <= 0 or bid <= 0 or sell_num <= 0:
                continue

            tag = None

            min_7d, max_7d = range_7d_map.get(item_id, (ask, ask))
            amplitude = (max_7d - min_7d) / max_7d if max_7d > 0 else 0.0
            supply_7d_ago = history_7d_map.get(item_id, {}).get("sell_listings", sell_num)
            supply_slope_7d = (
                (sell_num - supply_7d_ago) / supply_7d_ago
                if supply_7d_ago and supply_7d_ago > 0
                else 0.0
            )
            if (
                amplitude < MM_ACCUM_AMPLITUDE_MAX
                and supply_slope_7d < MM_ACCUM_SUPPLY_SLOPE_7D_MAX
                and (buy_num / sell_num) > MM_ACCUM_BID_WALL_RATIO_MIN
            ):
                tag = "[疑似吸筹]"

            spread_ratio = (ask - bid) / ask if ask > 0 else 0.0
            current_volume = history_now_map.get(item_id, {}).get("volume", 0)
            volume_1h_ago = history_1h_map.get(item_id, {}).get("volume", current_volume)
            turnover_now = (current_volume / sell_num * 100.0) if sell_num > 0 else 0.0
            sell_1h_ago_for_turnover = history_1h_map.get(item_id, {}).get("sell_listings", sell_num)
            turnover_1h = (
                (volume_1h_ago / sell_1h_ago_for_turnover * 100.0)
                if sell_1h_ago_for_turnover and sell_1h_ago_for_turnover > 0
                else 0.0
            )
            supply_1h_ago = history_1h_map.get(item_id, {}).get("sell_listings", sell_num)
            price_1h_ago = history_1h_map.get(item_id, {}).get("price", ask)
            supply_slope_1h = (
                (sell_num - supply_1h_ago) / supply_1h_ago
                if supply_1h_ago and supply_1h_ago > 0
                else 0.0
            )
            price_slope_1h = (
                (ask - price_1h_ago) / price_1h_ago
                if price_1h_ago and price_1h_ago > 0
                else 0.0
            )
            washout_turnover_ok = (
                turnover_now <= turnover_1h * MM_WASHOUT_TURNOVER_MULTIPLIER_MAX
                if turnover_1h > 0
                else current_volume <= int(volume_1h_ago * MM_WASHOUT_TURNOVER_MULTIPLIER_MAX)
            )
            washout_price_drop_ok = price_slope_1h <= MM_WASHOUT_PRICE_SLOPE_1H_MAX
            washout_supply_surge_ok = supply_slope_1h >= MM_WASHOUT_SELL_SURGE_1H_MIN
            washout_amplitude_ok = amplitude >= MM_WASHOUT_7D_AMPLITUDE_MIN
            if (
                MM_WASHOUT_SPREAD_MIN <= spread_ratio <= MM_WASHOUT_SPREAD_MAX
                and washout_turnover_ok
                and washout_price_drop_ok
                and washout_supply_surge_ok
                and washout_amplitude_ok
            ):
                tag = "[庄家洗盘/画线假摔]"

            markup_turnover_ok = (
                turnover_now >= turnover_1h * MM_MARKUP_TURNOVER_MULTIPLIER_MIN
                if turnover_1h > 0
                else current_volume >= int(volume_1h_ago * MM_MARKUP_TURNOVER_MULTIPLIER_MIN)
            )
            if (
                supply_slope_1h < MM_MARKUP_SUPPLY_SLOPE_1H_MAX
                and price_slope_1h > MM_MARKUP_PRICE_SLOPE_1H_MIN
                and spread_ratio < MM_MARKUP_SPREAD_MAX
                and markup_turnover_ok
            ):
                tag = "[主升浪开启]"

            volume_divergence = (
                turnover_now < turnover_1h * MM_DISTRIBUTION_TURNOVER_MULTIPLIER_MAX
                if turnover_1h > 0
                else current_volume < int(volume_1h_ago * MM_DISTRIBUTION_TURNOVER_MULTIPLIER_MAX)
            )
            buy_10m_ago = history_10m_map.get(item_id, {}).get("buy_orders", buy_num)
            price_10m_ago = history_10m_map.get(item_id, {}).get("price", ask)
            # 快照级 spoofing 近似: 买墙在短时间显著撤单 + 盘口断层拉大 + 价格转弱
            spoofing_like = bool(
                buy_10m_ago and buy_10m_ago > 0
                and buy_num <= buy_10m_ago * MM_SPOOFING_BUY_WALL_DROP_MULTIPLIER
                and spread_ratio >= MM_SPOOFING_SPREAD_MIN
                and price_10m_ago and price_10m_ago > 0
                and ask <= price_10m_ago * MM_SPOOFING_PRICE_DROP_RATIO
            )
            if (
                amplitude > MM_DISTRIBUTION_AMPLITUDE_MIN
                and ask >= max_7d * MM_DISTRIBUTION_HIGH_PRICE_RATIO
                and supply_slope_1h > MM_DISTRIBUTION_SUPPLY_SLOPE_1H_MIN
                and volume_divergence
                and spoofing_like
            ):
                tag = "[高危黑名单]"

            if tag:
                anomalies_tags[item_id] = tag
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        redis_client.delete(MARKET_MAKER_TAGS_KEY)
        if anomalies_tags:
            redis_client.hset(
                MARKET_MAKER_TAGS_KEY,
                mapping={str(item_id): tag for item_id, tag in anomalies_tags.items()},
            )

        result = {
            "tagged_items_count": len(anomalies_tags),
            "tag_counts": tag_counts,
            "timestamp": now.isoformat(),
        }
        logger.info(
            "[Anomaly] Market maker detection finished: tagged_items_count={}",
            result["tagged_items_count"],
        )
        return result
    finally:
        session.close()


def _gap_severity(gap_minutes: int) -> str:
    if gap_minutes >= GAP_FILL_MAX_AGE_HOURS * 60:
        return "critical"
    return "warning"


def run_data_integrity_check(
    window_hours: int = DEFAULT_GAP_WINDOW_HOURS,
    tolerance_multiplier: float = GAP_TOLERANCE_MULTIPLIER,
    output_path: Optional[str] = None,
    write_logs: bool = True,
) -> dict:
    session = get_sessionmaker()()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    try:
        items = session.execute(
            select(Item.id, Item.market_hash_name, Item.priority)
        ).all()
        item_priority = {int(item_id): int(priority or 5) for item_id, _, priority in items}
        item_names = {int(item_id): str(name) for item_id, name, _ in items}

        rows = session.execute(
            select(PriceHistory.item_id, PriceHistory.platform, PriceHistory.time)
            .where(PriceHistory.time >= cutoff)
            .order_by(PriceHistory.item_id, PriceHistory.platform, PriceHistory.time.asc())
        ).all()

        grouped: dict[tuple[int, str], list[datetime]] = {}
        for item_id, platform, time_value in rows:
            grouped.setdefault((int(item_id), str(platform)), []).append(time_value)

        items_with_data = {key[0] for key in grouped.keys()}
        missing_items = [item_names[item_id] for item_id in item_priority.keys() if item_id not in items_with_data]

        gaps: list[dict] = []
        created_logs = 0
        for (item_id, platform), timestamps in grouped.items():
            if len(timestamps) < 2:
                continue

            priority = item_priority.get(item_id, 5)
            group = priority_to_group(priority)
            expected_interval = COLLECTION_INTERVAL_SECONDS.get(group, COLLECTION_INTERVAL_SECONDS["medium"])
            threshold = int(expected_interval * tolerance_multiplier)

            for prev_time, current_time in zip(timestamps, timestamps[1:]):
                delta_seconds = int((current_time - prev_time).total_seconds())
                if delta_seconds <= threshold:
                    continue

                gap_minutes = max(1, int(delta_seconds / 60))
                severity = _gap_severity(gap_minutes)
                gap_payload = {
                    "item_id": item_id,
                    "item_name": item_names.get(item_id, str(item_id)),
                    "platform": platform,
                    "gap_start": prev_time.isoformat(),
                    "gap_end": current_time.isoformat(),
                    "gap_minutes": gap_minutes,
                    "severity": severity,
                }
                gaps.append(gap_payload)

                if write_logs:
                    exists = session.execute(
                        select(DataGapLog.id).where(
                            DataGapLog.item_id == item_id,
                            DataGapLog.platform == platform,
                            DataGapLog.gap_start == prev_time,
                            DataGapLog.gap_end == current_time,
                        )
                    ).scalar_one_or_none()
                    if exists is None:
                        session.add(
                            DataGapLog(
                                item_id=item_id,
                                platform=platform,
                                gap_start=prev_time,
                                gap_end=current_time,
                                gap_duration_minutes=gap_minutes,
                                severity=severity,
                                fill_status="pending",
                                fill_method=None,
                                filled_points=0,
                                gap_reason="missing_snapshot",
                                notes="auto-detected",
                            )
                        )
                        created_logs += 1

        if write_logs:
            session.commit()

        report = {
            "items_total": len(item_priority),
            "items_with_data": len(items_with_data),
            "missing_items": missing_items,
            "gaps_found": len(gaps),
            "gap_records_created": created_logs,
            "timestamp": now.isoformat(),
            "window_hours": window_hours,
            "details": gaps[:200],
        }

        if output_path or DEFAULT_REPORT_DIR:
            output_dir = Path(output_path or DEFAULT_REPORT_DIR)
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = output_dir / f"data_quality_{now.strftime('%Y%m%d_%H%M%S')}.json"
            filename.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
            report["report_path"] = str(filename)

        return report
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
