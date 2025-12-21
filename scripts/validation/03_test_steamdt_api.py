#!/usr/bin/env python3
"""
验证脚本 03: 测试 SteamDT API

功能:
1. 测试 SteamDT API 连接（5个Key轮换）
2. 探索可用的 API 端点
3. 测试获取多平台价格（Steam/Buff/悠悠有品）
4. 测试获取历史数据
5. 验证数据格式和完整性

使用方法:
    python scripts/validation/03_test_steamdt_api.py

注意:
- 需要在 .env 文件中配置 STEAMDT_API_KEYS
- 支持多个 API Key 轮换
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

# 测试饰品列表
TEST_ITEMS = [
    "AK-47 | 二西莫夫 (久经沙场)",
    "AWP | 二西莫夫 (久经沙场)",
    "AK-47 | Redline (Field-Tested)",
]


class SteamDTAPITester:
    """SteamDT API 测试器"""

    # 可能的 API Base URLs
    POSSIBLE_BASE_URLS = [
        "https://api.steamdt.com",
        "https://open.steamdt.com",
        "https://steamdt.com/api",
    ]

    # 可能的端点路径
    POSSIBLE_ENDPOINTS = {
        "prices": ["/v1/prices", "/api/v1/prices", "/open/cs2/v1/prices", "/prices"],
        "history": ["/v1/history", "/api/v1/history", "/open/cs2/v1/history", "/history"],
        "item": ["/v1/item", "/api/v1/item", "/open/cs2/v1/item", "/item"],
        "search": ["/v1/search", "/api/v1/search", "/open/cs2/v1/search", "/search"],
    }

    def __init__(self, api_keys: List[str] = None):
        # 从环境变量加载 API Keys
        if api_keys:
            self.api_keys = api_keys
        else:
            keys_str = os.getenv("STEAMDT_API_KEYS", "")
            if keys_str:
                self.api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
            else:
                # 尝试单个 key
                single_key = os.getenv("STEAMDT_API_KEY_1")
                if single_key:
                    self.api_keys = [single_key]
                else:
                    self.api_keys = []

        if not self.api_keys:
            logger.error("❌ 未找到 STEAMDT API Keys")
            logger.info("💡 请在 .env 文件中配置 STEAMDT_API_KEYS 或 STEAMDT_API_KEY_1")
            sys.exit(1)

        logger.info(f"✅ 加载了 {len(self.api_keys)} 个 API Keys")
        self.current_key_index = 0
        self.session = requests.Session()

    def _rotate_key(self) -> str:
        """轮换 API Key"""
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    def _make_request(self, url: str, params: Dict = None, method: str = "GET") -> Optional[Dict]:
        """发送 API 请求"""
        api_key = self._rotate_key()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        try:
            if method == "GET":
                response = self.session.get(url, headers=headers, params=params, timeout=15)
            else:
                response = self.session.post(url, headers=headers, json=params, timeout=15)

            logger.debug(f"请求: {url}")
            logger.debug(f"状态码: {response.status_code}")

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"API 返回状态码: {response.status_code}")
                logger.debug(f"响应内容: {response.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            logger.error(f"请求超时: {url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return None
        except json.JSONDecodeError:
            logger.error(f"JSON 解析失败")
            return None

    def explore_api_endpoints(self):
        """探索 API 端点"""
        logger.info("=" * 60)
        logger.info("🔍 探索 SteamDT API 端点")
        logger.info("=" * 60)

        test_item = TEST_ITEMS[0]
        working_endpoints = {}

        for endpoint_type, paths in self.POSSIBLE_ENDPOINTS.items():
            logger.info(f"\n📌 测试 {endpoint_type} 端点...")

            for base_url in self.POSSIBLE_BASE_URLS:
                for path in paths:
                    full_url = f"{base_url}{path}"

                    # 尝试不同的参数格式
                    param_variants = [
                        {"name": test_item},
                        {"item": test_item},
                        {"item_name": test_item},
                        {"market_hash_name": test_item},
                        {},  # 无参数
                    ]

                    for params in param_variants:
                        logger.debug(f"  尝试: {full_url} | 参数: {params}")
                        data = self._make_request(full_url, params)

                        if data:
                            logger.success(f"  ✅ 找到可用端点: {full_url}")
                            logger.info(f"     参数格式: {params}")
                            logger.info(f"     响应示例: {json.dumps(data, ensure_ascii=False)[:200]}...")

                            working_endpoints[endpoint_type] = {
                                "url": full_url,
                                "params": params,
                                "sample_response": data
                            }
                            break

                    if endpoint_type in working_endpoints:
                        break

                if endpoint_type in working_endpoints:
                    break

        logger.info("\n" + "=" * 60)
        logger.info("📊 探索结果总结")
        logger.info("=" * 60)
        logger.info(f"找到可用端点: {len(working_endpoints)}/{len(self.POSSIBLE_ENDPOINTS)}")

        for endpoint_type, info in working_endpoints.items():
            logger.success(f"✅ {endpoint_type}: {info['url']}")

        return working_endpoints

    def test_multi_platform_prices(self, item_name: str):
        """测试多平台价格获取"""
        logger.info("=" * 60)
        logger.info(f"📊 测试多平台价格: {item_name}")
        logger.info("=" * 60)

        # 尝试几个常见的价格查询端点
        attempts = [
            {
                "url": "https://open.steamdt.com/open/cs2/v1/prices",
                "params": {"name": item_name},
            },
            {
                "url": "https://api.steamdt.com/v1/prices",
                "params": {"item": item_name},
            },
            {
                "url": "https://steamdt.com/api/prices",
                "params": {"item_name": item_name},
            },
        ]

        for attempt in attempts:
            logger.info(f"\n尝试端点: {attempt['url']}")
            data = self._make_request(attempt['url'], attempt['params'])

            if data:
                logger.success("✅ 获取成功！")
                self._analyze_price_data(data, item_name)
                return data

        logger.error("❌ 所有端点都失败了")
        return None

    def _analyze_price_data(self, data: Dict, item_name: str):
        """分析价格数据"""
        logger.info("\n🔍 数据分析:")
        logger.info(f"  响应结构: {list(data.keys())}")

        # 尝试提取价格信息
        price_fields = ["steam", "buff", "youpin", "steam_price", "buff_price", "youpin_price", "price", "prices"]

        for field in price_fields:
            if field in data:
                logger.info(f"  {field}: {data[field]}")

        # 保存完整响应
        self._save_sample_data(data, f"steamdt_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    def test_key_rotation(self):
        """测试 API Key 轮换"""
        logger.info("=" * 60)
        logger.info(f"🔄 测试 API Key 轮换（{len(self.api_keys)} 个 Keys）")
        logger.info("=" * 60)

        test_url = "https://open.steamdt.com/open/cs2/v1/prices"
        test_params = {"name": TEST_ITEMS[0]}

        for i in range(min(5, len(self.api_keys) * 2)):
            logger.info(f"\n第 {i+1} 次请求:")
            current_key = self.api_keys[self.current_key_index]
            logger.info(f"  使用 Key: {current_key[:10]}...{current_key[-5:]}")

            data = self._make_request(test_url, test_params)

            if data:
                logger.success(f"  ✅ 请求成功")
            else:
                logger.error(f"  ❌ 请求失败")

            time.sleep(1)

    def _save_sample_data(self, data: Dict, filename: str):
        """保存示例数据"""
        output_dir = "data/validation"
        os.makedirs(output_dir, exist_ok=True)

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 数据已保存: {filepath}")

    def run_full_test(self):
        """运行完整测试"""
        logger.info("=" * 60)
        logger.info("🚀 开始测试 SteamDT API")
        logger.info("=" * 60)
        logger.info("")

        # 1. 探索 API 端点
        working_endpoints = self.explore_api_endpoints()
        logger.info("")

        # 2. 测试 Key 轮换
        if len(self.api_keys) > 1:
            self.test_key_rotation()
            logger.info("")

        # 3. 测试多平台价格获取
        for item in TEST_ITEMS[:2]:  # 只测试前2个
            self.test_multi_platform_prices(item)
            logger.info("")
            time.sleep(2)  # 限流

        # 4. 总结
        logger.info("=" * 60)
        logger.info("📊 测试总结")
        logger.info("=" * 60)
        logger.info(f"  API Keys 数量: {len(self.api_keys)}")
        logger.info(f"  发现可用端点: {len(working_endpoints)}")

        if working_endpoints:
            logger.success("✅ 测试完成！API 可用")
            logger.info("\n💡 建议:")
            logger.info("  - 查看 data/validation/ 目录下的示例数据")
            logger.info("  - 根据响应格式调整数据采集代码")
            return True
        else:
            logger.error("❌ 未找到可用的 API 端点")
            logger.info("\n💡 下一步:")
            logger.info("  1. 检查 API Keys 是否有效")
            logger.info("  2. 查看 Apifox 文档确认正确的端点")
            logger.info("  3. 联系 SteamDT 客服")
            return False


def main():
    """主函数"""
    tester = SteamDTAPITester()
    success = tester.run_full_test()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
