#!/usr/bin/env python3
from __future__ import annotations

import argparse

from backend.scrapers.youpin_device_headers import (
    build_market_url,
    refresh_headers_to_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Youpin device headers via Playwright.")
    parser.add_argument("--template-id", default="34780")
    parser.add_argument("--game-id", default="730")
    parser.add_argument("--list-type", default="10")
    parser.add_argument("--url", default=None, help="Optional override URL.")
    parser.add_argument("--out", default="docs/youpin/youpin_headers.json")
    parser.add_argument("--timeout", type=int, default=20000)
    args = parser.parse_args()

    url = args.url or build_market_url(args.template_id, args.game_id, args.list_type)
    headers = refresh_headers_to_file(url, args.out, timeout_ms=args.timeout)
    print(f"Wrote {len(headers)} headers to {args.out}")


if __name__ == "__main__":
    main()
