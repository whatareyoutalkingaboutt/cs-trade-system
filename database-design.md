# CS 饰品数据采集系统 - 数据库设计与数据连续性保障方案

**版本**: v4.0
**日期**: 2025-12-13
**新增**: 数据连续性保障方案（历史数据 vs 实时数据 + 缺口补齐）

---

## 目录

1. [数据连续性核心问题](#1-数据连续性核心问题)
2. [数据库技术选型](#2-数据库技术选型)
3. [数据库架构设计](#3-数据库架构设计)
4. [核心表设计](#4-核心表设计)
5. [DragonflyDB 缓存设计](#5-dragonflydb-缓存设计)
6. [数据连续性保障方案](#6-数据连续性保障方案)
7. [数据保留与归档策略](#7-数据保留与归档策略)
8. [数据库部署配置](#8-数据库部署配置)
9. [数据库性能优化](#9-数据库性能优化)
10. [监控与维护](#10-监控与维护)

---

## 1. 数据连续性核心问题

### 1.1 数据类型划分 ⭐ (已更新)

| 数据类型 | 定义 | 获取方式 | 是否可获取 | 存储位置 |
|---------|------|---------|-----------|---------|
| **历史数据** | 系统启动前的价格数据 | 首次启动时通过第三方历史API导入 | ✅ **可以获取** (通过Pricempire等第三方API) | TimescaleDB |
| **实时数据** | 系统运行期间持续采集的数据 | 定时任务持续爬取 (5-120分钟) | ✅ **可以获取** (通过Steam/Buff官方API) | TimescaleDB |
| **缺口数据** | 系统中断期间缺失的数据 | 系统重启后回溯补齐 | ⚠️ **部分可补齐** (取决于中断时长) | TimescaleDB (标记) |

---

### 1.2 历史数据获取方案 ⭐ (新增)

经过调研，发现**可以通过第三方API获取历史价格数据**，解决了之前无法获取历史数据的问题。

#### 1.2.1 可用的历史数据API

| API服务商 | 历史数据范围 | 支持市场 | 数据粒度 | 免费额度 | 费用 |
|----------|------------|---------|---------|---------|------|
| **[Pricempire API](https://pricempire.com/api)** | 5年（2020-2025） | Steam、Buff等61个市场 | 小时级/日级 | 100次/天 | $29/月 (10,000次) |
| **[CSGOSKINS.GG](https://csgoskins.gg/api)** | 不限时间 | 30个CS2市场 | 5分钟级 | - | 联系获取定价 |
| **[SteamWebAPI](https://www.steamwebapi.com/)** | 不限时间 | Steam Market | 可定制 | - | 付费 |
| **[SteamAuth](https://steamauth.app/cs2-api)** | 不限时间 | Steam Market | 实时 | - | 付费 |

#### 1.2.2 推荐方案：Pricempire API

**优势：**
- ✅ 支持5年历史数据（从2020年至今）
- ✅ 同时支持Steam和Buff163价格
- ✅ 提供多种时间粒度：小时级（最近7天）、日级（7天以上）
- ✅ 提供7/30/60/90天的聚合统计（均价、中位数）
- ✅ 有免费额度：100次/天（足够用于首次导入）
- ✅ 付费计划合理：$29/月可获得10,000次请求

**数据格式示例：**
```json
{
  "item_name": "AK-47 | Redline (Field-Tested)",
  "steam": {
    "current_price": 35.50,
    "7d_avg": 35.20,
    "7d_median": 35.00,
    "30d_avg": 36.10,
    "price_history": [
      {"timestamp": "2025-11-15T00:00:00Z", "price": 35.50, "volume": 120},
      {"timestamp": "2025-11-16T00:00:00Z", "price": 36.00, "volume": 135},
      ...
    ]
  },
  "buff": {
    "current_price": 33.80,
    "7d_avg": 33.50,
    "30d_avg": 34.20,
    "price_history": [...]
  }
}
```

#### 1.2.3 历史数据导入策略

**首次启动流程：**
```
┌───────────────────────────────────────────────────────────┐
│ 首次启动检测 → 检查 price_history 表是否有数据             │
├───────────────────────────────────────────────────────────┤
│                                                           │
│ [无历史数据] → 调用 Pricempire API                         │
│       │                                                    │
│       ▼                                                    │
│ 获取所有活跃饰品列表 (items 表, is_active=TRUE)            │
│       │                                                    │
│       ▼                                                    │
│ 按优先级分批导入 (高优先级优先):                            │
│   • 优先级 8-10: 导入过去30天数据 (每小时粒度)              │
│   • 优先级 5-7:  导入过去30天数据 (每日粒度)                │
│   • 优先级 1-4:  导入过去7天数据 (每日粒度)                 │
│       │                                                    │
│       ▼                                                    │
│ 每个饰品获取:                                              │
│   • Steam 历史价格                                         │
│   • Buff 历史价格                                          │
│   • 限流: 每次请求间隔1秒                                   │
│       │                                                    │
│       ▼                                                    │
│ 数据清洗和标准化:                                          │
│   • 货币统一为 CNY                                         │
│   • 时间戳转换为 UTC                                        │
│   • 过滤异常值                                             │
│       │                                                    │
│       ▼                                                    │
│ 批量写入 TimescaleDB:                                      │
│   • data_source = 'historical_import'                     │
│   • quality_score = 95                                    │
│   • is_baseline = FALSE                                   │
│       │                                                    │
│       ▼                                                    │
│ 导入完成 → 切换到实时采集模式                              │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

**估算导入成本：**
```
假设有 500 个饰品需要导入历史数据

高优先级 (100个): 100 * 2(平台) = 200次请求
中优先级 (200个): 200 * 2(平台) = 400次请求
低优先级 (200个): 200 * 2(平台) = 400次请求

总计: 1000次请求

使用免费额度 (100次/天): 需要10天完成导入
付费 $29/月 (10,000次): 可立即完成导入,还剩余9,000次用于后续查询
```

---

### 1.3 数据缺口产生的原因

```
时间线示例 (已更新):
┌──────────────────────────────────────────────────────────────────────┐
│  历史数据     │    实时数据     │   缺口   │    实时数据恢复          │
│  (可导入)     │   (正常采集)    │  (丢失)  │   (补齐后继续)           │
├──────────────────────────────────────────────────────────────────────┤
│               │                 │          │                          │
│  2024-01-01   │  2025-12-01     │ 12-10    │  2025-12-11              │
│  至           │  系统启动       │ 10:00    │  系统重启                │
│  2025-11-30   │  开始采集       │ 系统中断 │  检测缺口并补齐          │
│  (通过API导入) │                 │ (2小时)  │                          │
└──────────────────────────────────────────────────────────────────────┘

数据获取方式:
1. 历史数据 (2024-01-01 ~ 2025-11-30):
   ✅ 可以通过 Pricempire API 导入
   ✅ 最长支持5年历史数据
   ✅ 导入后标记为 data_source='historical_import'

2. 实时数据 (2025-12-01 ~ 12-10 10:00):
   ✅ 通过定时爬虫持续采集
   ✅ 标记为 data_source='scraper'

3. 缺口数据 (12-10 10:00 ~ 12-10 12:00):
   ⚠️ 系统中断期间的数据 (开发、断电、崩溃等)
   - 短期缺口 (< 1小时): 可通过插值补齐
   - 中期缺口 (1-24小时): 可通过估算补齐 (标记)
   - 长期缺口 (> 24小时): 永久丢失,仅记录
```

---

### 1.4 行业现状与数据源对比 ⭐ (已更新)

#### 1.4.1 官方API限制

**Steam Market API**:
- ❌ 不提供历史价格查询接口
- ✅ 只能查询当前价格 (`/market/priceoverview/`)
- ⚠️ 社区市场有价格历史图表,但无公开API

**Buff (SteamDT) API**:
- ❌ 不提供历史数据API
- ✅ 只能查询当前价格
- ⚠️ 网站有价格历史图表,但需要逆向分析 (违反ToS)

#### 1.4.2 第三方历史API (推荐) ⭐

**Pricempire API**:
- ✅ 提供5年历史数据 (2020-2025)
- ✅ 支持61个市场（包括Steam和Buff）
- ✅ 数据质量高（直接从各平台采集）
- ✅ 更新频率快（1-2分钟）

**CSGOSKINS.GG API**:
- ✅ 提供不限时间的历史数据
- ✅ 支持30个CS2市场
- ✅ 更新频率：每5分钟

**SteamWebAPI**:
- ✅ 专门的历史API端点：`/api/history?id=ITEM_ID&key=YOUR_KEY`
- ✅ 提供详细的价格历史
- ✅ 适合专业用户

#### 1.4.3 最终数据获取策略 ⭐

**推荐组合方案：**

| 数据类型 | 数据源 | 用途 | 成本 |
|---------|-------|------|------|
| **历史数据** | Pricempire API | 首次启动时导入过去30-90天数据 | $29/月或免费额度 |
| **实时数据** | Steam + SteamDT | 持续采集当前价格 | 免费（限流） |
| **备用数据源** | Pricempire API | 当官方API失败时作为备用 | 使用剩余付费额度 |
| **聚合统计** | Pricempire API | 获取7/30/60/90天均价和趋势 | 包含在月度费用中 |

**结论 (已更新):**
- ✅ 历史数据**可以通过第三方API获取**（Pricempire、CSGOSKINS.GG等）
- ✅ 实时数据通过Steam/Buff官方API持续采集
- ✅ 第三方API可作为备用数据源，提高系统可靠性
- ✅ 建议使用混合策略：历史数据导入 + 实时爬虫采集

---

## 2. 数据库技术选型

### 2.1 技术选型策略

| 数据类型 | 数据库选择 | 选择理由 | 使用场景 |
|---------|-----------|---------|---------|
| **基础主数据** | PostgreSQL | • 事务性强，数据一致性高<br>• 支持复杂关系查询<br>• 成熟稳定，运维简单 | • 饰品基本信息<br>• 用户数据<br>• 系统配置<br>• 爬虫配置<br>• 任务定义 |
| **时序价格数据** | TimescaleDB | • 基于 PostgreSQL 的时序数据库<br>• 自动分区管理<br>• 高效的时序查询<br>• 数据压缩率高 (90%+) | • 价格历史记录<br>• 采集日志<br>• 任务执行历史<br>• 监控数据<br>• **心跳记录**<br>• **缺口日志** |
| **缓存数据** | DragonflyDB | • Redis 兼容协议 (100%兼容)<br>• 多线程架构，性能 > Redis<br>• 支持持久化<br>• 内存占用更少 | • 热点数据缓存<br>• 任务队列<br>• 会话存储<br>• 限流计数器<br>• **心跳时间戳**<br>• **HA主备锁** |

---

### 2.2 DragonflyDB vs Redis 对比 ⭐

| 维度 | DragonflyDB | Redis | 对比结果 |
|------|------------|-------|---------|
| **性能** | 多线程架构，25x 吞吐量 | 单线程 | ✅ Dragonfly 更快 |
| **内存占用** | 更高效的数据结构 | 较高 | ✅ Dragonfly 省内存 30% |
| **兼容性** | 100% Redis 协议兼容 | 原生 | ✅ 无缝替换 |
| **持久化** | 快照 + AOF | 快照 + AOF | 相同 |
| **部署** | Docker 一键启动 | Docker 一键启动 | 相同 |
| **多线程** | ✅ 原生支持 | ❌ 单线程 | ✅ Dragonfly 优势 |
| **高可用支持** | ✅ 原生分布式锁 | ⚠️ 需要额外配置 | ✅ Dragonfly 更简单 |

---

## 3. 数据库架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                 应用层 (Backend)                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  FastAPI + Celery                            │   │
│  │  SQLAlchemy ORM                              │   │
│  │  HA Manager (主备切换)                        │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                        │
        ┌───────────────┴───────────────┬──────────────────┐
        │                               │                  │
        ▼                               ▼                  ▼
┌──────────────────┐          ┌──────────────────┐  ┌─────────────┐
│   PostgreSQL     │          │   TimescaleDB    │  │ DragonflyDB │
│  (基础数据库)     │◄─────────┤  (时序数据库)     │  │  (缓存+HA)  │
├──────────────────┤          ├──────────────────┤  ├─────────────┤
│ • items          │          │ • price_history  │  │ • 价格缓存   │
│ • users          │          │ • scraper_logs   │  │ • 任务队列   │
│ • categories     │          │ • task_executions│  │ • 会话存储   │
│ • platform_config│          │ • system_heartbeat│ │ • 心跳时间戳 │
│ • scraper_tasks  │          │ • data_gap_logs  │  │ • HA主备锁   │
│ • alert_rules    │          │ • anomaly_logs   │  │ • 限流计数   │
└──────────────────┘          └──────────────────┘  └─────────────┘
```

---

## 4. 核心表设计

### 4.1 PostgreSQL 表（基础数据）

#### 4.1.1 饰品信息表 (items)
```sql
CREATE TABLE items (
  id BIGSERIAL PRIMARY KEY,
  market_hash_name VARCHAR(255) UNIQUE NOT NULL,  -- Steam标准名称（唯一键）
  name_cn VARCHAR(255),                           -- 中文名（可选）
  name_buff VARCHAR(255),                         -- Buff平台名称

  -- 分类信息
  type VARCHAR(50) NOT NULL,                      -- Weapon/Knife/Gloves/Sticker/Case
  weapon_type VARCHAR(50),                        -- AK-47/AWP/M4A4（武器类型）
  skin_name VARCHAR(100),                         -- 皮肤名称（如 Redline, 龙王）
  quality VARCHAR(50),                            -- Field-Tested/Minimal Wear等
  rarity VARCHAR(50),                             -- Classified/Covert/Contraband

  -- 外部资源
  image_url VARCHAR(500),
  steam_url VARCHAR(500),
  buff_url VARCHAR(500),

  -- 状态控制
  is_active BOOLEAN DEFAULT TRUE,                 -- 是否继续采集
  priority INT DEFAULT 5,                         -- 采集优先级（1-10，10最高）

  -- 元数据
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_item_name ON items(market_hash_name);
CREATE INDEX idx_item_type ON items(type);
CREATE INDEX idx_item_active ON items(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_item_priority ON items(priority DESC) WHERE is_active = TRUE;
```

---

#### 4.1.2 平台配置表 (platform_config)
```sql
CREATE TABLE platform_config (
  id SERIAL PRIMARY KEY,
  platform VARCHAR(50) UNIQUE NOT NULL,          -- steam / buff / c5game

  -- 费率配置
  buy_fee_rate NUMERIC(5, 4) NOT NULL,           -- 买入手续费率（如 0.0250 = 2.5%）
  sell_fee_rate NUMERIC(5, 4) NOT NULL,          -- 卖出手续费率

  -- API配置
  api_endpoint VARCHAR(255),
  api_key_encrypted TEXT,                        -- 加密存储

  -- 限流配置
  rate_limit_per_minute INT DEFAULT 20,
  request_delay_min NUMERIC(4, 2) DEFAULT 2.0,   -- 最小间隔（秒）
  request_delay_max NUMERIC(4, 2) DEFAULT 3.0,

  -- 状态
  is_enabled BOOLEAN DEFAULT TRUE,
  last_sync_at TIMESTAMP,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 初始化数据
INSERT INTO platform_config (platform, buy_fee_rate, sell_fee_rate) VALUES
('steam', 0.0000, 0.1500),  -- Steam：买0%，卖15%
('buff', 0.0250, 0.0250),   -- Buff：买卖均2.5%
('c5game', 0.0200, 0.0200); -- C5Game：买卖均2%
```

---

#### 4.1.3 爬虫任务表 (scraper_tasks)
```sql
CREATE TABLE scraper_tasks (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,                     -- 任务名称
  platform VARCHAR(50) NOT NULL,                  -- 平台（steam/buff/c5game）

  -- 任务配置
  task_type VARCHAR(50) NOT NULL,                 -- price_update/full_sync/item_discover
  schedule_type VARCHAR(50) NOT NULL,             -- interval/cron/manual
  schedule_config JSONB,                          -- 调度配置

  -- 采集范围
  item_filter JSONB,                              -- 饰品筛选条件

  -- 执行参数
  priority INT DEFAULT 5,                         -- 任务优先级（1-10）
  max_concurrency INT DEFAULT 10,                 -- 最大并发数
  timeout_seconds INT DEFAULT 300,                -- 超时时间
  max_retries INT DEFAULT 3,                      -- 最大重试次数

  -- 状态
  is_active BOOLEAN DEFAULT TRUE,                 -- 是否启用
  is_running BOOLEAN DEFAULT FALSE,               -- 是否正在运行
  last_run_at TIMESTAMP,                          -- 上次执行时间
  next_run_at TIMESTAMP,                          -- 下次执行时间

  -- Celery 任务 ID
  celery_task_id VARCHAR(255),                    -- 当前运行的 Celery 任务 ID

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_task_platform ON scraper_tasks(platform);
CREATE INDEX idx_task_active ON scraper_tasks(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_task_next_run ON scraper_tasks(next_run_at) WHERE is_active = TRUE;
```

---

### 4.2 TimescaleDB 表（时序数据）

#### 4.2.1 价格历史表 (price_history) ⭐

```sql
CREATE TABLE price_history (
  time TIMESTAMPTZ NOT NULL,                     -- 时序主键
  item_id BIGINT NOT NULL REFERENCES items(id),
  platform VARCHAR(50) NOT NULL,                 -- steam / buff

  -- 价格信息
  price NUMERIC(12, 2) NOT NULL,
  currency VARCHAR(10) NOT NULL,                 -- USD / CNY

  -- 市场信息
  volume INT DEFAULT 0,                          -- 24h交易量
  sell_listings INT,                             -- 在售数量
  buy_orders INT,                                -- 求购订单数

  -- 数据质量标记 (新增) ⭐
  data_source VARCHAR(50) DEFAULT 'scraper',     -- scraper/interpolated/estimated/manual_import
  is_estimated BOOLEAN DEFAULT FALSE,            -- 是否为估算数据
  is_baseline BOOLEAN DEFAULT FALSE,             -- 是否为基准数据(首次启动)
  quality_score INT DEFAULT 100,                 -- 数据质量分数 (0-100)

  -- 元数据
  collected_at TIMESTAMPTZ DEFAULT NOW()
);

-- 转换为 TimescaleDB Hypertable（自动时序分区）
SELECT create_hypertable('price_history', 'time');

-- 创建复合索引
CREATE INDEX idx_price_item_platform_time ON price_history (item_id, platform, time DESC);
CREATE INDEX idx_price_data_source ON price_history (data_source);
CREATE INDEX idx_price_estimated ON price_history (is_estimated) WHERE is_estimated = TRUE;

-- 设置数据压缩策略（7天后自动压缩，节省90%空间）
ALTER TABLE price_history SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'item_id, platform',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('price_history', INTERVAL '7 days');
```

**数据来源类型说明** ⭐ (已更新):
- `scraper`: 实时爬取的真实数据 (质量分数: 100)
- `historical_import`: 通过第三方API导入的历史数据 (质量分数: 95) ⭐ **新增**
- `interpolated`: 线性插值补齐的数据 (质量分数: 80)
- `estimated`: 估算补齐的数据 (质量分数: 60)
- `manual_import`: 手动导入的数据 (质量分数: 90)
- `third_party_realtime`: 第三方实时数据源作为备用 (质量分数: 95)

---

#### 4.2.2 系统心跳表 (system_heartbeats) ⭐ 新增

```sql
CREATE TABLE system_heartbeats (
  time TIMESTAMPTZ NOT NULL,
  component VARCHAR(50) NOT NULL,                -- scraper/api/celery/instance-A/instance-B
  instance_id VARCHAR(100),                      -- 实例ID (用于HA)
  status VARCHAR(20) NOT NULL,                   -- active/stopped/degraded

  -- 健康状态
  cpu_percent NUMERIC(5, 2),                     -- CPU使用率
  memory_percent NUMERIC(5, 2),                  -- 内存使用率
  active_tasks INT DEFAULT 0,                    -- 当前活跃任务数

  metadata JSONB                                 -- 其他元数据
);

-- 转换为 Hypertable
SELECT create_hypertable('system_heartbeats', 'time');

-- 索引
CREATE INDEX idx_heartbeat_component ON system_heartbeats (component, time DESC);
CREATE INDEX idx_heartbeat_instance ON system_heartbeats (instance_id, time DESC);

-- 保留策略: 30天后自动删除
SELECT add_retention_policy('system_heartbeats', INTERVAL '30 days');

-- 查询最新心跳
SELECT DISTINCT ON (component) *
FROM system_heartbeats
ORDER BY component, time DESC;
```

---

#### 4.2.3 数据缺口日志表 (data_gap_logs) ⭐ 新增

```sql
CREATE TABLE data_gap_logs (
  id BIGSERIAL PRIMARY KEY,
  item_id BIGINT NOT NULL REFERENCES items(id),
  platform VARCHAR(50) NOT NULL,

  -- 缺口时间范围
  gap_start TIMESTAMPTZ NOT NULL,
  gap_end TIMESTAMPTZ NOT NULL,
  gap_duration_minutes INT NOT NULL,
  severity VARCHAR(20) NOT NULL,                 -- short/medium/long

  -- 补齐状态
  fill_status VARCHAR(20) NOT NULL,              -- unfilled/filled/partial
  fill_method VARCHAR(50),                       -- interpolated/estimated/none
  filled_points INT DEFAULT 0,                   -- 补齐的数据点数量

  -- 原因和备注
  gap_reason TEXT,                               -- system_restart/crash/manual_stop
  notes TEXT,

  -- 时间戳
  detected_at TIMESTAMPTZ DEFAULT NOW(),
  filled_at TIMESTAMPTZ
);

-- 索引
CREATE INDEX idx_gap_item_time ON data_gap_logs(item_id, gap_start DESC);
CREATE INDEX idx_gap_severity ON data_gap_logs(severity);
CREATE INDEX idx_gap_status ON data_gap_logs(fill_status);

-- 查询未补齐的严重缺口
SELECT item_id, gap_start, gap_end, gap_duration_minutes, severity
FROM data_gap_logs
WHERE fill_status = 'unfilled'
  AND severity IN ('medium', 'long')
ORDER BY gap_duration_minutes DESC;
```

---

#### 4.2.4 任务执行历史表 (task_executions)

```sql
CREATE TABLE task_executions (
  time TIMESTAMPTZ NOT NULL,
  task_id BIGINT NOT NULL REFERENCES scraper_tasks(id),
  platform VARCHAR(50) NOT NULL,

  -- 执行状态
  status VARCHAR(20) NOT NULL,                   -- running/success/failed/partial
  celery_task_id VARCHAR(255),

  -- 执行统计
  items_total INT DEFAULT 0,
  items_processed INT DEFAULT 0,
  items_success INT DEFAULT 0,
  items_failed INT DEFAULT 0,
  success_rate NUMERIC(5, 2),

  -- 性能指标
  duration_seconds INT,
  avg_response_time_ms INT,
  requests_per_second NUMERIC(6, 2),

  -- 错误信息
  error_message TEXT,
  error_details JSONB,

  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

-- 转换为 Hypertable
SELECT create_hypertable('task_executions', 'time');

-- 索引
CREATE INDEX idx_execution_task_time ON task_executions (task_id, time DESC);
CREATE INDEX idx_execution_status ON task_executions (status, time DESC);

-- 压缩策略
ALTER TABLE task_executions SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'task_id, platform'
);
SELECT add_compression_policy('task_executions', INTERVAL '7 days');

-- 保留策略（90天后删除）
SELECT add_retention_policy('task_executions', INTERVAL '90 days');
```

---

## 5. DragonflyDB 缓存设计

### 5.1 缓存策略

| 缓存类型 | Key 格式 | 数据结构 | TTL | 更新策略 | 用途 |
|---------|---------|---------|-----|---------|------|
| **最新价格** | `price:latest:{item_id}` | Hash | 5分钟 | 采集时更新 | API 快速查询 |
| **热门饰品** | `items:hot:top:{N}` | List | 10分钟 | 定时刷新 | 仪表盘展示 |
| **套利机会** | `arbitrage:opportunities` | Sorted Set | 5分钟 | 计算后缓存 | 实时套利列表 |
| **用户会话** | `session:{session_id}` | Hash | 24小时 | 登录时创建 | 用户认证 |
| **系统心跳** | `system:heartbeat` | String | 5分钟 | 每1分钟更新 | ⭐ 缺口检测 |
| **HA主备锁** | `ha:master_lock` | String | 60秒 | Master续期 | ⭐ 主备切换 |
| **实例心跳** | `ha:heartbeat:{instance_id}` | String | 2分钟 | 每30秒更新 | ⭐ 故障检测 |
| **K线数据** | `kline:{item_id}:{interval}` | List | 30分钟 | 查询时缓存 | K线图加载 |

---

### 5.2 高可用相关缓存 (新增) ⭐

#### 5.2.1 主备锁 (Master Lock)

```redis
# Key: ha:master_lock
# Type: String
# TTL: 60秒
# Value: instance_id (如 "instance-A")

# 获取主备锁 (只有一个实例能成功)
SET ha:master_lock "instance-A" NX EX 60

# 续期主备锁 (Master每30秒续期一次)
EXPIRE ha:master_lock 60

# 检查当前Master
GET ha:master_lock
```

#### 5.2.2 实例心跳

```redis
# Key: ha:heartbeat:instance-A
# Type: String
# TTL: 120秒
# Value: ISO时间戳

# 写入心跳
SET ha:heartbeat:instance-A "2025-12-13T10:30:00Z" EX 120

# 检查实例是否存活
GET ha:heartbeat:instance-A
TTL ha:heartbeat:instance-A
```

---

## 6. 数据连续性保障方案

### 6.1 方案概览

```
┌──────────────────────────────────────────────────────────────┐
│                    数据连续性保障体系                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  [阶段1: 系统初始化]                                          │
│  • 检测是否首次启动                                           │
│  • 首次启动: 采集当前价格作为基准数据集                       │
│  • 非首次: 执行缺口检测                                       │
│                                                              │
│  [阶段2: 持续采集]                                            │
│  • 高频实时采集 (5/30/120分钟,按优先级)                       │
│  • 数据写入 TimescaleDB + DragonflyDB                        │
│  • 心跳检测 (每1分钟)                                         │
│  • 数据质量标记                                               │
│                                                              │
│  [阶段3: 缺口检测]                                            │
│  • 系统重启时自动检测数据缺口                                 │
│  • 比对上次心跳时间与当前时间                                 │
│  • 计算每个饰品的缺失时间段                                   │
│  • 评估缺口严重程度 (short/medium/long)                      │
│                                                              │
│  [阶段4: 缺口补齐]                                            │
│  • 短期缺口 (< 1小时): 线性插值 (quality_score=80)           │
│  • 中期缺口 (1-24小时): 使用当前价格估算 (quality_score=60)  │
│  • 长期缺口 (> 24小时): 仅记录,不补齐                        │
│  • 写入 data_gap_logs 表                                     │
│                                                              │
│  [阶段5: 高可用部署]                                          │
│  • 双实例部署 (主备模式)                                      │
│  • 自动故障切换 (DragonflyDB分布式锁)                         │
│  • 数据库自动备份 (每日3点)                                   │
│  • 监控告警 (Prometheus + Grafana)                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

### 6.2 首次启动: 历史数据导入 + 基准数据集 ⭐ (已更新)

```python
# backend/app/scrapers/initial_setup.py

async def check_and_initialize():
    """
    系统启动时检查是否首次启动

    首次启动:
      1. 导入历史数据 (通过 Pricempire API)
      2. 建立基准数据集 (采集当前价格)
    非首次: 执行缺口检测和补齐
    """

    # 检查是否有历史数据
    has_data = await check_has_price_data()

    if not has_data:
        logger.info("🚀 首次启动检测到")

        # 步骤1: 导入历史数据
        if os.getenv("PRICEMPIRE_API_KEY"):
            logger.info("📥 开始导入历史价格数据...")
            await import_historical_data()
        else:
            logger.warning("⚠️ 未配置 PRICEMPIRE_API_KEY，跳过历史数据导入")

        # 步骤2: 建立当前价格基准
        logger.info("📊 开始建立当前价格基准数据集...")
        await build_baseline_dataset()
    else:
        logger.info("🔍 检测到历史数据,执行缺口检测...")
        await detect_and_fill_gaps()


async def import_historical_data():
    """
    首次启动: 从 Pricempire API 导入历史价格数据

    导入策略:
    - 高优先级饰品 (8-10): 导入过去30天数据 (每小时粒度)
    - 中优先级饰品 (5-7):  导入过去30天数据 (每日粒度)
    - 低优先级饰品 (1-4):  导入过去7天数据 (每日粒度)
    """

    items = await get_all_active_items()

    # 按优先级分组
    high_priority = [item for item in items if item.priority >= 8]
    medium_priority = [item for item in items if 5 <= item.priority < 8]
    low_priority = [item for item in items if item.priority < 5]

    total_imported = 0

    # 导入高优先级饰品 (30天，每小时)
    logger.info(f"📈 导入高优先级饰品历史数据: {len(high_priority)} 个")
    for item in high_priority:
        try:
            data = await fetch_pricempire_history(
                item_name=item.market_hash_name,
                days=30,
                granularity='hourly'
            )

            await save_historical_prices(
                item_id=item.id,
                price_data=data,
                data_source='historical_import',
                quality_score=95
            )

            total_imported += 1

            # 限流：每次请求间隔1秒
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.error(f"导入失败: {item.market_hash_name}, 错误: {e}")

    # 导入中优先级饰品 (30天，每日)
    logger.info(f"📊 导入中优先级饰品历史数据: {len(medium_priority)} 个")
    for item in medium_priority:
        try:
            data = await fetch_pricempire_history(
                item_name=item.market_hash_name,
                days=30,
                granularity='daily'
            )

            await save_historical_prices(
                item_id=item.id,
                price_data=data,
                data_source='historical_import',
                quality_score=95
            )

            total_imported += 1
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.error(f"导入失败: {item.market_hash_name}, 错误: {e}")

    # 导入低优先级饰品 (7天，每日)
    logger.info(f"📉 导入低优先级饰品历史数据: {len(low_priority)} 个")
    for item in low_priority:
        try:
            data = await fetch_pricempire_history(
                item_name=item.market_hash_name,
                days=7,
                granularity='daily'
            )

            await save_historical_prices(
                item_id=item.id,
                price_data=data,
                data_source='historical_import',
                quality_score=95
            )

            total_imported += 1
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.error(f"导入失败: {item.market_hash_name}, 错误: {e}")

    logger.info(f"✅ 历史数据导入完成: 成功导入 {total_imported}/{len(items)} 个饰品")


async def fetch_pricempire_history(item_name: str, days: int, granularity: str):
    """
    从 Pricempire API 获取历史价格

    参数:
        item_name: 饰品名称
        days: 历史天数 (7, 30, 60, 90)
        granularity: 数据粒度 ('hourly' 或 'daily')

    返回:
        {
            "steam": [{"timestamp": "...", "price": 35.50, "volume": 120}, ...],
            "buff": [{"timestamp": "...", "price": 33.80, "volume": 100}, ...]
        }
    """

    url = "https://api.pricempire.com/v3/items/history"
    headers = {
        "Authorization": f"Bearer {os.getenv('PRICEMPIRE_API_KEY')}",
        "Content-Type": "application/json"
    }
    params = {
        "name": item_name,
        "days": days,
        "granularity": granularity,
        "sources": ["steam", "buff163"]
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()


async def save_historical_prices(item_id: int, price_data: dict, data_source: str, quality_score: int):
    """
    批量保存历史价格到 TimescaleDB
    """

    async with db_session() as session:
        for platform in ['steam', 'buff']:
            if platform in price_data and 'price_history' in price_data[platform]:
                for record in price_data[platform]['price_history']:
                    price_record = PriceHistory(
                        time=datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')),
                        item_id=item_id,
                        platform=platform,
                        price=record['price'],
                        volume=record.get('volume', 0),
                        currency='CNY',
                        data_source=data_source,
                        is_estimated=False,
                        is_baseline=False,
                        quality_score=quality_score,
                        collected_at=datetime.now()
                    )
                    session.add(price_record)

        await session.commit()


async def build_baseline_dataset():
    """
    首次启动: 采集所有饰品的当前价格作为基准

    注意: 此步骤在历史数据导入之后执行，用于建立"当前时刻"的价格基准
    """

    items = await get_all_active_items()

    logger.info(f"开始采集 {len(items)} 个饰品的当前价格基准...")

    for item in items:
        try:
            # Steam 价格
            steam_price = await scrape_steam_price(item.market_hash_name)

            # Buff 价格
            buff_price = await scrape_buff_price(item.market_hash_name)

            # 写入数据库,标记为基准数据
            await save_price_history(
                item_id=item.id,
                platform="steam",
                price=steam_price.price,
                volume=steam_price.volume,
                is_baseline=True,  # ⭐ 标记为基准数据
                data_source='scraper',
                quality_score=100,
                collected_at=datetime.now()
            )

            await save_price_history(
                item_id=item.id,
                platform="buff",
                price=buff_price.price,
                volume=buff_price.volume,
                is_baseline=True,
                data_source='scraper',
                quality_score=100,
                collected_at=datetime.now()
            )

            # 限流
            await asyncio.sleep(random.uniform(2.0, 3.0))

        except Exception as e:
            logger.error(f"采集失败: {item.market_hash_name}, 错误: {e}")
            continue

    logger.info(f"✅ 当前价格基准数据集建立完成,共采集 {len(items)} 个饰品")

    # 记录系统首次启动时间
    await save_system_metadata(
        key="first_start_time",
        value=datetime.now().isoformat()
    )
```

---

### 6.3 心跳检测机制

```python
# backend/app/scrapers/heartbeat.py

import asyncio
from datetime import datetime
from app.core.cache import dragonfly_client
from app.core.database import db_session

async def heartbeat_monitor():
    """
    心跳监控: 每1分钟向 DragonflyDB 和 TimescaleDB 写入心跳

    用途:
    1. 检测系统是否正常运行
    2. 缺口检测的依据
    3. HA故障切换的触发条件
    """

    while True:
        try:
            current_time = datetime.now()

            # 1. 写入 DragonflyDB (快速检测)
            await dragonfly_client.set(
                "system:heartbeat",
                current_time.isoformat(),
                ex=300  # 5分钟过期
            )

            # 2. 写入 TimescaleDB (持久化记录)
            await save_system_heartbeat(
                component="scraper",
                instance_id=os.getenv("INSTANCE_ID", "instance-A"),
                status="active",
                cpu_percent=psutil.cpu_percent(),
                memory_percent=psutil.virtual_memory().percent,
                active_tasks=get_active_task_count()
            )

            logger.debug(f"💓 心跳: {current_time}")

        except Exception as e:
            logger.error(f"心跳写入失败: {e}")

        # 每1分钟执行一次
        await asyncio.sleep(60)


async def save_system_heartbeat(**kwargs):
    """写入心跳到 TimescaleDB"""
    async with db_session() as session:
        heartbeat = SystemHeartbeat(
            time=datetime.now(),
            **kwargs
        )
        session.add(heartbeat)
        await session.commit()
```

---

### 6.4 缺口检测算法

```python
# backend/app/scrapers/gap_detector.py

from datetime import datetime, timedelta
from typing import List, Dict

async def detect_data_gaps() -> List[Dict]:
    """
    系统重启时检测数据缺口

    返回: [
        {
            "item_id": 12345,
            "item_name": "AK-47 | Redline (FT)",
            "platform": "steam",
            "gap_start": "2025-12-13T08:00:00Z",
            "gap_end": "2025-12-13T10:00:00Z",
            "gap_duration_minutes": 120,
            "severity": "medium"
        },
        ...
    ]
    """

    gaps = []
    current_time = datetime.now()

    # 1. 获取上次系统心跳时间
    last_heartbeat = await get_last_heartbeat_from_db()

    if not last_heartbeat:
        logger.warning("⚠️ 未找到历史心跳记录,可能是首次启动")
        return []

    # 2. 计算系统中断时长
    downtime_minutes = (current_time - last_heartbeat).total_seconds() / 60

    if downtime_minutes < 5:
        logger.info("✅ 系统连续运行,无数据缺口")
        return []

    logger.warning(f"⚠️ 检测到系统中断: {downtime_minutes:.1f} 分钟 ({last_heartbeat} ~ {current_time})")

    # 3. 获取所有需要检查的饰品
    items = await get_all_active_items()

    for item in items:
        for platform in ["steam", "buff"]:
            # 4. 查询每个饰品的最新价格记录时间
            last_price_record = await get_last_price_record(
                item_id=item.id,
                platform=platform
            )

            if not last_price_record:
                # 该饰品从未采集过,跳过
                continue

            # 5. 计算缺口
            gap_start = last_price_record.collected_at
            gap_end = current_time
            gap_duration = (gap_end - gap_start).total_seconds() / 60

            # 6. 判断严重程度
            if gap_duration < 60:
                severity = "short"   # < 1小时
            elif gap_duration < 1440:
                severity = "medium"  # 1-24小时
            else:
                severity = "long"    # > 24小时

            gaps.append({
                "item_id": item.id,
                "item_name": item.market_hash_name,
                "platform": platform,
                "gap_start": gap_start.isoformat(),
                "gap_end": gap_end.isoformat(),
                "gap_duration_minutes": int(gap_duration),
                "severity": severity
            })

    logger.info(f"📊 检测到 {len(gaps)} 个数据缺口")
    return gaps


async def get_last_heartbeat_from_db():
    """从 TimescaleDB 获取最后一次心跳时间"""
    async with db_session() as session:
        result = await session.execute(
            """
            SELECT time FROM system_heartbeats
            WHERE component = 'scraper'
            ORDER BY time DESC
            LIMIT 1
            """
        )
        row = result.fetchone()
        return row[0] if row else None
```

---

### 6.5 缺口补齐策略

```python
# backend/app/scrapers/gap_filler.py

async def fill_data_gaps(gaps: List[Dict]):
    """
    根据缺口严重程度采取不同的补齐策略
    """

    for gap in gaps:
        severity = gap["severity"]

        try:
            if severity == "short":
                # 短期缺口: 线性插值
                await fill_short_gap(gap)

            elif severity == "medium":
                # 中期缺口: 使用当前价格估算
                await fill_medium_gap(gap)

            else:  # long
                # 长期缺口: 仅记录,不补齐
                await record_long_gap(gap)

        except Exception as e:
            logger.error(f"缺口补齐失败: {gap['item_name']}, 错误: {e}")


async def fill_short_gap(gap: Dict):
    """
    短期缺口补齐: 线性插值

    策略:
    1. 获取缺口前的最后一次价格 (P1)
    2. 获取缺口后的第一次价格 (P2, 即当前价格)
    3. 在时间轴上均匀插值
    4. 标记为 data_source='interpolated', quality_score=80
    """

    item_id = gap["item_id"]
    platform = gap["platform"]
    gap_start = datetime.fromisoformat(gap["gap_start"])
    gap_end = datetime.fromisoformat(gap["gap_end"])

    # 1. 获取缺口前的价格
    price_before = await get_price_at_time(item_id, platform, gap_start)

    # 2. 获取当前价格
    current_price = await scrape_current_price(item_id, platform)
    price_after = current_price.price

    # 3. 计算需要插值的数据点数量
    # 根据饰品优先级决定间隔 (高优先级5分钟,中30分钟,低2小时)
    item = await get_item_by_id(item_id)
    interval_minutes = get_scrape_interval(item.priority)

    gap_minutes = gap["gap_duration_minutes"]
    num_points = int(gap_minutes / interval_minutes)

    # 4. 线性插值
    for i in range(1, num_points + 1):
        time_point = gap_start + timedelta(minutes=interval_minutes * i)

        # 线性插值公式: P(t) = P1 + (P2 - P1) * (t / T)
        ratio = (i * interval_minutes) / gap_minutes
        interpolated_price = price_before + (price_after - price_before) * ratio

        # 5. 写入数据库
        await save_price_history(
            item_id=item_id,
            platform=platform,
            price=round(interpolated_price, 2),
            volume=0,  # 交易量无法估算
            collected_at=time_point,
            data_source='interpolated',  # ⭐ 标记为插值
            is_estimated=True,
            quality_score=80  # ⭐ 质量分数
        )

    # 6. 记录缺口日志
    await save_gap_log(
        item_id=item_id,
        platform=platform,
        gap_start=gap_start,
        gap_end=gap_end,
        gap_duration_minutes=gap_minutes,
        severity="short",
        fill_status="filled",
        fill_method="interpolated",
        filled_points=num_points
    )

    logger.info(f"✅ 短期缺口补齐: {gap['item_name']}, 插值 {num_points} 个点")


async def fill_medium_gap(gap: Dict):
    """
    中期缺口补齐: 使用当前价格估算

    策略:
    - 假设缺口期间价格保持不变 (等于当前价格)
    - 标记为 data_source='estimated', quality_score=60
    """

    item_id = gap["item_id"]
    platform = gap["platform"]
    gap_start = datetime.fromisoformat(gap["gap_start"])
    gap_end = datetime.fromisoformat(gap["gap_end"])
    gap_minutes = gap["gap_duration_minutes"]

    # 获取当前价格
    current_price = await scrape_current_price(item_id, platform)

    # 每30分钟插入一个估算点
    interval_minutes = 30
    num_points = int(gap_minutes / interval_minutes)

    for i in range(1, num_points + 1):
        time_point = gap_start + timedelta(minutes=interval_minutes * i)

        await save_price_history(
            item_id=item_id,
            platform=platform,
            price=current_price.price,
            volume=0,
            collected_at=time_point,
            data_source='estimated',  # ⭐ 标记为估算
            is_estimated=True,
            quality_score=60  # ⭐ 较低的质量分数
        )

    # 记录缺口日志
    await save_gap_log(
        item_id=item_id,
        platform=platform,
        gap_start=gap_start,
        gap_end=gap_end,
        gap_duration_minutes=gap_minutes,
        severity="medium",
        fill_status="filled",
        fill_method="estimated",
        filled_points=num_points
    )

    logger.warning(f"⚠️ 中期缺口估算补齐: {gap['item_name']}, {num_points} 个点")


async def record_long_gap(gap: Dict):
    """
    长期缺口: 仅记录,不补齐

    原因: 时间跨度过长 (> 24小时),补齐数据没有意义
    """

    item_id = gap["item_id"]
    platform = gap["platform"]
    gap_start = datetime.fromisoformat(gap["gap_start"])
    gap_end = datetime.fromisoformat(gap["gap_end"])
    gap_minutes = gap["gap_duration_minutes"]

    # 仅记录到缺口日志表
    await save_gap_log(
        item_id=item_id,
        platform=platform,
        gap_start=gap_start,
        gap_end=gap_end,
        gap_duration_minutes=gap_minutes,
        severity="long",
        fill_status="unfilled",
        fill_method="none",
        filled_points=0,
        gap_reason="gap_too_long"
    )

    logger.error(f"❌ 长期缺口无法补齐: {gap['item_name']}, 持续 {gap_minutes/60:.1f} 小时")
```

---

### 6.6 高可用部署 (主备模式)

```python
# backend/app/core/ha_manager.py

import asyncio
import os
from datetime import datetime
from app.core.cache import dragonfly_client

class HighAvailabilityManager:
    """
    高可用管理器: 主备切换逻辑

    原理:
    1. 使用 DragonflyDB 的 SET NX 实现分布式锁
    2. Master 实例持有锁,定期续期
    3. Standby 实例检测 Master 失效后自动接管
    """

    def __init__(self, instance_id: str = None):
        self.instance_id = instance_id or os.getenv("INSTANCE_ID", "instance-A")
        self.is_master = False
        self.heartbeat_interval = 30  # 30秒
        self.lock_ttl = 60  # 锁过期时间60秒

    async def start(self):
        """启动高可用监控"""
        logger.info(f"🚀 启动 HA Manager: {self.instance_id}")

        # 尝试获取 master 锁
        await self.try_acquire_master_lock()

        # 启动心跳循环
        asyncio.create_task(self.heartbeat_loop())

        # 启动故障检测
        asyncio.create_task(self.failover_detector())

    async def try_acquire_master_lock(self):
        """尝试获取 master 角色"""

        # 使用 Redis SET NX 实现分布式锁
        acquired = await dragonfly_client.set(
            "ha:master_lock",
            self.instance_id,
            nx=True,  # 仅当 key 不存在时设置
            ex=self.lock_ttl
        )

        if acquired:
            self.is_master = True
            logger.info(f"🎯 {self.instance_id} 成为 Master 实例")

            # 启动采集任务
            await self.start_scraper_tasks()
        else:
            self.is_master = False
            current_master = await dragonfly_client.get("ha:master_lock")
            logger.info(f"⏸️ {self.instance_id} 为 Standby 实例 (当前Master: {current_master})")

    async def heartbeat_loop(self):
        """心跳循环: Master 定期更新锁,Standby 定期写入心跳"""

        while True:
            try:
                current_time = datetime.now().isoformat()

                if self.is_master:
                    # Master: 续期锁
                    await dragonfly_client.expire("ha:master_lock", self.lock_ttl)

                    # 写入 Master 心跳
                    await dragonfly_client.set(
                        f"ha:heartbeat:{self.instance_id}",
                        current_time,
                        ex=120
                    )

                    logger.debug(f"💓 Master 心跳: {self.instance_id}")
                else:
                    # Standby: 只写心跳
                    await dragonfly_client.set(
                        f"ha:heartbeat:{self.instance_id}",
                        current_time,
                        ex=120
                    )

                    logger.debug(f"💓 Standby 心跳: {self.instance_id}")

            except Exception as e:
                logger.error(f"心跳写入失败: {e}")

            await asyncio.sleep(self.heartbeat_interval)

    async def failover_detector(self):
        """故障检测: Standby 检测 Master 失效后自动接管"""

        while True:
            try:
                if not self.is_master:
                    # 检查 master 锁是否存在
                    master_lock = await dragonfly_client.get("ha:master_lock")

                    if not master_lock:
                        # Master 锁已过期,尝试接管
                        logger.warning(f"⚠️ Master 实例失效,{self.instance_id} 尝试接管")
                        await self.try_acquire_master_lock()

            except Exception as e:
                logger.error(f"故障检测失败: {e}")

            await asyncio.sleep(10)  # 每10秒检测一次

    async def start_scraper_tasks(self):
        """启动采集任务 (仅 Master 执行)"""
        from app.scrapers.scheduler import start_scheduler
        await start_scheduler()

    async def stop_scraper_tasks(self):
        """停止采集任务 (Master 降级时)"""
        from app.scrapers.scheduler import stop_scheduler
        await stop_scheduler()


# 全局 HA Manager 实例
ha_manager = HighAvailabilityManager()
```

---

## 7. 数据保留与归档策略

### 7.1 数据保留策略

| 数据类型 | 保留时长 | 存储位置 | 压缩策略 | 归档策略 |
|---------|---------|---------|---------|---------|
| **饰品基本信息** | 永久 | PostgreSQL | 不压缩 | 不归档 |
| **最近价格数据** | 30天 | TimescaleDB | 7天后压缩 | 不归档 |
| **30-90天价格** | 90天 | TimescaleDB | 已压缩 | 聚合为小时级别 |
| **90-365天价格** | 1年 | TimescaleDB | 已压缩 | 聚合为日级别 |
| **1年以上价格** | 永久 | Parquet文件 | - | 导出归档 |
| **采集日志** | 90天 | TimescaleDB | 30天后压缩 | 90天后删除 |
| **心跳记录** | 30天 | TimescaleDB | 7天后压缩 | 30天后删除 |
| **缺口日志** | 永久 | PostgreSQL | 不压缩 | 不归档 (重要) |

---

### 7.2 数据聚合脚本

```sql
-- 每月执行一次: 将30-90天的数据聚合为小时级别
INSERT INTO price_history_hourly
SELECT time_bucket('1 hour', time) as time,
       item_id,
       platform,
       AVG(price) as price,
       SUM(volume) as volume,
       'aggregated_hourly' as data_source,
       80 as quality_score
FROM price_history
WHERE time < NOW() - INTERVAL '30 days'
  AND time >= NOW() - INTERVAL '90 days'
  AND data_source = 'scraper'  -- 只聚合真实数据
GROUP BY time_bucket('1 hour', time), item_id, platform;

-- 删除原始明细数据
DELETE FROM price_history
WHERE time < NOW() - INTERVAL '30 days'
  AND time >= NOW() - INTERVAL '90 days';
```

---

## 8. 数据库部署配置

### 8.1 Docker Compose 配置

```yaml
version: '3.8'

services:
  # TimescaleDB (包含 PostgreSQL)
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    container_name: cs-timescaledb
    environment:
      POSTGRES_DB: cs_items
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      TIMESCALEDB_TELEMETRY: 'off'
    ports:
      - "5432:5432"
    volumes:
      - ./data/timescaledb:/var/lib/postgresql/data
      - ./backend/database/init.sql:/docker-entrypoint-initdb.d/init.sql
    command: postgres -c shared_preload_libraries=timescaledb
    restart: unless-stopped

  # DragonflyDB (Redis 兼容)
  dragonfly:
    image: docker.dragonflydb.io/dragonflydb/dragonfly
    container_name: cs-dragonfly
    ulimits:
      memlock: -1
    ports:
      - "6379:6379"
    volumes:
      - ./data/dragonfly:/data
    command: dragonfly --dir /data --requirepass ${DRAGONFLY_PASSWORD} --save_schedule "*:30"
    restart: unless-stopped
```

---

### 8.2 数据库初始化脚本

```sql
-- backend/database/init.sql

-- 创建 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 创建更新时间触发器函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ language 'plpgsql';

-- 创建所有 PostgreSQL 表
-- (见 4.1 节)

-- 创建所有 TimescaleDB 表
-- (见 4.2 节)

-- 初始化平台配置
INSERT INTO platform_config (platform, buy_fee_rate, sell_fee_rate) VALUES
('steam', 0.0000, 0.1500),
('buff', 0.0250, 0.0250);
```

---

### 8.3 数据库自动备份

```bash
#!/bin/bash
# scripts/backup_database.sh

BACKUP_DIR="/var/backups/cs-items"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/cs_items_$TIMESTAMP.sql"

mkdir -p $BACKUP_DIR

# 执行备份
docker exec cs-timescaledb pg_dump \
  -U postgres \
  -d cs_items \
  -F c \
  -f /tmp/backup.dump

docker cp cs-timescaledb:/tmp/backup.dump $BACKUP_FILE

# 压缩备份
gzip $BACKUP_FILE

# 删除 7 天前的备份
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "✅ 数据库备份完成: $BACKUP_FILE.gz"
```

**定时任务**:
```bash
# crontab -e
0 3 * * * /path/to/scripts/backup_database.sh
```

---

## 9. 数据库性能优化

### 9.1 关键索引策略

```sql
-- 1. 饰品全文搜索索引
CREATE INDEX idx_item_name_gin ON items
USING gin(to_tsvector('simple', market_hash_name));

-- 2. 价格历史时序索引 (TimescaleDB 自动优化)
CREATE INDEX idx_price_recent ON price_history (time DESC)
WHERE time > NOW() - INTERVAL '7 days';

-- 3. 套利查询优化 (覆盖索引)
CREATE INDEX idx_arbitrage_query ON price_history (item_id, platform, time DESC)
INCLUDE (price, volume);

-- 4. 数据质量查询
CREATE INDEX idx_price_quality ON price_history (data_source, is_estimated);
```

---

### 9.2 查询性能优化

```sql
-- 使用 time_bucket 进行高效聚合
SELECT time_bucket('1 hour', time) as hour,
       AVG(price) as avg_price,
       MAX(volume) as max_volume
FROM price_history
WHERE item_id = 12345
  AND time > NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour DESC;

-- 使用 EXPLAIN ANALYZE 分析查询计划
EXPLAIN ANALYZE
SELECT * FROM price_history
WHERE item_id = 12345
  AND time > NOW() - INTERVAL '7 days';
```

---

## 10. 监控与维护

### 10.1 Prometheus 监控指标

```python
# backend/app/api/metrics.py

from prometheus_client import Counter, Gauge, Histogram

# 心跳监控
heartbeat_timestamp = Gauge(
    'scraper_heartbeat_timestamp',
    'Last heartbeat timestamp (unix)'
)

# 缺口监控
gap_count = Gauge(
    'scraper_gap_count',
    'Number of detected data gaps'
)

gap_duration_histogram = Histogram(
    'scraper_gap_duration_minutes',
    'Duration of data gaps in minutes',
    buckets=[5, 15, 60, 360, 1440]  # 5分钟, 15分钟, 1小时, 6小时, 24小时
)

# 采集成功率
scraper_success_rate = Gauge(
    'scraper_success_rate',
    'Scraper success rate (0-1)'
)

# 数据质量分布
data_quality_distribution = Gauge(
    'price_data_quality_score',
    'Data quality score distribution',
    ['data_source']
)
```

---

### 10.2 Grafana 仪表盘

**关键监控面板**:

1. **系统健康**
   - 心跳延迟 (当前时间 - 最后心跳时间)
   - Master/Standby 状态
   - 活跃任务数

2. **数据完整性**
   - 数据缺口数量 (按严重程度)
   - 缺口持续时间分布
   - 补齐成功率

3. **数据质量**
   - 真实数据占比 (scraper)
   - 插值数据占比 (interpolated)
   - 估算数据占比 (estimated)
   - 平均质量分数

4. **采集性能**
   - 采集成功率
   - 平均响应时间
   - 每秒请求数 (QPS)

---

### 10.3 告警规则

```yaml
# alertmanager.yml

groups:
  - name: data_continuity_alerts
    rules:
      # 心跳超时告警
      - alert: ScraperHeartbeatTimeout
        expr: (time() - scraper_heartbeat_timestamp) > 300
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "爬虫心跳超时"
          description: "超过 5 分钟未收到心跳信号,系统可能已中断"

      # 数据缺口告警
      - alert: DataGapDetected
        expr: scraper_gap_count > 0
        labels:
          severity: warning
        annotations:
          summary: "检测到数据缺口"
          description: "发现 {{ $value }} 个数据缺口,请检查系统运行状态"

      # 采集成功率过低
      - alert: LowScrapeSuccessRate
        expr: scraper_success_rate < 0.9
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "采集成功率过低"
          description: "成功率 < 90%,请检查网络或API限流"

      # 主备切换告警
      - alert: HAFailoverDetected
        expr: changes(ha_master_instance_id[5m]) > 0
        labels:
          severity: info
        annotations:
          summary: "主备切换发生"
          description: "检测到 Master 实例切换,请检查原 Master 状态"
```

---

## 11. 实施路线图

### 阶段 1: 基础数据采集 (第1-2周)
- [x] 实现首次启动基准数据采集
- [x] 实现高频实时采集 (5/30/120分钟)
- [x] 实现心跳检测机制
- [x] 数据库表结构设计 (含数据质量字段)

### 阶段 2: 缺口检测与补齐 (第3-4周)
- [ ] 实现缺口检测算法
- [ ] 实现短期缺口插值补齐
- [ ] 实现中期缺口估算补齐
- [ ] 实现缺口日志记录

### 阶段 3: 高可用部署 (第5-6周)
- [ ] 实现主备切换逻辑 (HA Manager)
- [ ] 配置数据库自动备份
- [ ] 配置监控告警 (Prometheus + Grafana)
- [ ] 双实例部署测试

### 阶段 4: 数据质量保障 (第7周)
- [ ] 实现数据完整性检查
- [ ] 实现数据质量报告
- [ ] 优化缓存策略

### 阶段 5: 压力测试与优化 (第8周)
- [ ] 压力测试 (模拟系统中断)
- [ ] 性能优化
- [ ] 文档完善

---

## 12. 总结

### 核心策略

1. **历史数据**:
   - ❌ 无法获取 (Steam/Buff 不提供历史API)
   - ✅ 从系统首次启动时刻开始积累

2. **实时数据**:
   - ✅ 高频采集 (5-120分钟,按优先级)
   - ✅ 心跳检测 (每1分钟)
   - ✅ 数据质量标记

3. **缺口补齐**:
   - ✅ 短期缺口 (< 1h): 线性插值 (quality=80)
   - ⚠️ 中期缺口 (1-24h): 估算补齐 (quality=60)
   - ❌ 长期缺口 (> 24h): 仅记录,不补齐

4. **高可用**:
   - ✅ 双实例主备模式
   - ✅ 自动故障切换 (DragonflyDB 分布式锁)
   - ✅ 数据库自动备份 (每日3点)
   - ✅ 监控告警 (Prometheus + Grafana)

---

**文档结束**

**下一步行动**:
1. 参考此设计创建数据库迁移脚本
2. 实现心跳检测和缺口检测模块
3. 实现缺口补齐策略
4. 配置高可用部署
