#!/usr/bin/env python3
"""
Backtest v2 timing strategies with recent snapshot history.

Outputs:
1) Six-strategy win rates and forward returns.
2) Score calibration report (bucketed by signal score).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from loguru import logger
from sqlalchemy import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.cache import SNAPSHOT_HISTORY_INDEX_KEY, get_dragonfly_client, get_snapshot_history
from backend.core.database import get_sessionmaker
from backend.models import PriceHistory
from backend.services.arbitrage_service import _evaluate_timing_strategies


@dataclass
class StrategyStats:
    signal: str
    samples: int = 0
    success: int = 0
    avg_end_return_pct: float = 0.0
    avg_max_return_pct: float = 0.0
    avg_min_return_pct: float = 0.0

    def update(self, end_ret: float, max_ret: float, min_ret: float, is_success: bool) -> None:
        self.samples += 1
        if is_success:
            self.success += 1
        self.avg_end_return_pct += end_ret
        self.avg_max_return_pct += max_ret
        self.avg_min_return_pct += min_ret

    def finalize(self) -> dict[str, Any]:
        if self.samples <= 0:
            return asdict(self)
        return {
            "signal": self.signal,
            "samples": self.samples,
            "success": self.success,
            "win_rate_pct": round(self.success / self.samples * 100.0, 2),
            "avg_end_return_pct": round(self.avg_end_return_pct / self.samples, 4),
            "avg_max_return_pct": round(self.avg_max_return_pct / self.samples, 4),
            "avg_min_return_pct": round(self.avg_min_return_pct / self.samples, 4),
        }


def _parse_iso_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            ts = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _chunked(values: list[int], size: int) -> Iterable[list[int]]:
    batch = max(1, int(size))
    for idx in range(0, len(values), batch):
        yield values[idx : idx + batch]


def _daily_kline_until(
    series: list[tuple[datetime, float, float]],
    until_ts: datetime,
    lookback_days: int,
) -> list[dict[str, Any]]:
    if not series:
        return []
    cutoff = until_ts - timedelta(days=max(1, int(lookback_days)))
    times = [row[0] for row in series]
    left = bisect_left(times, cutoff)
    right = bisect_right(times, until_ts)
    if right <= left:
        return []
    subset = series[left:right]
    grouped: dict[datetime, dict[str, float]] = {}
    for ts, price, volume in subset:
        bucket = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        row = grouped.get(bucket)
        if row is None:
            grouped[bucket] = {
                "o": price,
                "h": price,
                "l": price,
                "c": price,
                "v_sum": volume,
                "v_count": 1.0,
            }
            continue
        row["h"] = max(row["h"], price)
        row["l"] = min(row["l"], price)
        row["c"] = price
        row["v_sum"] += volume
        row["v_count"] += 1.0

    result: list[dict[str, Any]] = []
    for day, row in sorted(grouped.items(), key=lambda pair: pair[0]):
        denom = max(1.0, row["v_count"])
        result.append(
            {
                "t": day.isoformat(),
                "o": row["o"],
                "h": row["h"],
                "l": row["l"],
                "c": row["c"],
                "v": row["v_sum"] / denom,
            }
        )
    return result


def _forward_returns(
    series: list[tuple[datetime, float, float]],
    signal_ts: datetime,
    entry_price: float,
    horizon_hours: int,
) -> tuple[float, float, float] | None:
    if entry_price <= 0 or not series:
        return None
    times = [row[0] for row in series]
    start = bisect_right(times, signal_ts)
    end = bisect_right(times, signal_ts + timedelta(hours=max(1, int(horizon_hours))))
    if end <= start:
        return None
    window_prices = [row[1] for row in series[start:end] if row[1] > 0]
    if not window_prices:
        return None
    last_price = window_prices[-1]
    max_price = max(window_prices)
    min_price = min(window_prices)
    end_ret = (last_price - entry_price) / entry_price * 100.0
    max_ret = (max_price - entry_price) / entry_price * 100.0
    min_ret = (min_price - entry_price) / entry_price * 100.0
    return end_ret, max_ret, min_ret


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _score_buckets(records: list[dict[str, float]], bucket_count: int) -> list[dict[str, Any]]:
    if not records:
        return []
    rows = sorted(records, key=lambda row: row["score"])
    n = len(rows)
    k = max(1, int(bucket_count))
    result: list[dict[str, Any]] = []
    for bucket_idx in range(k):
        left = int(bucket_idx * n / k)
        right = int((bucket_idx + 1) * n / k)
        if right <= left:
            continue
        subset = rows[left:right]
        sample = len(subset)
        avg_score = sum(row["score"] for row in subset) / sample
        avg_max_ret = sum(row["max_ret"] for row in subset) / sample
        win_rate = sum(1 for row in subset if row["is_success"]) / sample * 100.0
        result.append(
            {
                "bucket": bucket_idx + 1,
                "samples": sample,
                "avg_score": round(avg_score, 4),
                "avg_max_return_pct": round(avg_max_ret, 4),
                "win_rate_pct": round(win_rate, 2),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest v2 six timing strategies.")
    parser.add_argument("--sample-items", type=int, default=300, help="Max item count sampled from snapshot history.")
    parser.add_argument("--lookback-hours", type=int, default=168, help="Only use snapshots in this recent horizon.")
    parser.add_argument("--lookback-points", type=int, default=2880, help="Max snapshot points loaded per item.")
    parser.add_argument("--min-history-points", type=int, default=24, help="Minimum points before evaluating signals.")
    parser.add_argument("--stride", type=int, default=3, help="Evaluate every N-th snapshot point.")
    parser.add_argument("--horizon-hours", type=int, default=24, help="Forward window for return evaluation.")
    parser.add_argument("--success-threshold-pct", type=float, default=2.0, help="Success threshold by forward max return.")
    parser.add_argument("--lookback-days-kline", type=int, default=40, help="Daily K build window for signal eval.")
    parser.add_argument("--sell-fee-rate", type=float, default=0.025, help="Buff sell fee rate used by strategy evaluator.")
    parser.add_argument("--score-buckets", type=int, default=5, help="Bucket count for score calibration.")
    parser.add_argument("--report", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max(1, int(args.lookback_hours)))
    client = get_dragonfly_client()

    raw_ids = client.smembers(SNAPSHOT_HISTORY_INDEX_KEY) or set()
    all_ids: list[int] = []
    for raw in raw_ids:
        try:
            all_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    all_ids = sorted(set(all_ids))
    if not all_ids:
        raise SystemExit("snapshot:history:index 为空，无法执行回测。")

    selected_history: dict[int, list[dict[str, Any]]] = {}
    min_points_required = max(2, int(args.min_history_points))
    for item_id in all_ids:
        rows = get_snapshot_history(item_id, limit=max(1, int(args.lookback_points)))
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _parse_iso_ts(row.get("updated_at"))
            if ts is None or ts < cutoff:
                continue
            normalized.append({**row, "_ts": ts})
        normalized.sort(key=lambda row: row["_ts"])
        if len(normalized) < min_points_required + 1:
            continue
        selected_history[item_id] = normalized
        if len(selected_history) >= max(1, int(args.sample_items)):
            break

    if not selected_history:
        raise SystemExit("最近窗口内可回测快照不足，请增加 lookback-hours 或降低 min-history-points。")

    item_ids = sorted(selected_history.keys())
    min_ts = min(rows[0]["_ts"] for rows in selected_history.values())
    max_ts = max(rows[-1]["_ts"] for rows in selected_history.values())
    query_start = min_ts - timedelta(days=max(1, int(args.lookback_days_kline)) + 2)
    query_end = max_ts + timedelta(hours=max(1, int(args.horizon_hours)) + 2)

    session = get_sessionmaker()()
    buff_series: dict[int, list[tuple[datetime, float, float]]] = {}
    try:
        for chunk in _chunked(item_ids, 200):
            rows = session.execute(
                select(
                    PriceHistory.item_id,
                    PriceHistory.time,
                    PriceHistory.price,
                    PriceHistory.volume,
                )
                .where(
                    PriceHistory.item_id.in_(chunk),
                    PriceHistory.platform == "buff",
                    PriceHistory.time >= query_start,
                    PriceHistory.time <= query_end,
                )
                .order_by(PriceHistory.item_id.asc(), PriceHistory.time.asc())
            ).all()
            for item_id, time_value, price_value, volume_value in rows:
                if price_value is None:
                    continue
                ts = _parse_iso_ts(time_value)
                if ts is None:
                    continue
                buff_series.setdefault(int(item_id), []).append(
                    (ts, float(price_value), float(volume_value or 0.0))
                )
    finally:
        session.close()

    strategy_stats: dict[str, StrategyStats] = {}
    scored_points: list[dict[str, float]] = []
    evaluated_points = 0

    stride = max(1, int(args.stride))
    for item_id, history in selected_history.items():
        series = buff_series.get(item_id, [])
        if len(series) < 2:
            continue
        for idx in range(min_points_required, len(history), stride):
            point = history[idx]
            point_ts = point["_ts"]
            daily_kline = _daily_kline_until(
                series=series,
                until_ts=point_ts,
                lookback_days=args.lookback_days_kline,
            )
            strategy_eval = _evaluate_timing_strategies(
                row=point,
                snapshot_history_rows=history[: idx + 1],
                daily_kline=daily_kline,
                sell_fee_rate=float(args.sell_fee_rate),
            )
            signals = strategy_eval.get("signals") or []
            if not signals:
                continue

            entry_price = float(point.get("buff_sell_price") or 0.0)
            forward = _forward_returns(
                series=series,
                signal_ts=point_ts,
                entry_price=entry_price,
                horizon_hours=args.horizon_hours,
            )
            if forward is None:
                continue
            end_ret, max_ret, min_ret = forward
            is_success = max_ret >= float(args.success_threshold_pct)
            evaluated_points += 1

            for signal in signals:
                signal_name = str(signal.get("name") or "").strip() or "UNKNOWN"
                stats = strategy_stats.setdefault(signal_name, StrategyStats(signal=signal_name))
                stats.update(end_ret=end_ret, max_ret=max_ret, min_ret=min_ret, is_success=is_success)

            top_signal = signals[0]
            scored_points.append(
                {
                    "score": float(top_signal.get("score") or 0.0),
                    "max_ret": max_ret,
                    "is_success": 1.0 if is_success else 0.0,
                }
            )

    strategy_rows = [stats.finalize() for stats in strategy_stats.values()]
    strategy_rows.sort(key=lambda row: int(row.get("samples", 0)), reverse=True)

    score_corr = None
    if scored_points:
        xs = [row["score"] for row in scored_points]
        ys = [row["max_ret"] for row in scored_points]
        corr = _pearson(xs, ys)
        score_corr = None if corr is None else round(corr, 4)

    score_buckets = _score_buckets(scored_points, bucket_count=args.score_buckets)
    report = {
        "generated_at": now.isoformat(),
        "inputs": {
            "sample_items": len(item_ids),
            "lookback_hours": int(args.lookback_hours),
            "lookback_points": int(args.lookback_points),
            "min_history_points": int(args.min_history_points),
            "stride": int(args.stride),
            "horizon_hours": int(args.horizon_hours),
            "success_threshold_pct": float(args.success_threshold_pct),
            "lookback_days_kline": int(args.lookback_days_kline),
            "sell_fee_rate": float(args.sell_fee_rate),
        },
        "coverage": {
            "selected_items": len(item_ids),
            "evaluated_points": evaluated_points,
            "signals_counted": sum(int(row.get("samples", 0)) for row in strategy_rows),
        },
        "strategy_win_rates": strategy_rows,
        "score_calibration": {
            "samples": len(scored_points),
            "pearson_score_vs_forward_max_return": score_corr,
            "buckets": score_buckets,
        },
    }

    logger.info("回测完成: selected_items={}, evaluated_points={}", len(item_ids), evaluated_points)
    logger.info("策略统计:")
    for row in strategy_rows:
        logger.info(
            "  {signal}: samples={samples}, win_rate={win_rate_pct}%, avg_max_ret={avg_max_return_pct}%",
            **row,
        )
    logger.info("评分校验: samples={}, corr={}", len(scored_points), score_corr)

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.report:
        path = Path(args.report).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
        logger.success("报告已写入 {}", path)


if __name__ == "__main__":
    main()

