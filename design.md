# CS 饰品数据采集系统 - 设计文档

## 1. 项目概述

### 1.1 项目目标
构建一个**个人使用**的 CS2/CSGO 饰品市场数据采集和存储系统，持续抓取多平台价格数据，建立本地数据库，用于后续分析和查询。

### 1.2 核心价值
- 自动化采集所有饰品的多平台价格数据
- 建立完整的历史价格数据库
- 本地存储，数据完全可控
- 支持简单的命令行查询和导出

### 1.3 项目范围
- **包含**: 数据采集、存储、简单 CLI 查询
- **不包含**: Web UI、移动端、多用户系统、商业化功能
- **定位**: 后端数据服务，为未来分析做数据准备

---

## 2. 核心功能

### 2.1 数据采集（核心）

#### 2.1.1 目标数据源

**Steam 社区市场**
- [ ] 获取所有 CS2 饰品列表
- [ ] 采集实时价格和交易量
- [ ] 采集价格历史数据
- API: `steamcommunity.com/market/*`

**Buff (buff.163.com)**
- [ ] 采集 CNY 价格
- [ ] 交易量数据
- [ ] 可能需要逆向或使用 SteamDT API

**其他平台（可选）**
- [ ] C5Game
- [ ] IGXE
- [ ] UU898

**饰品元数据**
- [ ] 饰品名称、类型、品质
- [ ] 稀有度、磨损等级
- [ ] 图片 URL
- [ ] 分类信息（武器类型、箱子等）

#### 2.1.2 采集策略

**全量采集**
```python
# 第一次运行：获取所有饰品
1. 从 Steam Market 获取所有 CS2 物品列表
2. 提取 market_hash_name 作为唯一标识
3. 存储到 items 表
```

**增量更新**
```python
# 定时任务：更新价格数据
1. 从 items 表读取所有饰品
2. 遍历每个饰品，获取最新价格
3. 插入到 price_history 表
4. 频率：每 10-30 分钟一次
```

**反爬虫对策**
- 请求间隔：每个请求间隔 1-3 秒（随机）
- User-Agent 轮换
- 使用代理池（如需要）
- 错误重试机制（指数退避）
- 保存 cookies（保持会话）

**数据校验**
- 价格异常检测（突然为 0 或异常高）
- 缺失字段处理
- 重复数据去重

### 2.2 数据存储

#### 2.2.1 存储策略
- **饰品基础信息**: PostgreSQL（关系型）
- **价格时序数据**: PostgreSQL（使用 TimescaleDB 扩展）或 InfluxDB
- **配置信息**: JSON 文件或数据库表
- **日志**: 文件日志

#### 2.2.2 数据保留策略
- 原始数据永久保留
- 定期聚合（每小时/每日均价）
- 数据压缩（旧数据）

### 2.3 数据查询（CLI）

#### 2.3.1 命令行工具
```bash
# 查询饰品价格
python cli.py price "AK-47 | Redline (Field-Tested)"

# 查询价格历史
python cli.py history "AK-47 | Redline (Field-Tested)" --days 30

# 导出数据
python cli.py export --format csv --output data.csv

# 统计信息
python cli.py stats --top 10 --by volume

# 价格对比
python cli.py compare "AK-47 | Redline (Field-Tested)" --platforms steam,buff
```

#### 2.3.2 数据导出
- CSV 格式
- JSON 格式
- 支持筛选条件导出

### 2.4 数据分析（简单）

#### 2.4.1 基础统计
- [ ] 计算涨跌幅
- [ ] 计算移动平均线
- [ ] 计算价格波动率
- [ ] 跨平台价差分析

#### 2.4.2 异动检测
- [ ] 价格异常波动提醒（>20%）
- [ ] 交易量突然增加
- [ ] 套利机会（价差>15%）
- [ ] 输出到日志或发送通知

---

## 3. 技术架构

