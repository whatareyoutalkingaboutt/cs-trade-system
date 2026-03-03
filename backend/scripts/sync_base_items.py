#!/usr/bin/env python3
"""
Sync SteamDT base items into items table.

Usage:
  python backend/scripts/sync_base_items.py
"""

from __future__ import annotations

import os
import sys

from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.services.base_sync_service import sync_base_items


def main() -> None:
    result = sync_base_items()
    logger.info("Sync complete: {}", result)


if __name__ == "__main__":
    main()
