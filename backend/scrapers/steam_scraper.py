#!/usr/bin/env python3
"""
Steam Market 爬虫

Steam社区市场的官方API,提供实时价格数据。

特点:
- 免费,无需API Key
- 数据准确,官方来源
- 但有严格的限流控制,需要合理控制请求频率

限制:
- 需要通过VPN/代理访问(国内IP可能被限制)
- 限流: 建议 2-3秒/请求
- 无官方文档,API可能随时变更
"""

import os
from typing import Dict, Any, Optional
from datetime import datetime

import requests
from loguru import logger

from .base_scraper import BaseScraper, rate_limit, retry, parse_price_string


class SteamMarketScraper(BaseScraper):
    """
    Steam Market 爬虫

    通过Steam社区市场API获取实时价格数据。

    注意:
    - 需要VPN/代理访问
    - 严格限流(2-3秒/请求)
    - 可能随时被Steam修改或限制
    """

    BASE_URL = "https://steamcommunity.com/market"
    APP_ID = 730  # CS2/CSGO的App ID

    def __init__(
        self,
        use_proxy: bool = True,
        proxy_url: Optional[str] = None,
        timeout: int = 10,
        rate_limit_seconds: float = 2.5
    ):
        """
        初始化Steam爬虫

        参数:
            use_proxy: 是否使用代理(国内访问建议开启)
            proxy_url: 代理URL(默认从环境变量 STEAM_PROXY_URL 读取,或使用 http://127.0.0.1:33210)
            timeout: 请求超时时间(秒)
            rate_limit_seconds: 限流时间间隔(秒),默认2.5秒(避免被Steam限制)
        """
        # 获取代理配置
        if proxy_url is None:
            proxy_url = os.getenv("STEAM_PROXY_URL", "http://127.0.0.1:33210")

        super().__init__(
            platform_name='steam',
            use_proxy=use_proxy,
            proxy_url=proxy_url,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds
        )

        # Steam特定配置
        self.app_id = self.APP_ID

        # 更新请求头(模拟浏览器)
        self.session.headers.update({
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://steamcommunity.com/market/'
        })

    @retry(max_attempts=3, delay=2.0, backoff=2.0)
    @rate_limit(2.5)  # 每2.5秒最多1次请求
    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        """
        获取Steam Market价格

        参数:
            item_name: 饰品名称(英文,必须与Steam市场中的名称完全一致)

        返回:
            价格数据字典,格式为:
            {
                'platform': 'steam',
                'item_name': str,
                'lowest_price': float,      # 最低售价(CNY)
                'median_price': float,      # 中位价(CNY)
                'volume': int,              # 24小时交易量
                'timestamp': str,           # ISO格式时间戳
                'currency': 'CNY'
            }
            如果获取失败,返回 None
        """
        logger.info(f"🎮 [Steam] 获取价格: {item_name}")

        try:
            # API端点
            url = f"{self.BASE_URL}/priceoverview/"
            params = {
                'appid': self.app_id,
                'currency': 23,  # 23 = CNY (人民币)
                'market_hash_name': item_name
            }

            # 发送请求
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            # 解析响应
            data = response.json()

            # 检查响应状态
            if not data.get('success'):
                logger.warning(f"  ⚠️ [Steam] API返回失败: {data}")
                self._update_stats(success=False)
                return None

            # 解析价格
            lowest_price_str = data.get('lowest_price', 'N/A')
            median_price_str = data.get('median_price', 'N/A')
            volume_str = data.get('volume', 'N/A')

            # 转换为数值
            lowest_price = parse_price_string(lowest_price_str)
            median_price = parse_price_string(median_price_str)

            # 交易量可能包含逗号(如 "1,234")
            volume = None
            if volume_str != 'N/A':
                try:
                    volume = int(str(volume_str).replace(',', ''))
                except (ValueError, AttributeError):
                    volume = None

            # 构建返回数据
            price_data = {
                'platform': 'steam',
                'item_name': item_name,
                'lowest_price': lowest_price,
                'median_price': median_price,
                'volume': volume,
                'timestamp': datetime.now().isoformat(),
                'currency': 'CNY'
            }

            # 日志
            if lowest_price:
                logger.success(f"  ✅ [Steam] 最低价: ¥{lowest_price:.2f}")
            else:
                logger.success(f"  ✅ [Steam] 最低价: N/A")

            if median_price:
                logger.info(f"     中位价: ¥{median_price:.2f}")
            if volume:
                logger.info(f"     交易量: {volume}")

            self._update_stats(success=True)
            return price_data

        except requests.exceptions.Timeout:
            logger.error(f"  ❌ [Steam] 请求超时")
            logger.info(f"     提示: 如果频繁超时,请检查VPN/代理是否正常")
            self._update_stats(success=False)
            return None

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error(f"  ❌ [Steam] 429 Too Many Requests - 请求过于频繁")
                logger.info(f"     提示: 增加限流时间间隔(当前: {self.rate_limit_seconds}秒)")
            else:
                logger.error(f"  ❌ [Steam] HTTP错误: {e.response.status_code}")

            self._update_stats(success=False)
            return None

        except requests.exceptions.ProxyError:
            logger.error(f"  ❌ [Steam] 代理连接失败")
            logger.info(f"     提示: 请检查VPN/代理是否正常运行")
            self._update_stats(success=False)
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"  ❌ [Steam] 请求失败: {e}")
            self._update_stats(success=False)
            return None

        except Exception as e:
            logger.error(f"  ❌ [Steam] 未知错误: {e}")
            self._update_stats(success=False)
            return None

    def test_connection(self) -> bool:
        """
        测试Steam Market API连接

        返回:
            True: 连接正常
            False: 连接失败
        """
        logger.info("🔌 [Steam] 测试 Steam Market API 连接...")

        # 使用一个常见饰品进行测试
        test_item = "AK-47 | Redline (Field-Tested)"

        try:
            price_data = self.get_price(test_item)

            if price_data:
                logger.success("✅ [Steam] Steam Market API 连接成功")
                return True
            else:
                logger.error("❌ [Steam] 无法获取测试数据")
                return False

        except Exception as e:
            logger.error(f"❌ [Steam] 连接失败: {e}")
            return False

    def get_item_listings(
        self,
        item_name: str,
        start: int = 0,
        count: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        获取饰品的市场挂单信息(高级功能)

        参数:
            item_name: 饰品名称
            start: 起始位置
            count: 获取数量

        返回:
            挂单信息(包括卖家、价格、磨损等)

        注意:
        - 此功能需要解析HTML,较为复杂
        - 限流要求更严格
        - 建议仅在必要时使用
        """
        logger.info(f"📋 [Steam] 获取挂单信息: {item_name}")
        logger.warning("   ⚠️ 此功能暂未实现,需要解析HTML")

        # TODO: 实现挂单信息获取
        # 需要请求: https://steamcommunity.com/market/listings/730/{item_name}
        # 解析HTML获取详细信息

        return None


# ==================== 使用示例 ====================

if __name__ == "__main__":
    """
    使用示例
    """
    from dotenv import load_dotenv
    import sys

    load_dotenv()

    # 配置日志
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

    # 创建爬虫
    with SteamMarketScraper(use_proxy=True) as scraper:
        # 1. 测试连接
        if not scraper.test_connection():
            logger.error("❌ 连接失败,请检查:")
            logger.error("   1. VPN/代理是否正常运行")
            logger.error("   2. 代理地址是否正确(默认: http://127.0.0.1:33210)")
            logger.error("   3. 网络连接是否正常")
            sys.exit(1)

        # 2. 获取多个饰品价格
        test_items = [
            "AK-47 | Redline (Field-Tested)",
            "AWP | Asiimov (Field-Tested)",
            "Glock-18 | Water Elemental (Field-Tested)"
        ]

        for item in test_items:
            price_data = scraper.get_price(item)

            if price_data:
                logger.success(f"✅ {item}: ¥{price_data['lowest_price']:.2f}")
            else:
                logger.error(f"❌ {item}: 获取失败")

        # 3. 查看统计信息
        stats = scraper.get_stats()
        logger.info(f"📊 统计信息: {stats}")
