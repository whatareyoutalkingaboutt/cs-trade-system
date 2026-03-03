#!/usr/bin/env python3
"""
Buff goods snapshot CLI (direct API).

Example:
    PYTHONPATH=. python3 -m cli.buff_direct_scraper --goods-id 33822 --summary \
        --out /Users/gaolaozhuanghouxianzi/cs-item-scraper/tests/history/buff_test_33822.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from backend.scrapers.buff_scraper import BuffScraper


def _parse_goods_ids(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _format_value(value) -> str:
    return "NA" if value is None else str(value)


def _format_price(value) -> str:
    if value is None:
        return "NA"
    return f"{value:.2f}"


def _print_summary(payload: Dict[str, object], multi: bool) -> None:
    print(f"商品ID={payload.get('goods_id')}")
    print(f"名称={_format_value(payload.get('name'))}")
    print(f"磨损={_format_value(payload.get('wear'))}")
    print(f"在售数量={_format_value(payload.get('sell_count'))}")
    print(f"求购数量={_format_value(payload.get('buy_count'))}")
    print(f"在售最低价={_format_price(payload.get('sell_min_price'))}")
    print(f"最高求购价={_format_price(payload.get('buy_max_price'))}")
    if multi:
        print("---")


def main() -> None:
    parser = argparse.ArgumentParser(description="Buff goods snapshot (direct).")
    parser.add_argument("--goods-id", required=True, help="Goods ID, comma-separated supported.")
    parser.add_argument("--page-num", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--summary", action="store_true", help="Print summary to stdout.")
    parser.add_argument("--pretty", action="store_true", help="Pretty JSON output.")
    parser.add_argument("--out", help="Write JSON output to file.")
    args = parser.parse_args()

    goods_ids = _parse_goods_ids(args.goods_id)
    results: Dict[str, object] = {"results": {}}

    with BuffScraper() as scraper:
        for goods_id in goods_ids:
            payload = scraper.get_goods_snapshot(
                goods_id=goods_id,
                page_num=args.page_num,
                page_size=args.page_size,
            )
            results["results"][str(goods_id)] = payload
            if args.summary:
                _print_summary(payload, multi=len(goods_ids) > 1)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.pretty:
            out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            out_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
