#!/usr/bin/env python3
"""Import historical JSONL data into the database.

This script reads JSONL files produced by collect_historical_data.py and writes
price snapshots into price_history. It will also seed items from the test items
file if they are missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.database import get_sessionmaker
from backend.models import Item
from backend.services.price_service import PriceRecord, write_prices_batch


def load_items(items_path: Path) -> list[dict[str, Any]]:
    with items_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    items = payload.get("items", payload if isinstance(payload, list) else [])
    return [item for item in items if isinstance(item, dict)]


def seed_items(items_path: Path) -> int:
    items = load_items(items_path)
    session = get_sessionmaker()()
    created = 0
    try:
        for item in items:
            market_name = item.get("name_en") or item.get("market_hash_name") or item.get("name")
            if not market_name:
                continue
            exists = (
                session.query(Item)
                .filter(Item.market_hash_name == market_name)
                .first()
            )
            if exists:
                continue
            row = Item(
                market_hash_name=market_name,
                name_cn=item.get("name"),
                type=item.get("type") or "unknown",
                rarity=item.get("rarity"),
                priority=item.get("priority") or 5,
                is_active=True,
            )
            session.add(row)
            created += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return created


def iter_jsonl_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("*.jsonl"))
    return files


def build_records(lines: Iterable[str], platform_filter: str | None) -> list[PriceRecord]:
    records: list[PriceRecord] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not record.get("success"):
            continue
        platform = record.get("platform")
        if platform_filter and platform != platform_filter:
            continue
        price = record.get("lowest_price")
        if price is None:
            continue
        records.append(
            PriceRecord(
                item_name=record.get("item_name"),
                platform=platform or "unknown",
                price=float(price),
                currency=record.get("currency") or "CNY",
                volume=record.get("volume"),
                time=record.get("collected_at"),
                data_source="historical_import",
                is_estimated=record.get("is_estimated"),
            )
        )
    return records


def import_jsonl(path: Path, platform_filter: str | None, batch_size: int) -> int:
    total = 0
    with path.open("r", encoding="utf-8") as handle:
        buffer: list[str] = []
        for line in handle:
            buffer.append(line)
            if len(buffer) >= batch_size:
                records = build_records(buffer, platform_filter)
                if records:
                    total += write_prices_batch(records)
                buffer = []
        if buffer:
            records = build_records(buffer, platform_filter)
            if records:
                total += write_prices_batch(records)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical JSONL price data into DB")
    parser.add_argument("--items", default="data/test_items.json", help="Items JSON to seed")
    parser.add_argument("--input", default="data/historical/youpin", help="JSONL file or directory")
    parser.add_argument("--platform", default=None, help="Optional platform filter")
    parser.add_argument("--batch-size", type=int, default=200, help="Batch size for inserts")
    args = parser.parse_args()

    load_dotenv()
    logger.remove()
    logger.add(lambda msg: print(msg, end=""))

    items_path = Path(args.items).resolve()
    input_path = Path(args.input).resolve()

    created = seed_items(items_path)
    logger.info(f"Seeded items: {created}")

    files = iter_jsonl_files(input_path)
    if not files:
        logger.warning(f"No JSONL files found under {input_path}")
        return

    total_inserted = 0
    for file_path in files:
        inserted = import_jsonl(file_path, args.platform, args.batch_size)
        logger.info(f"Imported {inserted} rows from {file_path.name}")
        total_inserted += inserted

    logger.success(f"Total inserted: {total_inserted}")


if __name__ == "__main__":
    main()
