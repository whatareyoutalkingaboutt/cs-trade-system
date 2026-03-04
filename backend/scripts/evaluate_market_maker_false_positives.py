#!/usr/bin/env python3
"""
Evaluate false-positive rate for market-maker tiered alerts.

Method:
- Load `alert_logs` rows with trigger_type=market_maker_alerts.
- For each alert, compare later BUFF price movement in a forward horizon.
- If expected direction is not reached, count as false positive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from loguru import logger
from sqlalchemy import select, text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.database import get_sessionmaker
from backend.models import PriceHistory


LONG_TYPES = {"washout_phase", "markup_phase", "accumulation_phase"}
SHORT_TYPES = {"distribution_risk"}


def _parse_iso_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            ts = datetime.fromisoformat(text_value)
        except ValueError:
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _chunked(values: list[int], size: int) -> Iterable[list[int]]:
    chunk_size = max(1, int(size))
    for idx in range(0, len(values), chunk_size):
        yield values[idx : idx + chunk_size]


def _normalize_type(payload_type: Any, message: str) -> str:
    text_type = str(payload_type or "").strip().lower()
    if text_type:
        return text_type
    msg = str(message or "")
    if "高危黑名单" in msg:
        return "distribution_risk"
    if "主升浪开启" in msg:
        return "markup_phase"
    if "疑似吸筹" in msg:
        return "accumulation_phase"
    if "洗盘" in msg:
        return "washout_phase"
    return "unknown"


def _price_window_returns(
    series: list[tuple[datetime, float]],
    event_ts: datetime,
    horizon_hours: int,
) -> tuple[float, float, float] | None:
    if not series:
        return None
    times = [row[0] for row in series]
    prices = [row[1] for row in series]

    entry_idx = bisect_left(times, event_ts)
    if entry_idx >= len(prices):
        entry_idx = len(prices) - 1
    entry_price = prices[entry_idx]
    if entry_price <= 0:
        return None

    left = bisect_right(times, event_ts)
    right = bisect_right(times, event_ts + timedelta(hours=max(1, int(horizon_hours))))
    if right <= left:
        return None
    window = prices[left:right]
    if not window:
        return None
    max_ret = (max(window) - entry_price) / entry_price * 100.0
    min_ret = (min(window) - entry_price) / entry_price * 100.0
    end_ret = (window[-1] - entry_price) / entry_price * 100.0
    return end_ret, max_ret, min_ret


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate market-maker alert false positives.")
    parser.add_argument("--days", type=int, default=7, help="Lookback days for alert logs.")
    parser.add_argument("--horizon-hours", type=int, default=24, help="Forward window for evaluation.")
    parser.add_argument("--up-threshold-pct", type=float, default=2.0, help="Long signal success threshold.")
    parser.add_argument("--down-threshold-pct", type=float, default=2.0, help="Short signal success threshold.")
    parser.add_argument("--report", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(args.days)))

    session = get_sessionmaker()()
    try:
        rows = session.execute(
            text(
                """
                SELECT event_time, item_id, message, payload
                FROM alert_logs
                WHERE trigger_type = 'market_maker_alerts'
                  AND event_time >= :cutoff
                ORDER BY event_time ASC
                """
            ),
            {"cutoff": cutoff},
        ).fetchall()
    finally:
        session.close()

    alerts: list[dict[str, Any]] = []
    for event_time, item_id, message, payload in rows:
        ts = _parse_iso_ts(event_time)
        if ts is None:
            continue
        if item_id is None:
            continue
        payload_data: dict[str, Any] = {}
        if isinstance(payload, dict):
            payload_data = payload
        elif isinstance(payload, str):
            try:
                loaded = json.loads(payload)
                if isinstance(loaded, dict):
                    payload_data = loaded
            except Exception:
                payload_data = {}

        signal_type = _normalize_type(payload_data.get("type"), str(message or ""))
        if signal_type not in LONG_TYPES and signal_type not in SHORT_TYPES:
            continue
        alerts.append(
            {
                "event_time": ts,
                "item_id": int(item_id),
                "signal_type": signal_type,
            }
        )

    if not alerts:
        raise SystemExit("未找到可评估的 market_maker_alerts 告警。")

    item_ids = sorted({int(row["item_id"]) for row in alerts})
    min_ts = min(row["event_time"] for row in alerts) - timedelta(hours=2)
    max_ts = max(row["event_time"] for row in alerts) + timedelta(hours=max(1, int(args.horizon_hours)) + 2)

    session = get_sessionmaker()()
    price_series: dict[int, list[tuple[datetime, float]]] = {}
    try:
        for chunk in _chunked(item_ids, 200):
            rows = session.execute(
                select(
                    PriceHistory.item_id,
                    PriceHistory.time,
                    PriceHistory.price,
                )
                .where(
                    PriceHistory.platform == "buff",
                    PriceHistory.item_id.in_(chunk),
                    PriceHistory.time >= min_ts,
                    PriceHistory.time <= max_ts,
                )
                .order_by(PriceHistory.item_id.asc(), PriceHistory.time.asc())
            ).all()
            for item_id, time_value, price_value in rows:
                if price_value is None:
                    continue
                ts = _parse_iso_ts(time_value)
                if ts is None:
                    continue
                price_series.setdefault(int(item_id), []).append((ts, float(price_value)))
    finally:
        session.close()

    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0, "false_positive": 0, "insufficient": 0})
    all_total = 0
    all_success = 0
    all_false_positive = 0
    all_insufficient = 0

    for alert in alerts:
        signal_type = str(alert["signal_type"])
        item_id = int(alert["item_id"])
        event_ts = alert["event_time"]
        result = _price_window_returns(
            series=price_series.get(item_id, []),
            event_ts=event_ts,
            horizon_hours=args.horizon_hours,
        )

        stats[signal_type]["total"] += 1
        all_total += 1

        if result is None:
            stats[signal_type]["insufficient"] += 1
            all_insufficient += 1
            continue

        _, max_ret, min_ret = result
        if signal_type in LONG_TYPES:
            hit = max_ret >= float(args.up_threshold_pct)
        else:
            hit = min_ret <= -float(args.down_threshold_pct)

        if hit:
            stats[signal_type]["success"] += 1
            all_success += 1
        else:
            stats[signal_type]["false_positive"] += 1
            all_false_positive += 1

    per_type: list[dict[str, Any]] = []
    for signal_type, row in sorted(stats.items(), key=lambda pair: pair[0]):
        valid = row["total"] - row["insufficient"]
        fp_rate = (row["false_positive"] / valid * 100.0) if valid > 0 else None
        hit_rate = (row["success"] / valid * 100.0) if valid > 0 else None
        per_type.append(
            {
                "signal_type": signal_type,
                "total": row["total"],
                "insufficient": row["insufficient"],
                "valid": valid,
                "success": row["success"],
                "false_positive": row["false_positive"],
                "hit_rate_pct": None if hit_rate is None else round(hit_rate, 2),
                "false_positive_rate_pct": None if fp_rate is None else round(fp_rate, 2),
            }
        )

    all_valid = all_total - all_insufficient
    overall_fp_rate = (all_false_positive / all_valid * 100.0) if all_valid > 0 else None
    overall_hit_rate = (all_success / all_valid * 100.0) if all_valid > 0 else None

    report = {
        "generated_at": now.isoformat(),
        "inputs": {
            "days": int(args.days),
            "horizon_hours": int(args.horizon_hours),
            "up_threshold_pct": float(args.up_threshold_pct),
            "down_threshold_pct": float(args.down_threshold_pct),
        },
        "overall": {
            "total": all_total,
            "insufficient": all_insufficient,
            "valid": all_valid,
            "success": all_success,
            "false_positive": all_false_positive,
            "hit_rate_pct": None if overall_hit_rate is None else round(overall_hit_rate, 2),
            "false_positive_rate_pct": None if overall_fp_rate is None else round(overall_fp_rate, 2),
        },
        "per_type": per_type,
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.report:
        path = Path(args.report).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
        logger.success("报告已写入 {}", path)


if __name__ == "__main__":
    main()