### 3.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│                  CLI 查询工具                        │
│  命令行交互 | 数据导出 | 简单统计                     │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                 数据处理层                           │
│  数据清洗 | 异常检测 | 统计计算 | 价格分析            │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                 数据采集层                           │
│  Steam 爬虫 | Buff 爬虫 | 任务调度 | 限流控制        │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                 数据存储层                           │
│  PostgreSQL (饰品信息 + 价格历史)                    │
│  SQLite (配置) | 文件系统 (日志)                     │
└─────────────────────────────────────────────────────┘
```

### 3.2 技术栈

#### 3.2.1 推荐方案：Python
```yaml
语言: Python 3.10+
优势:
  - 丰富的数据处理库 (pandas, numpy)
  - 爬虫生态完善 (requests, beautifulsoup, scrapy)
  - 快速开发

核心库:
  - requests: HTTP 请求
  - beautifulsoup4/lxml: HTML 解析
  - sqlalchemy: ORM 数据库操作
  - psycopg2: PostgreSQL 驱动
  - schedule/APScheduler: 任务调度
  - pandas: 数据分析
  - click: CLI 工具
  - loguru: 日志管理
```

#### 3.2.2 数据库选择
```yaml
方案一: PostgreSQL + TimescaleDB 扩展
  - 适合时序数据
  - SQL 查询方便
  - 易于维护
  - 推荐 ⭐⭐⭐⭐⭐

方案二: PostgreSQL (纯)
  - 简单，只需一个数据库
  - 分区表处理大量数据
  - 推荐 ⭐⭐⭐⭐

方案三: PostgreSQL + InfluxDB
  - InfluxDB 专门存储时序价格数据
  - 高性能查询
  - 但需要维护两个数据库
  - 推荐 ⭐⭐⭐
```

#### 3.2.3 部署方式
```yaml
本地开发:
  - Docker Compose 启动 PostgreSQL
  - Python 虚拟环境
  - Cron 定时任务

生产环境:
  - Linux 服务器 / 本地主机
  - systemd 服务管理
  - 自动重启机制
```

---

## 4. 数据模型设计

### 4.1 饰品基础信息表 (items)

```sql
CREATE TABLE items (
  id BIGSERIAL PRIMARY KEY,
  market_hash_name VARCHAR(255) UNIQUE NOT NULL,  -- Steam 市场唯一名称
  name_cn VARCHAR(255),                           -- 中文名称
  type VARCHAR(50),                               -- 类型：Weapon, Knife, Gloves, Sticker, Case 等
  weapon_type VARCHAR(50),                        -- 武器类型：Rifle, Pistol, SMG 等
  quality VARCHAR(50),                            -- 品质：Consumer, Industrial, Mil-Spec, Restricted, Classified, Covert
  rarity VARCHAR(50),                             -- 稀有度
  wear_category VARCHAR(50),                      -- 磨损类型：Factory New, Minimal Wear 等
  exterior VARCHAR(50),                           -- 外观
  category VARCHAR(50),                           -- 大类：武器、饰品、箱子等
  collection VARCHAR(100),                        -- 收藏品系列
  image_url VARCHAR(500),                         -- 图片 URL
  steam_market_url VARCHAR(500),                  -- Steam 市场链接
  is_active BOOLEAN DEFAULT TRUE,                 -- 是否还在采集
  first_seen_at TIMESTAMP DEFAULT NOW(),          -- 首次发现时间
  updated_at TIMESTAMP DEFAULT NOW(),             -- 最后更新时间
  metadata JSONB                                  -- 其他元数据（灵活存储）
);

CREATE INDEX idx_items_type ON items(type);
CREATE INDEX idx_items_quality ON items(quality);
CREATE INDEX idx_items_name ON items(market_hash_name);
```

### 4.2 价格历史表 (price_history)

```sql
CREATE TABLE price_history (
  id BIGSERIAL PRIMARY KEY,
  item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  platform VARCHAR(50) NOT NULL,                  -- steam, buff, c5game, igxe 等
  price NUMERIC(12, 2) NOT NULL,                  -- 价格
  currency VARCHAR(10) NOT NULL,                  -- CNY, USD, EUR
  volume INT DEFAULT 0,                           -- 24小时交易量
  lowest_price NUMERIC(12, 2),                    -- 最低价
  highest_price NUMERIC(12, 2),                   -- 最高价
  median_price NUMERIC(12, 2),                    -- 中位价
  sell_listings INT,                              -- 在售数量
  buy_orders INT,                                 -- 求购数量
  collected_at TIMESTAMP NOT NULL DEFAULT NOW(),  -- 采集时间

  -- 如果使用 TimescaleDB
  -- SELECT create_hypertable('price_history', 'collected_at');
);

