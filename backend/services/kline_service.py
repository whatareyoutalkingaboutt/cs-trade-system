from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import select

from backend.core.cache import KLINE_TTL_SECONDS, cache_kline, get_csqaq_metric_series, get_kline
from backend.core.database import get_sessionmaker
from backend.models import PriceHistory
from backend.scrapers.csqaq_scraper import CSQAQScraper
from backend.services.steamdt_price_service import load_csqaq_goods_snapshot


DEFAULT_INTERVAL = "1h"
DEFAULT_LOOKBACK_DAYS_BY_INTERVAL = {
    "1h": 7,
    "4h": 30,
    "1d": 30,
    "1w": 365,
}
CSQAQ_PERIOD_MAP = {
    "1h": "1hour",
    "1d": "1day",
}
CSQAQ_PLATFORM_MAP = {
    "buff": 1,
    "youpin": 2,
    "youyou": 2,
}


@dataclass(frozen=True)
class KlineCandle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    currency: str


def _normalize_interval(interval: str) -> str:
    interval = interval.strip().lower()
    if interval in {"1h", "hour", "hourly"}:
        return "1h"
    if interval in {"4h", "4hour", "4hours"}:
        return "4h"
    if interval in {"1d", "day", "daily"}:
        return "1d"
    if interval in {"1w", "week", "weekly"}:
        return "1w"
    raise ValueError("interval must be '1h', '4h', '1d' or '1w'")


def _bucket_start(ts: datetime, interval: str) -> datetime:
    ts = ts.astimezone(timezone.utc)
    if interval == "1h":
        return ts.replace(minute=0, second=0, microsecond=0)
    if interval == "4h":
        hour = (ts.hour // 4) * 4
        return ts.replace(hour=hour, minute=0, second=0, microsecond=0)
    if interval == "1d":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "1w":
        day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())
    raise ValueError("interval must be '1h', '4h', '1d' or '1w'")


def _serialize_candle(candle: KlineCandle) -> dict:
    payload = asdict(candle)
    payload["time"] = candle.time.isoformat()
    payload["open"] = round(payload["open"], 2)
    payload["high"] = round(payload["high"], 2)
    payload["low"] = round(payload["low"], 2)
    payload["close"] = round(payload["close"], 2)
    return payload


def _parse_iso_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        ts = value
    else:
        ts = datetime.fromisoformat(str(value))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _aggregate_candles(candles: list[dict], target_interval: str) -> list[dict]:
    if not candles:
        return []
    if target_interval in {"1h", "1d"}:
        return candles

    sorted_rows = sorted(candles, key=lambda row: _parse_iso_time(str(row.get("time"))))
    aggregated: list[dict] = []
    current_bucket: Optional[datetime] = None
    current: Optional[dict] = None

    for row in sorted_rows:
        try:
            ts = _parse_iso_time(str(row.get("time")))
            open_price = float(row.get("open", 0.0))
            high_price = float(row.get("high", 0.0))
            low_price = float(row.get("low", 0.0))
            close_price = float(row.get("close", 0.0))
            volume = int(row.get("volume") or 0)
            currency = str(row.get("currency") or "CNY")
        except Exception:
            continue

        bucket = _bucket_start(ts, target_interval)
        if current_bucket is None or bucket != current_bucket:
            if current is not None:
                aggregated.append(current)
            current_bucket = bucket
            current = {
                "time": bucket.isoformat(),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
                "volume": volume,
                "currency": currency,
            }
            continue

        if current is None:
            continue
        current["high"] = round(max(float(current["high"]), high_price), 2)
        current["low"] = round(min(float(current["low"]), low_price), 2)
        current["close"] = round(close_price, 2)
        current["volume"] = int(current.get("volume", 0)) + volume

    if current is not None:
        aggregated.append(current)
    return aggregated


def _source_interval_for_target(interval: str) -> str:
    if interval in {"1h", "4h"}:
        return "1h"
    return "1d"


