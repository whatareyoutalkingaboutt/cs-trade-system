#!/usr/bin/env python3
"""
验证饰品名称是否正确
从 test_items.json 中抽取一些饰品，测试能否获取到 Steam 价格
"""

import os
import sys
import json
import time
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import requests
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

# 加载测试饰品列表
with open('data/test_items.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
    items = data['items']

# 随机抽取10个饰品测试
test_items = random.sample(items, min(10, len(items)))

# Steam API
BASE_URL = "https://steamcommunity.com/market/priceoverview/"
proxies = {
    'http': 'http://127.0.0.1:33210',
    'https': 'http://127.0.0.1:33210'
}

logger.info("=" * 60)
logger.info("🧪 验证饰品名称正确性（抽取10个）")
logger.info("=" * 60)

success_count = 0
failed_items = []

for item in test_items:
    logger.info(f"\n测试: {item['name']} ({item['name_en']})")
    logger.info(f"  优先级: {item['priority']} | 预估价格: ¥{item['estimated_price_range']}")

    # 使用英文名称请求
    params = {
        'appid': 730,
        'currency': 23,  # CNY
        'market_hash_name': item['name_en']
    }

    try:
        response = requests.get(
            BASE_URL,
            params=params,
            proxies=proxies,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                logger.success(f"  ✅ 成功 | 最低价: {data.get('lowest_price', 'N/A')} | 交易量: {data.get('volume', 'N/A')}")
                success_count += 1
            else:
                logger.error(f"  ❌ API返回失败: {data}")
                failed_items.append(item['name_en'])
        else:
            logger.error(f"  ❌ HTTP {response.status_code}")
            failed_items.append(item['name_en'])

    except Exception as e:
        logger.error(f"  ❌ 请求异常: {e}")
        failed_items.append(item['name_en'])

    time.sleep(2)  # 限流

logger.info("\n" + "=" * 60)
logger.info("📊 验证结果")
logger.info("=" * 60)
logger.info(f"  成功: {success_count}/{len(test_items)}")
logger.info(f"  成功率: {success_count/len(test_items)*100:.1f}%")

if failed_items:
    logger.warning(f"\n失败的饰品:")
    for name in failed_items:
        logger.warning(f"  - {name}")
else:
    logger.success("\n✅ 所有饰品名称都正确！")