-- 索引优化查询
CREATE INDEX idx_price_item_time ON price_history(item_id, collected_at DESC);
CREATE INDEX idx_price_platform_time ON price_history(platform, collected_at DESC);
CREATE INDEX idx_price_time ON price_history(collected_at DESC);

-- 复合索引用于常见查询
CREATE INDEX idx_price_item_platform_time ON price_history(item_id, platform, collected_at DESC);
```

### 4.3 采集任务日志表 (scraper_logs)

```sql
CREATE TABLE scraper_logs (
  id BIGSERIAL PRIMARY KEY,
  platform VARCHAR(50) NOT NULL,
  task_type VARCHAR(50),                          -- full_sync, price_update, metadata_sync
  status VARCHAR(20),                             -- running, completed, failed
  items_processed INT DEFAULT 0,
  items_failed INT DEFAULT 0,
  error_message TEXT,
  started_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  duration_seconds INT
);

CREATE INDEX idx_logs_platform_time ON scraper_logs(platform, started_at DESC);
```

### 4.4 平台配置表 (platform_configs)

```sql
CREATE TABLE platform_configs (
  id SERIAL PRIMARY KEY,
  platform VARCHAR(50) UNIQUE NOT NULL,
  base_url VARCHAR(255),
  is_enabled BOOLEAN DEFAULT TRUE,
  rate_limit_per_minute INT DEFAULT 20,           -- 每分钟请求限制
  request_delay_ms INT DEFAULT 1000,              -- 请求间隔（毫秒）
  last_sync_at TIMESTAMP,
  config JSONB,                                   -- 其他配置（headers, cookies 等）
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 插入默认配置
INSERT INTO platform_configs (platform, base_url, rate_limit_per_minute, request_delay_ms) VALUES
  ('steam', 'https://steamcommunity.com/market', 30, 2000),
  ('buff', 'https://buff.163.com/api', 20, 3000),
  ('c5game', 'https://www.c5game.com', 20, 3000);
```

---

## 5. 数据采集实现细节

### 5.1 Steam Market 采集

#### 5.1.1 获取所有饰品列表

```python
# 方法1: 从 Steam Market 搜索页获取
# https://steamcommunity.com/market/search/render/?appid=730

# 方法2: 使用 Steam API
# 需要 Steam API Key

# 方法3: 爬取饰品列表页
# 分页获取所有物品
```

**实现示例**:
```python
import requests
import time

def fetch_all_items(appid=730):
    """获取所有 CS2 饰品"""
    items = []
    start = 0
    count = 100

    while True:
        url = f"https://steamcommunity.com/market/search/render/"
        params = {
            'appid': appid,
            'norender': 1,
            'count': count,
            'start': start
        }

        response = requests.get(url, params=params)
        data = response.json()

        if not data.get('results'):
            break

        for item in data['results']:
            items.append({
                'market_hash_name': item['hash_name'],
                'name': item['name'],
                'image_url': item.get('asset_description', {}).get('icon_url'),
                # ... 其他字段
            })

        start += count
        time.sleep(2)  # 防止限流

    return items
```

#### 5.1.2 获取价格数据

```python
def fetch_steam_price(market_hash_name):
    """获取 Steam 价格"""
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {
        'appid': 730,
        'currency': 1,  # USD
        'market_hash_name': market_hash_name
    }

    response = requests.get(url, params=params)
    data = response.json()

    return {
        'price': float(data.get('lowest_price', '0').replace('$', '')),
        'volume': int(data.get('volume', '0').replace(',', '')),
        'median_price': float(data.get('median_price', '0').replace('$', ''))
    }
```

#### 5.1.3 获取价格历史

```python
def fetch_price_history(market_hash_name):
    """获取价格历史（需要解析 JS）"""
    url = f"https://steamcommunity.com/market/listings/730/{market_hash_name}"

    # 需要解析页面中的 JavaScript 变量
    # var line1=[[timestamp_ms, price, volume], ...]

    # 使用正则或 JS 解析器提取
```

### 5.2 Buff 采集

#### 5.2.1 接口分析

```python
# Buff 接口示例（可能需要逆向）
# https://buff.163.com/api/market/goods?game=csgo&page_num=1

def fetch_buff_items(page=1):
    """获取 Buff 饰品列表"""
    url = "https://buff.163.com/api/market/goods"
    params = {
        'game': 'csgo',
        'page_num': page,
        'page_size': 80
    }

    headers = {
        'User-Agent': 'Mozilla/5.0...',
        'Cookie': 'session=...'  # 可能需要登录
    }

    response = requests.get(url, params=params, headers=headers)
    return response.json()
```

#### 5.2.2 价格映射

```python
def match_buff_to_steam(buff_name):
    """
    Buff 和 Steam 的饰品名称可能不同
    需要建立映射关系
    """
    # 可以通过模糊匹配或手动维护映射表
    pass
```

### 5.3 任务调度

#### 5.3.1 使用 APScheduler

```python
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

# 每30分钟更新一次价格
@scheduler.scheduled_job('interval', minutes=30)
def update_prices():
    print("开始更新价格...")
    # 遍历所有饰品，更新价格
    items = db.query(Item).filter(Item.is_active == True).all()
    for item in items:
        # 采集 Steam 价格
        steam_price = fetch_steam_price(item.market_hash_name)
        save_price(item.id, 'steam', steam_price)
        time.sleep(2)

        # 采集 Buff 价格
        buff_price = fetch_buff_price(item.market_hash_name)
        save_price(item.id, 'buff', buff_price)
        time.sleep(2)

scheduler.start()
```

#### 5.3.2 使用 Cron

```bash
# crontab -e
# 每30分钟执行一次
*/30 * * * * cd /path/to/project && python scraper.py update-prices
```

### 5.4 错误处理与重试

```python
import time
from functools import wraps

def retry_on_error(max_retries=3, delay=5):
    """重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"错误: {e}, 重试 {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        time.sleep(delay * (2 ** attempt))  # 指数退避
                    else:
                        raise
        return wrapper
    return decorator

@retry_on_error(max_retries=3)
def fetch_with_retry(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()
```

---

## 6. 数据处理与分析

### 6.1 数据清洗

```python
def clean_price_data(raw_data):
    """数据清洗"""
    # 1. 过滤异常价格
    if raw_data['price'] <= 0 or raw_data['price'] > 100000:
        return None

    # 2. 标准化货币
    if raw_data['currency'] == 'USD':
        raw_data['price_cny'] = raw_data['price'] * 7.2

    # 3. 处理缺失值
    raw_data.setdefault('volume', 0)

    return raw_data
```

### 6.2 基础统计

```python
def calculate_price_change(item_id, platform, days=7):
    """计算涨跌幅"""
    now = datetime.now()
    past = now - timedelta(days=days)

    current_price = db.query(PriceHistory).filter(
        PriceHistory.item_id == item_id,
        PriceHistory.platform == platform
    ).order_by(PriceHistory.collected_at.desc()).first()

    past_price = db.query(PriceHistory).filter(
        PriceHistory.item_id == item_id,
        PriceHistory.platform == platform,
        PriceHistory.collected_at <= past
    ).order_by(PriceHistory.collected_at.desc()).first()

    if not current_price or not past_price:
        return None

    change_percent = ((current_price.price - past_price.price) / past_price.price) * 100
    return round(change_percent, 2)
```

### 6.3 套利检测

```python
def find_arbitrage_opportunities(min_profit_percent=10):
    """找出跨平台套利机会"""
    # 获取最新价格
    latest_prices = db.query(
        PriceHistory.item_id,
        PriceHistory.platform,
        PriceHistory.price
    ).filter(
        PriceHistory.collected_at >= datetime.now() - timedelta(hours=1)
    ).all()

    # 按 item_id 分组
    price_by_item = {}
    for record in latest_prices:
        if record.item_id not in price_by_item:
            price_by_item[record.item_id] = {}
        price_by_item[record.item_id][record.platform] = record.price

    # 计算价差
    opportunities = []
    for item_id, prices in price_by_item.items():
        if len(prices) < 2:
            continue

        min_price = min(prices.values())
        max_price = max(prices.values())
        profit_percent = ((max_price - min_price) / min_price) * 100

        if profit_percent >= min_profit_percent:
            opportunities.append({
                'item_id': item_id,
                'min_platform': min(prices, key=prices.get),
                'max_platform': max(prices, key=prices.get),
                'min_price': min_price,
                'max_price': max_price,
                'profit_percent': round(profit_percent, 2)
            })

    return opportunities
```

---

## 7. CLI 工具设计

### 7.1 使用 Click 框架

```python
import click

@click.group()
def cli():
    """CS 饰品数据采集系统 CLI"""
    pass

@cli.command()
@click.argument('item_name')
def price(item_name):
    """查询饰品当前价格"""
    item = db.query(Item).filter(Item.market_hash_name.like(f'%{item_name}%')).first()
    if not item:
        click.echo(f"未找到饰品: {item_name}")
        return

    prices = db.query(PriceHistory).filter(
        PriceHistory.item_id == item.id
    ).order_by(PriceHistory.collected_at.desc()).limit(5).all()

    for p in prices:
        click.echo(f"{p.platform}: {p.price} {p.currency} @ {p.collected_at}")

@cli.command()
@click.option('--days', default=30, help='历史天数')
@click.argument('item_name')
def history(item_name, days):
    """查询价格历史"""
    # 实现历史查询
    pass

@cli.command()
@click.option('--format', type=click.Choice(['csv', 'json']), default='csv')
@click.option('--output', help='输出文件路径')
def export(format, output):
    """导出数据"""
    # 实现数据导出
    pass

if __name__ == '__main__':
    cli()
```

### 7.2 使用示例

```bash
# 查询价格
python cli.py price "AK-47 | Redline"

# 查询历史
python cli.py history "AK-47 | Redline" --days 30

# 导出数据
python cli.py export --format csv --output prices.csv

# 查看统计
python cli.py stats

# 查找套利机会
python cli.py arbitrage --min-profit 15
```

---

## 8. 项目结构

```
cs-item-scraper/
├── config/
│   ├── config.yaml              # 配置文件
│   └── logging.yaml             # 日志配置
├── scrapers/
│   ├── __init__.py
│   ├── base.py                  # 爬虫基类
│   ├── steam_scraper.py         # Steam 爬虫
│   ├── buff_scraper.py          # Buff 爬虫
│   └── utils.py                 # 工具函数
├── models/
│   ├── __init__.py
│   ├── database.py              # 数据库连接
│   ├── item.py                  # Item 模型
│   ├── price_history.py         # PriceHistory 模型
│   └── config.py                # Config 模型
├── services/
│   ├── __init__.py
│   ├── data_processor.py        # 数据处理
│   ├── analyzer.py              # 数据分析
│   └── notifier.py              # 通知服务
├── cli/
│   ├── __init__.py
│   └── commands.py              # CLI 命令
├── scripts/
│   ├── init_db.py               # 初始化数据库
│   ├── full_sync.py             # 全量同步
│   └── update_prices.py         # 更新价格
├── tests/
│   └── test_scrapers.py
├── logs/                        # 日志目录
├── data/                        # 数据导出目录
├── requirements.txt
├── docker-compose.yml           # Docker 配置
├── README.md
└── main.py                      # 主入口
```

---

## 9. 实现步骤

### Step 1: 环境搭建 (1-2 天)

- [ ] 安装 Python 3.10+
- [ ] 创建虚拟环境
- [ ] 安装依赖包
- [ ] 配置 PostgreSQL（Docker）
- [ ] 设计并创建数据库表
- [ ] 测试数据库连接

```bash
# 创建项目
mkdir cs-item-scraper && cd cs-item-scraper
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install requests beautifulsoup4 lxml sqlalchemy psycopg2-binary \
    pandas click apscheduler loguru python-dotenv

# 启动数据库
docker-compose up -d postgres
```

### Step 2: 数据采集器开发 (3-5 天)

- [ ] 实现 Steam 饰品列表获取
- [ ] 实现 Steam 价格采集
- [ ] 存储到数据库
- [ ] 添加错误处理和重试
- [ ] 添加日志记录
- [ ] 测试采集功能

```python
# 测试采集
python scripts/full_sync.py --platform steam --limit 100
```

### Step 3: 定时任务 (1-2 天)

- [ ] 实现定时价格更新
- [ ] 配置调度器
- [ ] 添加任务监控
- [ ] 测试定时任务

```python
# 启动定时任务
python main.py scheduler
```

### Step 4: Buff 数据源 (2-3 天)

- [ ] 分析 Buff API/网站
- [ ] 实现 Buff 爬虫
- [ ] 饰品名称映射
- [ ] 集成到系统

### Step 5: CLI 工具 (2-3 天)

- [ ] 实现价格查询命令
- [ ] 实现历史查询命令
- [ ] 实现数据导出
- [ ] 实现统计分析
- [ ] 添加帮助文档

### Step 6: 数据分析 (2-3 天)

- [ ] 实现涨跌幅计算
- [ ] 实现套利检测
- [ ] 实现异动监测
- [ ] 添加通知功能（可选）

### Step 7: 优化与完善 (持续)

- [ ] 性能优化（批量插入、索引优化）
- [ ] 错误处理完善
- [ ] 日志系统优化
- [ ] 数据备份机制
- [ ] 文档完善

**总预计时间**: 2-3 周（业余时间）

---

## 10. 关键技术难点

### 10.1 Steam API 限流

**问题**: Steam Market API 有严格的请求限制
**解决方案**:
- 请求间隔控制（2-3 秒）
- 使用多个 IP（代理池）
- 错误时指数退避
- 保存 cookies 维持会话

### 10.2 Buff 数据获取

**问题**: Buff 可能没有公开 API
**解决方案**:
- 浏览器开发者工具分析接口
- 模拟浏览器请求（headers, cookies）
- 使用 Selenium/Playwright（最后手段）
- 或直接使用 SteamDT 开放 API

### 10.3 饰品名称映射

**问题**: 不同平台饰品命名不一致
**解决方案**:
- 使用 market_hash_name 作为主键
- 建立中英文对照表
- 模糊匹配算法（difflib）
- 手动维护特殊映射

### 10.4 海量数据存储

**问题**: 价格历史数据量大（数千饰品 × 每小时 × 多平台）
**解决方案**:
- 使用 TimescaleDB 时序数据库扩展
- 定期聚合旧数据（hourly → daily）
- 数据分区存储
- 合理使用索引

### 10.5 数据准确性

**问题**: 数据采集可能出错或缺失
**解决方案**:
- 价格异常检测（统计学方法）
- 多源数据交叉验证
- 保存原始响应（用于调试）
- 人工抽查机制

---

## 11. 配置文件示例

### 11.1 config.yaml

```yaml
database:
  host: localhost
  port: 5432
  name: cs_items
  user: postgres
  password: your_password

scrapers:
  steam:
    enabled: true
    rate_limit: 30  # 每分钟请求数
    delay_ms: 2000  # 请求间隔
    timeout: 10

  buff:
    enabled: true
    rate_limit: 20
    delay_ms: 3000
    cookies: ""  # 登录后的 cookies

scheduler:
  full_sync_cron: "0 2 * * *"      # 每天凌晨2点全量同步
  price_update_interval: 30        # 每30分钟更新价格

logging:
  level: INFO
  file: logs/scraper.log

notification:
  enabled: false
  telegram_bot_token: ""
  telegram_chat_id: ""
```

### 11.2 requirements.txt

```
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
pandas==2.1.4
numpy==1.26.2
click==8.1.7
apscheduler==3.10.4
loguru==0.7.2
python-dotenv==1.0.0
pyyaml==6.0.1
```

---

## 12. Docker 部署

### 12.1 docker-compose.yml

```yaml
version: '3.8'

services:
  postgres:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_DB: cs_items
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: your_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  scraper:
    build: .
    depends_on:
      - postgres
    environment:
      - DATABASE_URL=postgresql://postgres:your_password@postgres:5432/cs_items
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./config:/app/config
    command: python main.py scheduler
    restart: unless-stopped

volumes:
  postgres_data:
```

### 12.2 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

---

## 13. 监控与日志

### 13.1 日志记录

```python
from loguru import logger

# 配置日志
logger.add(
    "logs/scraper_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO"
)

# 使用
logger.info("开始采集 Steam 数据")
logger.error(f"采集失败: {error}")
```

### 13.2 采集监控

```python
# 定期检查采集状态
def check_scraper_health():
    """检查采集器健康状态"""
    last_log = db.query(ScraperLog).order_by(
        ScraperLog.started_at.desc()
    ).first()

    if not last_log:
        return "未运行"

    time_since_last = datetime.now() - last_log.started_at
    if time_since_last > timedelta(hours=2):
        return "可能卡住"

    if last_log.status == 'failed':
        return f"失败: {last_log.error_message}"

    return "正常"
```

---

## 14. 数据采集接口汇总

### 14.1 Steam 接口

```
1. 搜索饰品列表
GET https://steamcommunity.com/market/search/render/
  ?appid=730
  &norender=1
  &count=100
  &start=0

2. 获取价格概览
GET https://steamcommunity.com/market/priceoverview/
  ?appid=730
  &currency=1
  &market_hash_name=AK-47%20%7C%20Redline%20(Field-Tested)

3. 获取价格历史（需解析页面）
GET https://steamcommunity.com/market/listings/730/{item_name}
```

### 14.2 SteamDT 开放平台

```
Base URL: https://open.steamdt.com/open/cs2/v1

1. 获取饰品基础信息
GET /base

2. 批量查询价格
POST /prices

3. 7天均价
GET /avgprices?days=7

需要 API Key: Bearer {YOUR_API_KEY}
```

---

## 15. 未来扩展

### 15.1 数据层面
- [ ] 支持更多平台（UU898、IGXE）
- [ ] 采集 Dota2、TF2 饰品
- [ ] 采集箱子开箱概率数据
- [ ] 采集玩家库存数据

### 15.2 分析层面
- [ ] 机器学习价格预测
- [ ] 市场趋势预测
- [ ] 热度指数计算
- [ ] 投资组合优化建议

### 15.3 工具层面
- [ ] 开发简单 Web 界面（可选）
- [ ] Grafana 可视化面板
- [ ] Telegram Bot 交互
- [ ] 数据 API 服务

---

## 附录

### A. 参考资料

- [Steam Web API 文档](https://developer.valvesoftware.com/wiki/Steam_Web_API)
- [SteamDT 开放平台](https://doc.steamdt.com/)
- [TimescaleDB 文档](https://docs.timescale.com/)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [APScheduler 文档](https://apscheduler.readthedocs.io/)

### B. 开发检查清单

**初始化阶段**
- [ ] 创建项目目录结构
- [ ] 初始化 Git 仓库
- [ ] 配置虚拟环境
- [ ] 安装依赖包
- [ ] 配置数据库

**开发阶段**
- [ ] 实现 Steam 爬虫
- [ ] 实现数据存储
- [ ] 实现定时任务
- [ ] 实现 CLI 工具
- [ ] 编写单元测试

**部署阶段**
- [ ] 配置 Docker
- [ ] 测试完整流程
- [ ] 配置日志监控
- [ ] 设置数据备份
- [ ] 编写运维文档

---

**文档版本**: v2.0 (后端专注版)
**创建日期**: 2025-12-02
**最后更新**: 2025-12-02
**适用范围**: 个人使用，数据采集与存储
