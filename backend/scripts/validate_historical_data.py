#!/usr/bin/env python3
"""
Validate historical JSONL snapshots for completeness, format, and gaps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config.historical_config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OUTPUT_DIR,
    COLLECTION_INTERVAL_SECONDS,
    GAP_TOLERANCE_MULTIPLIER,
    GAP_FILL_MAX_AGE_HOURS,
    priority_to_group,
)


REQUIRED_FIELDS = ("platform", "item_name", "collected_at", "currency")


def setup_logger() -> None:
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


def iter_jsonl_files(path: Path) -> List[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.jsonl"))


def load_items(items_path: str) -> Dict[str, Dict[str, Any]]:
    with open(items_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    items = payload.get("items", payload if isinstance(payload, list) else [])
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name_en") or item.get("market_hash_name") or item.get("name")
        if name:
            mapping[name] = item
    return mapping


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def validate_record(record: Dict[str, Any]) -> List[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in record or record[field] in (None, ""):
            errors.append(f"missing:{field}")
    if parse_timestamp(record.get("collected_at")) is None:
        errors.append("invalid:collected_at")
    for price_key in ("lowest_price", "median_price", "highest_price"):
        if record.get(price_key) is not None and coerce_float(record.get(price_key)) is None:
            errors.append(f"invalid:{price_key}")
    if record.get("volume") is not None and coerce_float(record.get("volume")) is None:
        errors.append("invalid:volume")
    return errors


def detect_gaps(
    timestamps: List[datetime],
    expected_interval: int,
    tolerance_multiplier: float,
) -> List[Tuple[datetime, datetime, int]]:
    if len(timestamps) < 2:
        return []
    gaps: List[Tuple[datetime, datetime, int]] = []
    for previous, current in zip(timestamps, timestamps[1:]):
        delta = int((current - previous).total_seconds())
        if delta > int(expected_interval * tolerance_multiplier):
            gaps.append((previous, current, delta))
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate historical JSONL snapshots.")
    parser.add_argument("--input", default=DEFAULT_OUTPUT_DIR, help="JSONL file or directory.")
    parser.add_argument("--items", default=DEFAULT_ITEMS_PATH, help="Items JSON for completeness checks.")
    parser.add_argument("--report", default=None, help="Write report JSON to this path.")
    args = parser.parse_args()

    setup_logger()

    input_path = Path(args.input).expanduser().resolve()
    jsonl_files = iter_jsonl_files(input_path)
    if not jsonl_files:
        logger.error(f"No JSONL files found in {input_path}")
        return

    items_map = load_items(args.items)
    expected_items = set(items_map.keys())

    stats = {
        "total_records": 0,
        "success_records": 0,
        "failure_records": 0,
        "invalid_records": 0,
    }

    timestamps_by_item: Dict[str, List[datetime]] = {}
    items_with_data: set[str] = set()
    items_with_gaps: set[str] = set()
    gap_fill_candidates: set[str] = set()
    gap_details: List[Dict[str, Any]] = []

    for file_path in jsonl_files:
        with file_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    stats["invalid_records"] += 1
                    continue

                stats["total_records"] += 1
                errors = validate_record(record)
                if errors:
                    stats["invalid_records"] += 1

                success_flag = record.get("success")
                if success_flag is True:
                    stats["success_records"] += 1
                else:
                    stats["failure_records"] += 1

                item_name = record.get("item_name")
                if not item_name:
                    continue
                items_with_data.add(item_name)

                collected_at = parse_timestamp(record.get("collected_at"))
                if collected_at:
                    timestamps_by_item.setdefault(item_name, []).append(collected_at)

    now = datetime.now()
    for item_name, timestamps in timestamps_by_item.items():
        timestamps.sort()
        priority = items_map.get(item_name, {}).get("priority")
        group = priority_to_group(priority)
        expected_interval = COLLECTION_INTERVAL_SECONDS.get(group, COLLECTION_INTERVAL_SECONDS["medium"])
        gaps = detect_gaps(timestamps, expected_interval, GAP_TOLERANCE_MULTIPLIER)
        if gaps:
            items_with_gaps.add(item_name)
            for start, end, delta in gaps[:3]:
                gap_details.append(
                    {
                        "item_name": item_name,
                        "gap_start": start.isoformat(),
                        "gap_end": end.isoformat(),
                        "gap_seconds": delta,
                    }
                )
            latest_gap_end = gaps[-1][1]
            if now - latest_gap_end <= timedelta(hours=GAP_FILL_MAX_AGE_HOURS):
                gap_fill_candidates.add(item_name)

    missing_items = sorted(expected_items - items_with_data)
    success_rate = (stats["success_records"] / stats["total_records"] * 100) if stats["total_records"] else 0.0

    report = {
        "generated_at": now.isoformat(),
        "inputs": [str(path) for path in jsonl_files],
        "total_records": stats["total_records"],
        "success_records": stats["success_records"],
        "failure_records": stats["failure_records"],
        "invalid_records": stats["invalid_records"],
        "success_rate": round(success_rate, 2),
        "expected_items": len(expected_items),
        "items_with_data": len(items_with_data),
        "missing_items": missing_items[:50],
        "missing_item_count": len(missing_items),
        "items_with_gaps": len(items_with_gaps),
        "gap_examples": gap_details[:20],
        "gap_fill_candidates": sorted(gap_fill_candidates),
    }

    report_path: Path
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
    else:
        report_dir = Path(DEFAULT_OUTPUT_DIR) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"historical_quality_{now.strftime('%Y%m%d_%H%M%S')}.json"

    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    logger.info(f"Report saved: {report_path}")
    logger.info(f"Records: {stats['total_records']} (success {stats['success_records']})")
    if missing_items:
        logger.warning(f"Missing items: {len(missing_items)}")


if __name__ == "__main__":
    main()
