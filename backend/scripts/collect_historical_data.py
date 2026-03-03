#!/usr/bin/env python3
"""
Collect historical price snapshots from Steam and store them on disk.

This script accumulates history by repeatedly sampling realtime prices and
writing normalized JSONL records. It supports priority batching and resume
via a checkpoint file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config.historical_config import (
    DEFAULT_ITEMS_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PLATFORM,
    priority_to_group,
    iter_priority_groups,
)
from backend.scrapers.base_scraper import parse_price_string
from backend.scrapers.steam_scraper import SteamMarketScraper
from backend.scrapers.buff_scraper import BuffScraper
from backend.scrapers.steamdt_price_scraper import SteamDTPriceScraper


CHECKPOINT_NAME = "historical_checkpoint.json"


def setup_logger() -> None:
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


def load_items(items_path: str) -> List[Dict[str, Any]]:
    with open(items_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    items = payload.get("items", payload if isinstance(payload, list) else [])
    return [item for item in items if isinstance(item, dict)]


def resolve_item_name(item: Dict[str, Any]) -> Optional[str]:
    return item.get("name_en") or item.get("market_hash_name") or item.get("name")


def group_items(items: Iterable[Dict[str, Any]], allowed_groups: Set[str]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in iter_priority_groups()}
    for item in items:
        priority = item.get("priority")
        group = priority_to_group(priority)
        if group in allowed_groups:
            grouped[group].append(item)
    return grouped


def coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parsed = parse_price_string(value)
        if parsed is not None:
            return parsed
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def normalize_price_data(
    raw: Optional[Dict[str, Any]],
    item: Dict[str, Any],
    run_id: str,
    group: str,
    platform: str,
    data_source: str,
    error: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now_iso = datetime.now().isoformat()
    item_name = resolve_item_name(item) or "UNKNOWN_ITEM"
    timestamp = raw.get("timestamp") if raw else None
    currency = raw.get("currency") if raw else None

    lowest_price = coerce_float(raw.get("lowest_price")) if raw else None
    median_price = coerce_float(raw.get("median_price")) if raw else None
    highest_price = coerce_float(raw.get("highest_price")) if raw else None
    volume = coerce_int(raw.get("volume")) if raw else None

    success = raw is not None and (lowest_price is not None or median_price is not None)
    resolved_error = error or (None if success else "no_data")

    return {
        "run_id": run_id,
        "platform": platform,
        "data_source": data_source,
        "item_name": item_name,
        "item_name_cn": item.get("name"),
        "priority": item.get("priority"),
        "priority_group": group,
        "currency": currency or "CNY",
        "collected_at": timestamp or now_iso,
        "lowest_price": lowest_price,
        "median_price": median_price,
        "highest_price": highest_price,
        "volume": volume,
        "success": success,
        "error": resolved_error,
        **(extra_fields or {}),
    }


def load_checkpoint(checkpoint_path: Path) -> Optional[Dict[str, Any]]:
    if not checkpoint_path.exists():
        return None
    try:
        with checkpoint_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Checkpoint load failed: {exc}")
        return None


def save_checkpoint(checkpoint_path: Path, state: Dict[str, Any]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with checkpoint_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def write_record(output_path: Path, record: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_stats(stats: Dict[str, Dict[str, int]]) -> None:
    total = sum(group["total"] for group in stats.values())
    success = sum(group["success"] for group in stats.values())
    failed = total - success
    logger.info(f"Summary: {success}/{total} succeeded, {failed} failed")


def collect_for_group(
    scraper,
    items: List[Dict[str, Any]],
    group: str,
    run_id: str,
    platform: str,
    data_source: str,
    output_path: Path,
    checkpoint_path: Path,
    items_path: str,
    completed: Set[str],
    resume: bool,
    extra_delay: float,
    stats: Dict[str, Dict[str, int]],
    started_at: str,
) -> None:
    total = len(items)
    stats[group] = {"total": 0, "success": 0}

    if total == 0:
        return

    logger.info(f"Group {group}: {total} items")

    for index, item in enumerate(items, 1):
        item_name = resolve_item_name(item)
        if not item_name:
            logger.warning(f"Skipping item without name: {item}")
            continue

        if resume and item_name in completed:
            logger.info(f"[{index}/{total}] {item_name} (skipped)")
            continue

        logger.info(f"[{index}/{total}] {item_name}")
        stats[group]["total"] += 1

        raw = None
        error = None
        try:
            raw = scraper.get_price(item_name)
        except Exception as exc:
            error = f"scrape_error:{exc}"
            logger.error(f"Failed to fetch {item_name}: {exc}")

        raw_for_record = raw
        error_for_record = error
        extra_fields: Dict[str, Any] = {}

        if platform == "youpin":
            if raw:
                extra_fields["buff_price"] = raw.get("buff_price")
                for key in ("steam_price", "youpin_price", "youpin_volume"):
                    if raw.get(key) is not None:
                        extra_fields[key] = raw.get(key)

            if not raw:
                error_for_record = error_for_record or "no_data"
                extra_fields["is_gap"] = True
                raw_for_record = None
            else:
                youpin_price = raw.get("youpin_price")
                youpin_volume = raw.get("youpin_volume")
                if youpin_price is not None:
                    raw_for_record = {
                        "lowest_price": youpin_price,
                        "volume": youpin_volume,
                        "timestamp": raw.get("timestamp"),
                        "currency": raw.get("currency"),
                    }
                else:
                    error_for_record = error_for_record or "no_youpin_data"
                    extra_fields["is_gap"] = True
                    raw_for_record = None

        record = normalize_price_data(
            raw_for_record,
            item,
            run_id,
            group,
            platform,
            data_source,
            error=error_for_record,
            extra_fields=extra_fields,
        )
        write_record(output_path, record)

        if record["success"]:
            stats[group]["success"] += 1

        completed.add(item_name)
        save_checkpoint(
            checkpoint_path,
            {
                "run_id": run_id,
                "platform": platform,
                "output_path": str(output_path),
                "items_path": os.path.abspath(items_path),
                "completed_items": sorted(completed),
                "started_at": started_at,
            },
        )

        if extra_delay > 0:
            time.sleep(extra_delay)


def parse_priority_arg(value: str) -> Set[str]:
    allowed = {"high", "medium", "low"}
    if value.lower() == "all":
        return allowed
    selected = {v.strip().lower() for v in value.split(",") if v.strip()}
    invalid = selected - allowed
    if invalid:
        raise ValueError(f"Invalid priority groups: {', '.join(sorted(invalid))}")
    return selected


def build_scraper(platform: str):
    if platform == "steam":
        return SteamMarketScraper
    if platform == "buff":
        return BuffScraper
    if platform == "youpin":
        return SteamDTPriceScraper
    raise ValueError(f"Unsupported platform: {platform}")


def run_platform(
    platform: str,
    items_path: str,
    output_dir: Path,
    allowed_groups: Set[str],
    run_id: str,
    resume: bool,
    no_proxy: bool,
    extra_delay: float,
) -> None:
    items = load_items(items_path)
    grouped_items = group_items(items, allowed_groups)

    output_path = output_dir / platform / f"{platform}_prices_{run_id}.jsonl"
    checkpoint_path = output_dir / platform / CHECKPOINT_NAME
    completed: Set[str] = set()

    if resume:
        checkpoint = load_checkpoint(checkpoint_path)
        if checkpoint and checkpoint.get("platform") == platform:
            checkpoint_items = checkpoint.get("items_path")
            if checkpoint_items and os.path.abspath(checkpoint_items) != items_path:
                logger.warning("Checkpoint items path does not match; starting a new run")
            else:
                output_path = Path(checkpoint.get("output_path", output_path))
                completed = set(checkpoint.get("completed_items", []))
                logger.info(f"Resuming run {checkpoint.get('run_id', run_id)}: {len(completed)} items completed")
        else:
            logger.info("No valid checkpoint found; starting a new run")

    logger.info(f"[{platform}] Output: {output_path}")
    logger.info(f"[{platform}] Priority groups: {', '.join(sorted(allowed_groups))}")

    stats: Dict[str, Dict[str, int]] = {}
    started_at = datetime.now().isoformat()

    scraper_class = build_scraper(platform)
    if platform == "steam":
        data_source = "steam_market"
    elif platform == "youpin":
        data_source = "steamdt"
    else:
        data_source = "direct_scraper"

    if platform == "steam":
        scraper = scraper_class(use_proxy=not no_proxy)
    else:
        scraper = scraper_class()

    with scraper as client:
        for group in iter_priority_groups():
            if group not in allowed_groups:
                continue
            collect_for_group(
                scraper=client,
                items=grouped_items.get(group, []),
                group=group,
                run_id=run_id,
                platform=platform,
                data_source=data_source,
                output_path=output_path,
                checkpoint_path=checkpoint_path,
                items_path=items_path,
                completed=completed,
                resume=resume,
                extra_delay=extra_delay,
                stats=stats,
                started_at=started_at,
            )

    summarize_stats({k: v for k, v in stats.items() if k in {"high", "medium", "low"}})


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect historical price snapshots from Steam.")
    parser.add_argument("--items", default=DEFAULT_ITEMS_PATH, help="Path to items JSON file.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory for JSONL files.")
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        choices=["steam", "buff", "youpin", "all"],
        help="Target platform.",
    )
    parser.add_argument("--priority", default="all", help="Priority groups: high,medium,low,all.")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint if present.")
    parser.add_argument("--run-id", default=None, help="Optional run identifier.")
    parser.add_argument("--no-proxy", action="store_true", help="Disable proxy usage for Steam.")
    parser.add_argument("--extra-delay", type=float, default=0.0, help="Extra delay between items (seconds).")
    args = parser.parse_args()

    setup_logger()
    load_dotenv()

    items_path = os.path.abspath(args.items)
    output_dir = Path(args.output_dir).expanduser().resolve()
    platform = args.platform
    allowed_groups = parse_priority_arg(args.priority)

    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"Run ID: {run_id}")

    platforms = ["steam", "buff", "youpin"] if platform == "all" else [platform]
    for target in platforms:
        run_platform(
            platform=target,
            items_path=items_path,
            output_dir=output_dir,
            allowed_groups=allowed_groups,
            run_id=run_id,
            resume=args.resume,
            no_proxy=args.no_proxy,
            extra_delay=args.extra_delay,
        )


if __name__ == "__main__":
    main()
