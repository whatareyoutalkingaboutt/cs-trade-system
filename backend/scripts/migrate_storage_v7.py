#!/usr/bin/env python3
"""
Storage migration for Task 7.

Usage:
  ./venv/bin/python backend/scripts/migrate_storage_v7.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core.database import get_engine


MIGRATION_SQL: list[str] = [
    # items metadata compatibility
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS buff_goods_id BIGINT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS youpin_template_id BIGINT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS exterior VARCHAR(50)",
    """
    CREATE OR REPLACE VIEW items_metadata AS
    SELECT
      market_hash_name,
      buff_goods_id,
      youpin_template_id,
      type,
      quality,
      exterior
    FROM items
    """,
    # alert logs table + indexes
    """
    CREATE TABLE IF NOT EXISTS alert_logs (
      id BIGSERIAL PRIMARY KEY,
      event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      item_id BIGINT REFERENCES items(id),
      market_hash_name VARCHAR(255),
      buy_platform VARCHAR(50),
      sell_platform VARCHAR(50),
      trigger_type VARCHAR(100),
      severity VARCHAR(20) DEFAULT 'info',
      message TEXT,
      payload JSONB,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alert_logs_event_time ON alert_logs (event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_alert_logs_item ON alert_logs (item_id, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_alert_logs_trigger ON alert_logs (trigger_type, event_time DESC)",
    # timescale lifecycle
    "SELECT set_chunk_time_interval('price_history', INTERVAL '1 day')",
    "SELECT add_retention_policy('price_history', INTERVAL '7 days', if_not_exists => TRUE)",
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS price_history_1h
    WITH (timescaledb.continuous) AS
    SELECT
      time_bucket(INTERVAL '1 hour', time) AS bucket,
      item_id,
      platform,
      first(price, time) AS open,
      max(price) AS high,
      min(price) AS low,
      last(price, time) AS close,
      sum(volume) AS volume
    FROM price_history
    GROUP BY bucket, item_id, platform
    WITH NO DATA
    """,
    """
    CREATE MATERIALIZED VIEW IF NOT EXISTS price_history_1d
    WITH (timescaledb.continuous) AS
    SELECT
      time_bucket(INTERVAL '1 day', time) AS bucket,
      item_id,
      platform,
      first(price, time) AS open,
      max(price) AS high,
      min(price) AS low,
      last(price, time) AS close,
      sum(volume) AS volume
    FROM price_history
    GROUP BY bucket, item_id, platform
    WITH NO DATA
    """,
    "CREATE INDEX IF NOT EXISTS idx_price_history_1h_item_platform_bucket ON price_history_1h (item_id, platform, bucket DESC)",
    "CREATE INDEX IF NOT EXISTS idx_price_history_1d_item_platform_bucket ON price_history_1d (item_id, platform, bucket DESC)",
    """
    DO $$
    BEGIN
      PERFORM add_continuous_aggregate_policy(
        'price_history_1h',
        start_offset => INTERVAL '7 days',
        end_offset => INTERVAL '5 minutes',
        schedule_interval => INTERVAL '15 minutes'
      );
    EXCEPTION
      WHEN duplicate_object THEN NULL;
    END $$;
    """,
    """
    DO $$
    BEGIN
      PERFORM add_continuous_aggregate_policy(
        'price_history_1d',
        start_offset => INTERVAL '90 days',
        end_offset => INTERVAL '1 hour',
        schedule_interval => INTERVAL '1 hour'
      );
    EXCEPTION
      WHEN duplicate_object THEN NULL;
    END $$;
    """,
]


def main() -> None:
    with get_engine().begin() as connection:
        for idx, stmt in enumerate(MIGRATION_SQL, start=1):
            connection.execute(text(stmt))
            print(f"[{idx}/{len(MIGRATION_SQL)}] OK")

    with get_engine().begin() as connection:
        checks = {
            "alert_logs": "SELECT to_regclass('public.alert_logs')",
            "items_metadata": "SELECT to_regclass('public.items_metadata')",
            "price_history_1h": "SELECT to_regclass('public.price_history_1h')",
            "price_history_1d": "SELECT to_regclass('public.price_history_1d')",
        }
        for name, sql in checks.items():
            value = connection.execute(text(sql)).scalar()
            print(f"[check] {name}={value}")


if __name__ == "__main__":
    main()
