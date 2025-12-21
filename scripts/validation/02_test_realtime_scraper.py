#!/usr/bin/env python3
"""
验证脚本 02: 测试实时数据采集

功能:
1. 测试 Steam Market API 连接
2. 测试 SteamDT API (Buff数据) 连接
3. 采集实时价格数据
4. 验证数据格式和完整性

使用方法:
    python scripts/validation/02_test_realtime_scraper.py

注意:
- Steam API 无需认证，但有限流
- SteamDT API 需要在 .env 中配置 STEAMDT_API_KEY
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

# 测试饰品列表
TEST_ITEMS = [
    {
        "name": "AK-47 | Redline (Field-Tested)",
        "steam_name": "AK-47 | Redline (Field-Tested)"
    },
    {
        "name": "AWP | Asiimov (Field-Tested)",
        "steam_name": "AWP | Asiimov (Field-Tested)"
    },
    {
        "name": "Glock-18 | Water Elemental (Field-Tested)",
        "steam_name": "Glock-18 | Water Elemental (Field-Tested)"
    },
]


class SteamMarketScraper:
    """Steam Market 爬虫"""

    BASE_URL = "https://steamcommunity.com/market"
    APP_ID = 730  # CS2/CSGO

    def __init__(self, use_proxy: bool = True):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        # 配置代理
        if use_proxy:
            proxies = {
                'http': 'http://127.0.0.1:33210',
                'https': 'http://127.0.0.1:33210'
            }
            self.session.proxies.update(proxies)
            logger.info("✅ 已启用代理: http://127.0.0.1:33210")

    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        """
        获取Steam市场价格

        参数:
            item_name: 饰品名称

        返回:
            价格数据 或 None
        """
        logger.info(f"🎮 [Steam] 获取价格: {item_name}")

        url = f"{self.BASE_URL}/priceoverview/"
        params = {
            'appid': self.APP_ID,
            'currency': 23,  # CNY
            'market_hash_name': item_name
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data.get('success'):
                price_data = {
                    'platform': 'steam',
                    'item_name': item_name,
                    'lowest_price': data.get('lowest_price', 'N/A'),
                    'median_price': data.get('median_price', 'N/A'),
                    'volume': data.get('volume', 'N/A'),
                    'timestamp': datetime.now().isoformat()
                }

                logger.success(f"  ✅ 最低价: {price_data['lowest_price']}")
                logger.info(f"     中位价: {price_data['median_price']}")
                logger.info(f"     交易量: {price_data['volume']}")

                return price_data
            else:
                logger.error(f"  ❌ API 返回失败: {data}")
                return None

        except requests.exceptions.Timeout:
            logger.error(f"  ❌ 请求超时")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"  ❌ 请求失败: {e}")
            return None


class SteamDTScraper:
    """SteamDT API 爬虫 (获取Buff价格)"""

    BASE_URL = "https://open.steamdt.com/open/cs2/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("STEAMDT_API_KEY")
        self.session = requests.Session()

        if self.api_key:
            self.session.headers.update({
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            })
        else:
            logger.warning("⚠️ 未配置 STEAMDT_API_KEY，将跳过 Buff 数据测试")

    def test_connection(self) -> bool:
        """测试API连接"""
        if not self.api_key:
            return False

        logger.info("🔌 测试 SteamDT API 连接...")

        try:
            # 测试端点: 获取价格列表
            url = f"{self.BASE_URL}/prices"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                logger.success("✅ SteamDT API 连接成功")
                return True
            elif response.status_code == 401:
                logger.error("❌ API Key 无效")
                return False
            else:
                logger.warning(f"⚠️ API 返回状态码: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            return False

    def get_buff_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        """
        获取Buff价格 (通过SteamDT API)

        参数:
            item_name: 饰品名称

        返回:
            价格数据 或 None
        """
        if not self.api_key:
            return None

        logger.info(f"🎲 [Buff] 获取价格: {item_name}")

        try:
            url = f"{self.BASE_URL}/prices"
            params = {'name': item_name}

            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data.get('code') == 0 and 'data' in data:
                item_data = data['data'].get(item_name, {})

                price_data = {
                    'platform': 'buff',
                    'item_name': item_name,
                    'buff_price': item_data.get('buff_price', 'N/A'),
                    'steam_price': item_data.get('steam_price', 'N/A'),
                    'volume': item_data.get('volume', 'N/A'),
                    'timestamp': datetime.now().isoformat()
                }

                logger.success(f"  ✅ Buff价格: ¥{price_data['buff_price']}")
                logger.info(f"     Steam价格: ¥{price_data['steam_price']}")
                logger.info(f"     交易量: {price_data['volume']}")

                return price_data
            else:
                logger.warning(f"  ⚠️ 未找到该饰品数据")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"  ❌ 请求失败: {e}")
            return None


class RealtimeScraperTester:
    """实时数据采集测试器"""

    def __init__(self):
        self.steam_scraper = SteamMarketScraper()
        self.steamdt_scraper = SteamDTScraper()
        self.results = []

    def test_single_item(self, item: Dict[str, str]) -> Dict[str, Any]:
        """测试单个饰品的数据采集"""
        logger.info("-" * 60)
        logger.info(f"📦 测试饰品: {item['name']}")
        logger.info("-" * 60)

        result = {
            'item_name': item['name'],
            'steam_data': None,
            'buff_data': None,
            'timestamp': datetime.now().isoformat()
        }

        # 1. 获取Steam价格
        steam_data = self.steam_scraper.get_price(item['steam_name'])
        result['steam_data'] = steam_data

        # 限流: 等待2-3秒
        logger.info("⏳ 等待 2 秒...")
        time.sleep(2)

        # 2. 获取Buff价格
        buff_data = None
        if self.steamdt_scraper.api_key:
            buff_data = self.steamdt_scraper.get_buff_price(item['name'])
            result['buff_data'] = buff_data
        else:
            logger.info("⏭️ 跳过 Buff 数据获取 (未配置 API Key)")

        # 3. 计算价差
        if steam_data and buff_data:
            try:
                # 解析价格字符串 (如 "¥35.50")
                steam_price = float(steam_data['lowest_price'].replace('¥', '').replace(',', ''))
                buff_price = float(buff_data['buff_price'])

                price_diff = steam_price - buff_price
                price_diff_percent = (price_diff / buff_price) * 100

                logger.info("")
                logger.info(f"💰 价差分析:")
                logger.info(f"   Steam: ¥{steam_price:.2f}")
                logger.info(f"   Buff:  ¥{buff_price:.2f}")
                logger.info(f"   价差:  ¥{price_diff:.2f} ({price_diff_percent:+.2f}%)")

                result['price_diff'] = price_diff
                result['price_diff_percent'] = price_diff_percent

            except (ValueError, KeyError) as e:
                logger.warning(f"⚠️ 价差计算失败: {e}")

        self.results.append(result)
        return result

    def save_results(self):
        """保存测试结果"""
        output_dir = "data/validation"
        os.makedirs(output_dir, exist_ok=True)

        filename = f"realtime_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 测试结果已保存: {filepath}")

    def run_full_test(self):
        """运行完整测试"""
        logger.info("=" * 60)
        logger.info("🚀 开始测试实时数据采集")
        logger.info("=" * 60)
        logger.info("")

        # 1. 测试SteamDT API连接
        if self.steamdt_scraper.api_key:
            self.steamdt_scraper.test_connection()
            logger.info("")

        # 2. 测试各个饰品
        success_count = 0
        for item in TEST_ITEMS:
            result = self.test_single_item(item)

            if result['steam_data']:
                success_count += 1

            logger.info("")

        # 3. 保存结果
        self.save_results()

        # 4. 总结
        logger.info("=" * 60)
        logger.info("📊 测试总结")
        logger.info("=" * 60)
        logger.info(f"  测试饰品数量: {len(TEST_ITEMS)}")
        logger.info(f"  成功获取数据: {success_count}")
        logger.info(f"  成功率: {success_count / len(TEST_ITEMS) * 100:.1f}%")

        if success_count == len(TEST_ITEMS):
            logger.success("✅ 所有测试通过！")
            return True
        elif success_count > 0:
            logger.warning("⚠️ 部分测试失败")
            return False
        else:
            logger.error("❌ 所有测试失败")
            return False


def main():
    """主函数"""
    tester = RealtimeScraperTester()
    success = tester.run_full_test()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