def _extract_ohlcv_rows(rows: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        try:
            normalized.append(
                {
                    "time": str(row.get("time")),
                    "open": round(float(row.get("open", 0.0)), 2),
                    "high": round(float(row.get("high", 0.0)), 2),
                    "low": round(float(row.get("low", 0.0)), 2),
                    "close": round(float(row.get("close", 0.0)), 2),
                    "volume": int(row.get("volume") or 0),
                    "currency": str(row.get("currency") or "CNY"),
                }
            )
        except Exception:
            continue
    normalized.sort(key=lambda row: _parse_iso_time(str(row.get("time"))))
    return normalized


def _snapshot_sell_price(row: dict, platform: str) -> Optional[float]:
    key = "buff_sell_price" if platform == "buff" else "yyyp_sell_price"
    value = row.get(key)
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except Exception:
        return None


def _ensure_live_candle(
    kline: list[dict],
    interval: str,
    market_hash_name: str,
    platform: str,
) -> list[dict]:
    row = _find_csqaq_snapshot_row(market_hash_name)
    if not row:
        return kline

    snapshot_close = _snapshot_sell_price(row, platform)
    if snapshot_close is None:
        return kline

    now_bucket = _bucket_start(datetime.now(timezone.utc), interval)
    if not kline:
        return [
            {
                "time": now_bucket.isoformat(),
                "open": snapshot_close,
                "high": snapshot_close,
                "low": snapshot_close,
                "close": snapshot_close,
                "volume": 0,
                "currency": "CNY",
            }
        ]

    rows = sorted(kline, key=lambda item: _parse_iso_time(str(item.get("time"))))
    last = dict(rows[-1])
    last_bucket = _bucket_start(_parse_iso_time(str(last.get("time"))), interval)
    last_close = float(last.get("close", snapshot_close))

    if last_bucket == now_bucket:
        last["close"] = round(snapshot_close, 2)
        last["high"] = round(max(float(last.get("high", snapshot_close)), snapshot_close), 2)
        last["low"] = round(min(float(last.get("low", snapshot_close)), snapshot_close), 2)
        rows[-1] = last
        return rows

    open_price = round(last_close, 2)
    rows.append(
        {
            "time": now_bucket.isoformat(),
            "open": open_price,
            "high": round(max(open_price, snapshot_close), 2),
            "low": round(min(open_price, snapshot_close), 2),
            "close": round(snapshot_close, 2),
            "volume": 0,
            "currency": "CNY",
        }
    )
    return rows


def _estimate_live_volume_from_listings(series: list[dict], interval: str) -> int:
    if not series:
        return 0
    now_bucket = _bucket_start(datetime.now(timezone.utc), interval)
    values: list[float] = []
    for row in series:
        try:
            ts = _parse_iso_time(str(row.get("time")))
            value = float(row.get("value"))
        except Exception:
            continue
        if _bucket_start(ts, interval) == now_bucket:
            values.append(value)
    if len(values) < 2:
        return 0
    return int(abs(max(values) - min(values)))


def _patch_live_candle_volume(kline: list[dict], interval: str, estimated_volume: int) -> list[dict]:
    if not kline or estimated_volume <= 0:
        return kline
    rows = sorted(kline, key=lambda row: _parse_iso_time(str(row.get("time"))))
    last = dict(rows[-1])
    last_bucket = _bucket_start(_parse_iso_time(str(last.get("time"))), interval)
    now_bucket = _bucket_start(datetime.now(timezone.utc), interval)
    if last_bucket != now_bucket:
        return rows

    current_volume = int(last.get("volume") or 0)
    if estimated_volume > current_volume:
        last["volume"] = estimated_volume
        rows[-1] = last
    return rows


def _compute_candles(rows: Iterable[tuple], interval: str) -> list[KlineCandle]:
    candles: list[KlineCandle] = []
    current_bucket: Optional[datetime] = None
    open_price = high_price = low_price = close_price = 0.0
    volume_sum = 0
    currency = ""

    for time_value, price_value, volume_value, currency_value in rows:
        if price_value is None:
            continue
        price = float(price_value)
        bucket = _bucket_start(time_value, interval)

        if current_bucket is None or bucket != current_bucket:
            if current_bucket is not None:
                candles.append(
                    KlineCandle(
                        time=current_bucket,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume_sum,
                        currency=currency,
                    )
                )
            current_bucket = bucket
            open_price = price
            high_price = price
            low_price = price
            close_price = price
            volume_sum = int(volume_value or 0)
            currency = str(currency_value or "CNY")
        else:
            if price > high_price:
                high_price = price
            if price < low_price:
                low_price = price
            close_price = price
            volume_sum += int(volume_value or 0)

    if current_bucket is not None:
        candles.append(
            KlineCandle(
                time=current_bucket,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume_sum,
                currency=currency,
            )
        )

    return candles


def generate_kline(
    item_id: int,
    platform: str,
    interval: str = DEFAULT_INTERVAL,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
    ttl: int = KLINE_TTL_SECONDS,
) -> list[dict]:
    interval = _normalize_interval(interval)

    if start_time is None and end_time is None and lookback_days is None:
        lookback_days = DEFAULT_LOOKBACK_DAYS_BY_INTERVAL.get(interval, 7)

    if start_time is None and lookback_days is not None:
        start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    if end_time is None:
        end_time = datetime.now(timezone.utc)

    if use_cache and lookback_days is not None:
        cached = get_kline(item_id, platform, interval)
        if cached is not None:
            return cached

    session = get_sessionmaker()()
    try:
        stmt = select(
            PriceHistory.time,
            PriceHistory.price,
            PriceHistory.volume,
            PriceHistory.currency,
        ).where(
            PriceHistory.item_id == item_id,
            PriceHistory.platform == platform,
            PriceHistory.time >= start_time,
            PriceHistory.time <= end_time,
        ).order_by(PriceHistory.time.asc())

        rows = session.execute(stmt).all()
        candles = _compute_candles(rows, interval)
        payload = [_serialize_candle(candle) for candle in candles]

        if use_cache and lookback_days is not None:
            cache_kline(item_id, platform, interval, payload, ttl=ttl)

        return payload
    finally:
        session.close()


def _moving_average(values: list[float], window: int) -> list[Optional[float]]:
    if window <= 0:
        return [None for _ in values]
    result: list[Optional[float]] = []
    running_sum = 0.0
    for idx, value in enumerate(values):
        running_sum += value
        if idx >= window:
            running_sum -= values[idx - window]
        if idx + 1 < window:
            result.append(None)
        else:
            result.append(round(running_sum / window, 2))
    return result


def _volatility(values: list[float], window: int) -> list[Optional[float]]:
    if window <= 1:
        return [None for _ in values]
    result: list[Optional[float]] = []
    for idx in range(len(values)):
        if idx + 1 < window:
            result.append(None)
            continue
        slice_values = values[idx + 1 - window: idx + 1]
        mean = sum(slice_values) / window
        variance = sum((v - mean) ** 2 for v in slice_values) / window
        result.append(round((variance ** 0.5), 4))
    return result


def attach_indicators(
    kline: list[dict],
    ma_windows: Iterable[int] = (5, 10, 30),
    volatility_window: int = 10,
) -> list[dict]:
    if not kline:
        return []

    closes = [float(row["close"]) for row in kline]
    ma_results = {window: _moving_average(closes, window) for window in ma_windows}
    volatility = _volatility(closes, volatility_window)

    enriched = []
    for idx, row in enumerate(kline):
        payload = dict(row)
        for window, series in ma_results.items():
            payload[f"ma{window}"] = series[idx]
        payload["volatility"] = volatility[idx]
        enriched.append(payload)

    return enriched


def generate_kline_with_indicators(
    item_id: int,
    platform: str,
    interval: str = DEFAULT_INTERVAL,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> list[dict]:
    kline = generate_kline(
        item_id=item_id,
        platform=platform,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
        lookback_days=lookback_days,
        use_cache=use_cache,
    )
    if not kline:
        logger.info("[Kline] No data found for item_id={} platform={}", item_id, platform)
        return []
    return attach_indicators(kline)


def _find_csqaq_snapshot_row(market_hash_name: str) -> Optional[dict]:
    rows = load_csqaq_goods_snapshot(use_cache=True)
    normalized = market_hash_name.strip().lower()
    for row in rows:
        name = str(row.get("market_hash_name") or "").strip().lower()
        if name == normalized:
            return row
    return None


def _filter_series_by_lookback(series: list[dict], lookback_days: int) -> list[dict]:
    if lookback_days <= 0:
        return series
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    filtered: list[dict] = []
    for row in series:
        try:
            ts = datetime.fromisoformat(str(row.get("time")))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            filtered.append(row)
    return filtered


def generate_csqaq_kline_with_indicators(
    market_hash_name: str,
    platform: str,
    interval: str = DEFAULT_INTERVAL,
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
    ttl: int = KLINE_TTL_SECONDS,
) -> tuple[int, list[dict]]:
    normalized_interval = _normalize_interval(interval)
    source_interval = _source_interval_for_target(normalized_interval)
    normalized_platform = (platform or "buff").strip().lower()

    plat = CSQAQ_PLATFORM_MAP.get(normalized_platform)
    if plat is None:
        raise ValueError("platform must be buff or youpin")

    periods = CSQAQ_PERIOD_MAP[source_interval]
    row = _find_csqaq_snapshot_row(market_hash_name)
    if not row:
        raise LookupError("Item not found")

    try:
        good_id = int(row.get("id"))
    except (TypeError, ValueError) as exc:
        raise LookupError("Item not found") from exc

    cache_platform = f"csqaq_{normalized_platform}"
    if use_cache:
        cached = get_kline(good_id, cache_platform, normalized_interval)
        if cached is not None:
            base = _extract_ohlcv_rows(cached)
            base = _ensure_live_candle(
                kline=base,
                interval=normalized_interval,
                market_hash_name=market_hash_name,
                platform=normalized_platform,
            )
            return good_id, attach_indicators(base)

    with CSQAQScraper() as scraper:
        raw_points = scraper.get_chart_all(
            good_id=good_id,
            plat=plat,
            periods=periods,
            max_time=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

    if lookback_days is None:
        lookback_days = DEFAULT_LOOKBACK_DAYS_BY_INTERVAL.get(normalized_interval, 7)

    payload_all: list[dict] = []
    for point in raw_points:
        ts_raw = point.get("t")
        try:
            ts_ms = int(float(ts_raw))
        except (TypeError, ValueError):
            continue
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        payload_all.append(
            {
                "time": ts.isoformat(),
                "open": round(float(point.get("o", 0.0)), 2),
                "high": round(float(point.get("h", 0.0)), 2),
                "low": round(float(point.get("l", 0.0)), 2),
                "close": round(float(point.get("c", 0.0)), 2),
                "volume": int(point.get("v") or 0),
                "currency": "CNY",
            }
        )

    payload_all.sort(key=lambda row: _parse_iso_time(str(row.get("time"))))
    payload = _aggregate_candles(payload_all, normalized_interval)
    payload = _ensure_live_candle(
        kline=payload,
        interval=normalized_interval,
        market_hash_name=market_hash_name,
        platform=normalized_platform,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    payload = [
        row
        for row in payload
        if _parse_iso_time(str(row.get("time"))) >= cutoff
    ]

    data = attach_indicators(payload)
    if use_cache:
        cache_kline(good_id, cache_platform, normalized_interval, data, ttl=ttl)
    return good_id, data


def _aggregate_metric_series(series: list[dict], interval: str, mode: str = "avg") -> list[dict]:
    if not series:
        return []
    buckets: dict[datetime, list[float]] = {}
    for row in series:
        try:
            ts = _parse_iso_time(str(row.get("time")))
            value = float(row.get("value"))
        except Exception:
            continue
        bucket = _bucket_start(ts, interval)
        buckets.setdefault(bucket, []).append(value)

    result: list[dict] = []
    for bucket in sorted(buckets.keys()):
        values = buckets[bucket]
        if not values:
            continue
        if mode == "last":
            value = values[-1]
        elif mode == "max":
            value = max(values)
        elif mode == "min":
            value = min(values)
        elif mode == "sum":
            value = sum(values)
        else:
            value = sum(values) / len(values)
        result.append({"time": bucket.isoformat(), "value": round(value, 4)})
    return result


def _align_series(reference: list[dict], target: list[dict]) -> list[dict]:
    if not reference:
        return []
    if not target:
        return [{"time": row.get("time"), "value": None} for row in reference]

    target_rows = sorted(target, key=lambda row: _parse_iso_time(str(row.get("time"))))
    ref_rows = sorted(reference, key=lambda row: _parse_iso_time(str(row.get("time"))))

    aligned: list[dict] = []
    cursor = 0
    latest: Optional[float] = None
    for ref in ref_rows:
        ref_time = _parse_iso_time(str(ref.get("time")))
        while cursor < len(target_rows):
            row = target_rows[cursor]
            try:
                row_time = _parse_iso_time(str(row.get("time")))
                row_value = float(row.get("value"))
            except Exception:
                cursor += 1
                continue
            if row_time <= ref_time:
                latest = row_value
                cursor += 1
                continue
            break
        aligned.append({"time": ref_time.isoformat(), "value": latest})
    return aligned


def _periods_for_days(interval: str, days: int) -> int:
    if days <= 0:
        return 1
    if interval == "1h":
        return max(1, days * 24)
    if interval == "4h":
        return max(1, days * 6)
    if interval == "1d":
        return max(1, days)
    if interval == "1w":
        return max(1, days // 7)
    return max(1, days)


def _series_latest(series: list[dict]) -> Optional[float]:
    if not series:
        return None
    value = series[-1].get("value")
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _pct_change(current: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if current is None or baseline is None:
        return None
    if baseline == 0:
        return None
    return (current - baseline) / baseline * 100.0


def _rolling_avg(values: list[Optional[float]], window: int) -> list[Optional[float]]:
    if window <= 0:
        return [None for _ in values]
    result: list[Optional[float]] = []
    for idx in range(len(values)):
        if idx + 1 < window:
            result.append(None)
            continue
        chunk = [v for v in values[idx + 1 - window: idx + 1] if v is not None]
        if not chunk:
            result.append(None)
            continue
        result.append(sum(chunk) / len(chunk))
    return result


def _rolling_std(values: list[Optional[float]], window: int) -> list[Optional[float]]:
    if window <= 1:
        return [None for _ in values]
    result: list[Optional[float]] = []
    for idx in range(len(values)):
        if idx + 1 < window:
            result.append(None)
            continue
        chunk = [v for v in values[idx + 1 - window: idx + 1] if v is not None]
        if len(chunk) < 2:
            result.append(None)
            continue
        avg = sum(chunk) / len(chunk)
        variance = sum((v - avg) ** 2 for v in chunk) / len(chunk)
        result.append(variance ** 0.5)
    return result


def _build_platform_indicators(
    interval: str,
    price_series: list[dict],
    volume_series: list[dict],
    listings_series: list[dict],
    bid_support_series: list[dict],
) -> dict:
    aligned_bid = _align_series(price_series, bid_support_series)
    aligned_listings = _align_series(price_series, listings_series)

    spread_ratio_series: list[dict] = []
    turnover_ratio_series: list[dict] = []
    panic_index_series: list[dict] = []

    prices: list[Optional[float]] = []
    volumes: list[Optional[float]] = []
    listings: list[Optional[float]] = []

    for idx, price_row in enumerate(price_series):
        try:
            price = float(price_row.get("value"))
        except Exception:
            price = None
        try:
            volume = float(volume_series[idx].get("value")) if idx < len(volume_series) else None
        except Exception:
            volume = None
        bid = aligned_bid[idx].get("value") if idx < len(aligned_bid) else None
        listing = aligned_listings[idx].get("value") if idx < len(aligned_listings) else None

        prices.append(price)
        volumes.append(volume)
        listings.append(float(listing) if listing is not None else None)

        spread = None
        if price is not None and bid is not None and price > 0:
            spread = (price - float(bid)) / price * 100.0
        spread_ratio_series.append(
            {
                "time": price_row.get("time"),
                "value": round(spread, 4) if spread is not None else None,
            }
        )

        turnover = None
        if volume is not None and listing is not None and float(listing) > 0:
            turnover = volume / float(listing) * 100.0
        turnover_ratio_series.append(
            {
                "time": price_row.get("time"),
                "value": round(turnover, 4) if turnover is not None else None,
            }
        )

    if interval == "1h":
        panic_window = 24 * 7
    elif interval == "4h":
        panic_window = 6 * 7
    elif interval == "1d":
        panic_window = 7
    else:
        panic_window = 4

    for idx, time_row in enumerate(price_series):
        cur_volume = volumes[idx]
        if idx <= 0 or cur_volume is None:
            panic_index_series.append({"time": time_row.get("time"), "value": None, "signal": False})
            continue

        start = max(0, idx - panic_window)
        baseline_chunk = [v for v in volumes[start:idx] if v is not None]
        baseline_avg = sum(baseline_chunk) / len(baseline_chunk) if baseline_chunk else None

        panic_value = None
        if baseline_avg and baseline_avg > 0:
            panic_value = cur_volume / baseline_avg * 100.0

        price_drop = _pct_change(prices[idx], prices[idx - 1]) if prices[idx - 1] is not None else None
        listing_change = (
            _pct_change(listings[idx], listings[idx - 1])
            if listings[idx - 1] is not None
            else None
        )
        is_signal = bool(
            panic_value is not None
            and panic_value >= 180.0
            and price_drop is not None
            and price_drop <= -3.0
            and listing_change is not None
            and listing_change >= 5.0
        )
        panic_index_series.append(
            {
                "time": time_row.get("time"),
                "value": round(panic_value, 4) if panic_value is not None else None,
                "signal": is_signal,
            }
        )

    inventory_slope_3d_series: list[dict] = []
    inventory_slope_5d_series: list[dict] = []
    back_3d = _periods_for_days(interval, 3)
    back_5d = _periods_for_days(interval, 5)
    for idx, row in enumerate(price_series):
        slope_3d = None
        slope_5d = None
        if idx >= back_3d:
            slope_3d = _pct_change(listings[idx], listings[idx - back_3d])
        if idx >= back_5d:
            slope_5d = _pct_change(listings[idx], listings[idx - back_5d])
        inventory_slope_3d_series.append(
            {
                "time": row.get("time"),
                "value": round(slope_3d, 4) if slope_3d is not None else None,
            }
        )
        inventory_slope_5d_series.append(
            {
                "time": row.get("time"),
                "value": round(slope_5d, 4) if slope_5d is not None else None,
            }
        )

    boll_window = 30 if interval in {"1d", "1w"} else 60
    sma = _rolling_avg(prices, boll_window)
    std = _rolling_std(prices, boll_window)
    bollinger_series: list[dict] = []
    for idx, row in enumerate(price_series):
        mid = sma[idx]
        dev = std[idx]
        upper = (mid + 2 * dev) if mid is not None and dev is not None else None
        lower = (mid - 2 * dev) if mid is not None and dev is not None else None
        bid = aligned_bid[idx].get("value") if idx < len(aligned_bid) else None
        modified_lower = lower
        if lower is not None and bid is not None:
            modified_lower = max(lower, float(bid))
        elif bid is not None:
            modified_lower = float(bid)
        bollinger_series.append(
            {
                "time": row.get("time"),
                "middle": round(mid, 4) if mid is not None else None,
                "upper": round(upper, 4) if upper is not None else None,
                "lower": round(lower, 4) if lower is not None else None,
                "modified_lower": round(modified_lower, 4) if modified_lower is not None else None,
            }
        )

    latest_panic = panic_index_series[-1] if panic_index_series else {"value": None, "signal": False}
    latest_boll = bollinger_series[-1] if bollinger_series else {}
    latest_inventory_3d = _series_latest(inventory_slope_3d_series)
    latest_inventory_5d = _series_latest(inventory_slope_5d_series)

    return {
        "series": {
            "spread_ratio_series": spread_ratio_series,
            "turnover_ratio_series": turnover_ratio_series,
            "panic_index_series": panic_index_series,
            "inventory_slope_3d_series": inventory_slope_3d_series,
            "inventory_slope_5d_series": inventory_slope_5d_series,
            "bollinger_series": bollinger_series,
        },
        "latest": {
            "spread_ratio_pct": _series_latest(spread_ratio_series),
            "turnover_ratio_pct": _series_latest(turnover_ratio_series),
            "panic_index_pct": (
                float(latest_panic["value"])
                if latest_panic.get("value") is not None
                else None
            ),
            "panic_signal": bool(latest_panic.get("signal")),
            "inventory_slope_3d_pct": latest_inventory_3d,
            "inventory_slope_5d_pct": latest_inventory_5d,
            "bollinger_middle": latest_boll.get("middle"),
            "bollinger_upper": latest_boll.get("upper"),
            "bollinger_lower": latest_boll.get("lower"),
            "bollinger_modified_lower": latest_boll.get("modified_lower"),
        },
    }


def _build_cross_indicators(
    buff_price_series: list[dict],
    youpin_price_series: list[dict],
    buff_bid_series: list[dict],
    buff_listings_series: list[dict],
    youpin_listings_series: list[dict],
) -> dict:
    aligned_buff_bid_for_youpin = _align_series(youpin_price_series, buff_bid_series)
    cross_drain_series: list[dict] = []
    for idx, row in enumerate(youpin_price_series):
        ask = row.get("value")
        bid = aligned_buff_bid_for_youpin[idx].get("value") if idx < len(aligned_buff_bid_for_youpin) else None
        value = None
        if ask is not None and bid is not None:
            ask_value = float(ask)
            if ask_value > 0:
                value = (float(bid) - ask_value) / ask_value * 100.0
        cross_drain_series.append(
            {
                "time": row.get("time"),
                "value": round(value, 4) if value is not None else None,
            }
        )

    aligned_buff_listing = _align_series(buff_price_series, buff_listings_series)
    aligned_youpin_listing = _align_series(buff_price_series, youpin_listings_series)
    liquidity_skew_series: list[dict] = []
    for idx, row in enumerate(buff_price_series):
        buff_listing = aligned_buff_listing[idx].get("value") if idx < len(aligned_buff_listing) else None
        youpin_listing = aligned_youpin_listing[idx].get("value") if idx < len(aligned_youpin_listing) else None
        value = None
        if buff_listing is not None and youpin_listing is not None and float(buff_listing) > 0:
            value = float(youpin_listing) / float(buff_listing) * 100.0
        liquidity_skew_series.append(
            {
                "time": row.get("time"),
                "value": round(value, 4) if value is not None else None,
            }
        )

    return {
        "series": {
            "cross_drain_series": cross_drain_series,
            "liquidity_skew_series": liquidity_skew_series,
        },
        "latest": {
            "cross_drain_index_pct": _series_latest(cross_drain_series),
            "liquidity_skew_pct": _series_latest(liquidity_skew_series),
        },
    }


def generate_csqaq_dual_platform_trends(
    market_hash_name: str,
    interval: str = DEFAULT_INTERVAL,
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> dict:
    normalized_interval = _normalize_interval(interval)
    if lookback_days is None:
        lookback_days = DEFAULT_LOOKBACK_DAYS_BY_INTERVAL.get(normalized_interval, 7)

    buff_item_id, buff_kline = generate_csqaq_kline_with_indicators(
        market_hash_name=market_hash_name,
        platform="buff",
        interval=normalized_interval,
        lookback_days=lookback_days,
        use_cache=use_cache,
    )
    youpin_item_id, youpin_kline = generate_csqaq_kline_with_indicators(
        market_hash_name=market_hash_name,
        platform="youpin",
        interval=normalized_interval,
        lookback_days=lookback_days,
        use_cache=use_cache,
    )
    item_id = buff_item_id or youpin_item_id

    buff_listing = _filter_series_by_lookback(
        get_csqaq_metric_series(item_id, "buff", "sell_listings"),
        lookback_days,
    )
    youpin_listing = _filter_series_by_lookback(
        get_csqaq_metric_series(item_id, "youpin", "sell_listings"),
        lookback_days,
    )
    buff_bid = _filter_series_by_lookback(
        get_csqaq_metric_series(item_id, "buff", "bid_price"),
        lookback_days,
    )
    youpin_bid = _filter_series_by_lookback(
        get_csqaq_metric_series(item_id, "youpin", "bid_price"),
        lookback_days,
    )

    if not buff_listing or not youpin_listing or not buff_bid or not youpin_bid:
        row = _find_csqaq_snapshot_row(market_hash_name)
        if row:
            updated_at = row.get("updated_at")
            if updated_at:
                if not buff_listing and row.get("buff_sell_num") is not None:
                    try:
                        buff_listing = [{"time": updated_at, "value": float(row.get("buff_sell_num"))}]
                    except (TypeError, ValueError):
                        pass
                if not youpin_listing and row.get("yyyp_sell_num") is not None:
                    try:
                        youpin_listing = [{"time": updated_at, "value": float(row.get("yyyp_sell_num"))}]
                    except (TypeError, ValueError):
                        pass
                if not buff_bid and row.get("buff_buy_price") is not None:
                    try:
                        buff_bid = [{"time": updated_at, "value": float(row.get("buff_buy_price"))}]
                    except (TypeError, ValueError):
                        pass
                if not youpin_bid and row.get("yyyp_buy_price") is not None:
                    try:
                        youpin_bid = [{"time": updated_at, "value": float(row.get("yyyp_buy_price"))}]
                    except (TypeError, ValueError):
                        pass

    buff_live_est_volume = _estimate_live_volume_from_listings(buff_listing, normalized_interval)
    youpin_live_est_volume = _estimate_live_volume_from_listings(youpin_listing, normalized_interval)
    buff_kline = _patch_live_candle_volume(buff_kline, normalized_interval, buff_live_est_volume)
    youpin_kline = _patch_live_candle_volume(youpin_kline, normalized_interval, youpin_live_est_volume)

    buff_price_series = [{"time": row["time"], "value": row["close"]} for row in buff_kline]
    buff_volume_series = [{"time": row["time"], "value": row.get("volume", 0)} for row in buff_kline]
    youpin_price_series = [{"time": row["time"], "value": row["close"]} for row in youpin_kline]
    youpin_volume_series = [{"time": row["time"], "value": row.get("volume", 0)} for row in youpin_kline]

    buff_listing_interval = _aggregate_metric_series(buff_listing, normalized_interval, mode="last")
    youpin_listing_interval = _aggregate_metric_series(youpin_listing, normalized_interval, mode="last")
    buff_bid_interval = _aggregate_metric_series(buff_bid, normalized_interval, mode="avg")
    youpin_bid_interval = _aggregate_metric_series(youpin_bid, normalized_interval, mode="avg")

    buff_indicators = _build_platform_indicators(
        interval=normalized_interval,
        price_series=buff_price_series,
        volume_series=buff_volume_series,
        listings_series=buff_listing_interval,
        bid_support_series=buff_bid_interval,
    )
    youpin_indicators = _build_platform_indicators(
        interval=normalized_interval,
        price_series=youpin_price_series,
        volume_series=youpin_volume_series,
        listings_series=youpin_listing_interval,
        bid_support_series=youpin_bid_interval,
    )
    cross_indicators = _build_cross_indicators(
        buff_price_series=buff_price_series,
        youpin_price_series=youpin_price_series,
        buff_bid_series=buff_bid_interval,
        buff_listings_series=buff_listing_interval,
        youpin_listings_series=youpin_listing_interval,
    )

    return {
        "item_id": item_id,
        "market_hash_name": market_hash_name,
        "interval": normalized_interval,
        "lookback_days": lookback_days,
        "platforms": {
            "buff": {
                "kline": buff_kline,
                "price_series": buff_price_series,
                "volume_series": buff_volume_series,
                "sell_listings_series": buff_listing_interval,
                "bid_support_series": buff_bid_interval,
                "indicator_series": buff_indicators["series"],
                "indicators": buff_indicators["latest"],
            },
            "youpin": {
                "kline": youpin_kline,
                "price_series": youpin_price_series,
                "volume_series": youpin_volume_series,
                "sell_listings_series": youpin_listing_interval,
                "bid_support_series": youpin_bid_interval,
                "indicator_series": youpin_indicators["series"],
                "indicators": youpin_indicators["latest"],
            },
        },
        "indicators": {
            "platforms": {
                "buff": buff_indicators["latest"],
                "youpin": youpin_indicators["latest"],
            },
            "cross": cross_indicators["latest"],
            "series": cross_indicators["series"],
        },
    }
