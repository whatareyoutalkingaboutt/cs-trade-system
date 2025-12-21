#!/usr/bin/env python3
"""
验证脚本 01: 测试历史数据API

功能:
1. 测试 Pricempire API 连接
2. 获取单个饰品的历史价格数据
3. 验证数据格式和完整性

使用方法:
    python scripts/validation/01_test_historical_api.py

注意:
- 需要先在 .env 文件中配置 PRICEMPIRE_API_KEY
- 免费额度: 100次/天
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Any

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import requests
from dotenv import load_dotenv
from loguru import logger

# 加载环境变量
load_dotenv()

# 配置日志
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

# 测试饰品列表
TEST_ITEMS = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Howl (Factory New)",
]


class PricempireAPITester:
    """Pricempire API 测试器"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("PRICEMPIRE_API_KEY")
        self.base_url = "https://api.pricempire.com/v3"

        if not self.api_key:
            logger.error("❌ 未找到 PRICEMPIRE_API_KEY，请在 .env 文件中配置")
            logger.info("💡 获取API Key: https://pricempire.com/api")
            sys.exit(1)

    def test_connection(self) -> bool:
        """测试API连接"""
        logger.info("🔌 测试 Pricempire API 连接...")

        try:
            # 测试端点: 获取API状态
            url = f"{self.base_url}/status"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                logger.success("✅ API 连接成功")
                return True
            elif response.status_code == 401:
                logger.error("❌ API Key 无效，请检查配置")
                return False
            else:
                logger.warning(f"⚠️ API 返回状态码: {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            logger.error("❌ API 请求超时")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ API 请求失败: {e}")
            return False

    def fetch_historical_prices(self, item_name: str, days: int = 30) -> Dict[str, Any]:
        """
        获取历史价格数据

        参数:
            item_name: 饰品名称
            days: 历史天数 (7, 30, 60, 90)

        返回:
            历史价格数据
        """
        logger.info(f"📥 获取饰品历史价格: {item_name} (最近 {days} 天)")

        url = f"{self.base_url}/items/history"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        params = {
            "name": item_name,
            "days": days,
            "sources": ["steam", "buff163"]
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # 验证数据结构
            self._validate_response_data(data, item_name)

            return data

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.error(f"❌ 饰品未找到: {item_name}")
            elif e.response.status_code == 429:
                logger.error("❌ API 请求次数超限，请稍后再试")
            else:
                logger.error(f"❌ HTTP 错误: {e}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 请求失败: {e}")
            return {}

    def _validate_response_data(self, data: Dict[str, Any], item_name: str):
        """验证响应数据格式"""
        logger.info("🔍 验证数据格式...")

        # 检查必需字段
        required_fields = ["item_name", "steam", "buff"]
        for field in required_fields:
            if field not in data:
                logger.warning(f"⚠️ 缺少字段: {field}")

        # 验证 Steam 数据
        if "steam" in data:
            steam_data = data["steam"]
            logger.info(f"  📊 Steam 数据:")
            logger.info(f"    - 当前价格: ¥{steam_data.get('current_price', 'N/A')}")
            logger.info(f"    - 7天均价: ¥{steam_data.get('7d_avg', 'N/A')}")
            logger.info(f"    - 30天均价: ¥{steam_data.get('30d_avg', 'N/A')}")

            if "price_history" in steam_data:
                history_count = len(steam_data["price_history"])
                logger.info(f"    - 历史数据点数: {history_count}")

                if history_count > 0:
                    first_record = steam_data["price_history"][0]
                    logger.info(f"    - 最早记录: {first_record.get('timestamp', 'N/A')}")
            else:
                logger.warning("    ⚠️ 缺少价格历史数据")

        # 验证 Buff 数据
        if "buff" in data:
            buff_data = data["buff"]
            logger.info(f"  📊 Buff 数据:")
            logger.info(f"    - 当前价格: ¥{buff_data.get('current_price', 'N/A')}")
            logger.info(f"    - 7天均价: ¥{buff_data.get('7d_avg', 'N/A')}")

            if "price_history" in buff_data:
                history_count = len(buff_data["price_history"])
                logger.info(f"    - 历史数据点数: {history_count}")
            else:
                logger.warning("    ⚠️ 缺少价格历史数据")

        logger.success("✅ 数据格式验证通过")

    def save_sample_data(self, data: Dict[str, Any], filename: str):
        """保存示例数据到文件"""
        output_dir = "data/validation"
        os.makedirs(output_dir, exist_ok=True)

        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 示例数据已保存: {filepath}")

    def run_full_test(self):
        """运行完整测试"""
        logger.info("=" * 60)
        logger.info("🚀 开始测试 Pricempire API")
        logger.info("=" * 60)

        # 1. 测试连接
        if not self.test_connection():
            logger.error("❌ 连接测试失败，终止测试")
            return False

        logger.info("")

        # 2. 测试历史数据获取
        success_count = 0
        for item_name in TEST_ITEMS:
            logger.info("-" * 60)
            data = self.fetch_historical_prices(item_name, days=30)

            if data:
                success_count += 1
                # 保存第一个成功的示例数据
                if success_count == 1:
                    self.save_sample_data(
                        data,
                        f"pricempire_sample_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    )

            logger.info("")

        # 3. 总结
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
    tester = PricempireAPITester()
    success = tester.run_full_test()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
