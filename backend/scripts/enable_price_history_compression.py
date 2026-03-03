#!/usr/bin/env python3
"""
Enable TimescaleDB compression policy for price_history.

Usage:
  python backend/scripts/enable_price_history_compression.py
"""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.database import get_engine


def main() -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE price_history SET (
                  timescaledb.compress,
                  timescaledb.compress_segmentby = 'item_id, platform',
                  timescaledb.compress_orderby = 'time DESC'
                );
                """
            )
        )
        connection.execute(
            text(
                """
                SELECT add_compression_policy(
                  'price_history',
                  INTERVAL '7 days',
                  if_not_exists => TRUE
                );
                """
            )
        )


if __name__ == "__main__":
    main()
