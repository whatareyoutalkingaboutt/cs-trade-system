-- TimescaleDB init script for CS item scraper

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

-- Base tables (PostgreSQL)
CREATE TABLE IF NOT EXISTS items (
  id BIGSERIAL PRIMARY KEY,
  market_hash_name VARCHAR(255) UNIQUE NOT NULL,
  name_cn VARCHAR(255),
  name_buff VARCHAR(255),

  type VARCHAR(50) NOT NULL,
  weapon_type VARCHAR(50),
  skin_name VARCHAR(100),
  quality VARCHAR(50),
  rarity VARCHAR(50),

  image_url VARCHAR(500),
  steam_url VARCHAR(500),
  buff_url VARCHAR(500),
  data_hash VARCHAR(32),

  is_active BOOLEAN DEFAULT TRUE,
  priority INT DEFAULT 5,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_item_name ON items(market_hash_name);
CREATE INDEX IF NOT EXISTS idx_item_name_trgm ON items USING gin (market_hash_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_item_name_cn_trgm ON items USING gin (name_cn gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_item_type ON items(type);
CREATE INDEX IF NOT EXISTS idx_item_active ON items(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_item_priority ON items(priority DESC) WHERE is_active = TRUE;

ALTER TABLE items ADD COLUMN IF NOT EXISTS data_hash VARCHAR(32);
ALTER TABLE items ADD COLUMN IF NOT EXISTS buff_goods_id BIGINT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS youpin_template_id BIGINT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS exterior VARCHAR(50);

CREATE OR REPLACE VIEW items_metadata AS
SELECT
  market_hash_name,
  buff_goods_id,
  youpin_template_id,
  type,
  quality,
  exterior
FROM items;

CREATE TABLE IF NOT EXISTS platform_config (
  id SERIAL PRIMARY KEY,
  platform VARCHAR(50) UNIQUE NOT NULL,

  buy_fee_rate NUMERIC(5, 4) NOT NULL,
  sell_fee_rate NUMERIC(5, 4) NOT NULL,

  api_endpoint VARCHAR(255),
  api_key_encrypted TEXT,

  rate_limit_per_minute INT DEFAULT 20,
  request_delay_min NUMERIC(4, 2) DEFAULT 2.0,
  request_delay_max NUMERIC(4, 2) DEFAULT 3.0,

  is_enabled BOOLEAN DEFAULT TRUE,
  last_sync_at TIMESTAMP,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(50) UNIQUE NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL,
  hashed_password TEXT NOT NULL,

  is_active BOOLEAN DEFAULT TRUE,
  is_superuser BOOLEAN DEFAULT FALSE,
  last_login_at TIMESTAMP,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS scraper_tasks (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  platform VARCHAR(50) NOT NULL,

  task_type VARCHAR(50) NOT NULL,
  schedule_type VARCHAR(50) NOT NULL,
  schedule_config JSONB,

  item_filter JSONB,

  priority INT DEFAULT 5,
  max_concurrency INT DEFAULT 10,
  timeout_seconds INT DEFAULT 300,
  max_retries INT DEFAULT 3,

  is_active BOOLEAN DEFAULT TRUE,
  is_running BOOLEAN DEFAULT FALSE,
  last_run_at TIMESTAMP,
  next_run_at TIMESTAMP,

  celery_task_id VARCHAR(255),

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_platform ON scraper_tasks(platform);
CREATE INDEX IF NOT EXISTS idx_task_active ON scraper_tasks(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_task_next_run ON scraper_tasks(next_run_at) WHERE is_active = TRUE;

DROP TRIGGER IF EXISTS set_updated_at_items ON items;
CREATE TRIGGER set_updated_at_items
BEFORE UPDATE ON items
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS set_updated_at_platform_config ON platform_config;
CREATE TRIGGER set_updated_at_platform_config
BEFORE UPDATE ON platform_config
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS set_updated_at_users ON users;
CREATE TRIGGER set_updated_at_users
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS set_updated_at_scraper_tasks ON scraper_tasks;
CREATE TRIGGER set_updated_at_scraper_tasks
BEFORE UPDATE ON scraper_tasks
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- TimescaleDB tables
CREATE TABLE IF NOT EXISTS price_history (
  time TIMESTAMPTZ NOT NULL,
  item_id BIGINT NOT NULL REFERENCES items(id),
  platform VARCHAR(50) NOT NULL,

  price NUMERIC(12, 2) NOT NULL,
  currency VARCHAR(10) NOT NULL,

  volume INT DEFAULT 0,
  sell_listings INT,
  buy_orders INT,

  data_source VARCHAR(50) DEFAULT 'scraper',
  is_estimated BOOLEAN DEFAULT FALSE,
  is_baseline BOOLEAN DEFAULT FALSE,
  quality_score INT DEFAULT 100,

  collected_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable(
  'price_history',
  'time',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);
SELECT set_chunk_time_interval('price_history', INTERVAL '1 day');

CREATE INDEX IF NOT EXISTS idx_price_item_platform_time
  ON price_history (item_id, platform, time DESC);
CREATE INDEX IF NOT EXISTS idx_price_data_source ON price_history (data_source);
CREATE INDEX IF NOT EXISTS idx_price_estimated
  ON price_history (is_estimated) WHERE is_estimated = TRUE;

ALTER TABLE price_history SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'item_id, platform',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('price_history', INTERVAL '7 days', if_not_exists => TRUE);
-- 使用 Timescale retention policy 触发 drop_chunks，自动清理 7 天前明细
SELECT add_retention_policy('price_history', INTERVAL '7 days', if_not_exists => TRUE);

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
WITH NO DATA;

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
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_price_history_1h_item_platform_bucket
  ON price_history_1h (item_id, platform, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_1d_item_platform_bucket
  ON price_history_1d (item_id, platform, bucket DESC);

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

CREATE OR REPLACE VIEW price_history_with_items AS
SELECT
  p.time,
  p.item_id,
  p.platform,
  p.price,
  p.currency,
  p.volume,
  p.sell_listings,
  p.buy_orders,
  p.data_source,
  p.is_estimated,
  p.is_baseline,
  p.quality_score,
  p.collected_at,
  i.market_hash_name,
  i.name_cn,
  i.rarity,
  i.type
FROM price_history p
JOIN items i ON i.id = p.item_id;

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
);

CREATE INDEX IF NOT EXISTS idx_alert_logs_event_time
  ON alert_logs (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_alert_logs_item
  ON alert_logs (item_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_alert_logs_trigger
  ON alert_logs (trigger_type, event_time DESC);

CREATE TABLE IF NOT EXISTS system_heartbeats (
  time TIMESTAMPTZ NOT NULL,
  component VARCHAR(50) NOT NULL,
  instance_id VARCHAR(100),
  status VARCHAR(20) NOT NULL,

  cpu_percent NUMERIC(5, 2),
  memory_percent NUMERIC(5, 2),
  active_tasks INT DEFAULT 0,

  metadata JSONB
);

SELECT create_hypertable('system_heartbeats', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_heartbeat_component
  ON system_heartbeats (component, time DESC);
CREATE INDEX IF NOT EXISTS idx_heartbeat_instance
  ON system_heartbeats (instance_id, time DESC);

SELECT add_retention_policy('system_heartbeats', INTERVAL '30 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS data_gap_logs (
  id BIGSERIAL PRIMARY KEY,
  item_id BIGINT NOT NULL REFERENCES items(id),
  platform VARCHAR(50) NOT NULL,

  gap_start TIMESTAMPTZ NOT NULL,
  gap_end TIMESTAMPTZ NOT NULL,
  gap_duration_minutes INT NOT NULL,
  severity VARCHAR(20) NOT NULL,

  fill_status VARCHAR(20) NOT NULL,
  fill_method VARCHAR(50),
  filled_points INT DEFAULT 0,

  gap_reason TEXT,
  notes TEXT,

  detected_at TIMESTAMPTZ DEFAULT NOW(),
  filled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gap_item_time
  ON data_gap_logs (item_id, gap_start DESC);
CREATE INDEX IF NOT EXISTS idx_gap_severity ON data_gap_logs (severity);
CREATE INDEX IF NOT EXISTS idx_gap_status ON data_gap_logs (fill_status);

CREATE TABLE IF NOT EXISTS task_executions (
  time TIMESTAMPTZ NOT NULL,
  task_id BIGINT NOT NULL REFERENCES scraper_tasks(id),
  platform VARCHAR(50) NOT NULL,

  status VARCHAR(20) NOT NULL,
  celery_task_id VARCHAR(255),

  items_total INT DEFAULT 0,
  items_processed INT DEFAULT 0,
  items_success INT DEFAULT 0,
  items_failed INT DEFAULT 0,
  success_rate NUMERIC(5, 2),

  duration_seconds INT,
  avg_response_time_ms INT,
  requests_per_second NUMERIC(6, 2),

  error_message TEXT,
  error_details JSONB,

  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

SELECT create_hypertable('task_executions', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_execution_task_time
  ON task_executions (task_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_execution_status
  ON task_executions (status, time DESC);

ALTER TABLE task_executions SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'task_id, platform'
);
SELECT add_compression_policy('task_executions', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('task_executions', INTERVAL '90 days', if_not_exists => TRUE);

INSERT INTO platform_config (platform, buy_fee_rate, sell_fee_rate) VALUES
  ('steam', 0.0000, 0.1500),
  ('buff', 0.0250, 0.0250),
  ('c5game', 0.0200, 0.0200)
ON CONFLICT (platform) DO NOTHING;
