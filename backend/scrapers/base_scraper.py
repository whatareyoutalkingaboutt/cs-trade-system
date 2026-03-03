#!/usr/bin/env python3
"""
爬虫基类

提供所有爬虫的通用功能:
- 限流控制
- 重试机制
- 错误处理
- User-Agent轮换
- 代理配置
- 统一的接口定义
"""

import time
import random
from abc import ABC, abstractmethod
from functools import wraps
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

import requests
from loguru import logger


# ==================== 装饰器 ====================

def rate_limit(seconds: float):
    """
    限流装饰器

    参数:
        seconds: 每次请求之间的最小时间间隔(秒)

    示例:
        @rate_limit(2.0)  # 每2秒最多1次请求
        def fetch_data(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        last_called = [0.0]  # 使用列表以便在闭包中修改

        @wraps(func)
        def wrapper(*args, **kwargs):
            # 计算需要等待的时间
            elapsed = time.time() - last_called[0]
            if elapsed < seconds:
                wait_time = seconds - elapsed
                logger.debug(f"⏳ 限流控制: 等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)

            # 执行函数
            result = func(*args, **kwargs)
            last_called[0] = time.time()

            return result

        return wrapper
    return decorator


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    重试装饰器(指数退避)

    参数:
        max_attempts: 最大尝试次数
        delay: 初始延迟时间(秒)
        backoff: 退避系数(每次失败后延迟乘以此系数)

    示例:
        @retry(max_attempts=3, delay=1.0, backoff=2.0)
        def fetch_data(self):
            # 失败后会自动重试,延迟为: 1s, 2s, 4s
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(f"❌ 重试 {max_attempts} 次后仍然失败: {e}")
                        raise

                    logger.warning(f"⚠️ 第 {attempt}/{max_attempts} 次尝试失败: {e}")
                    logger.info(f"⏳ {current_delay:.1f}秒后重试...")

                    time.sleep(current_delay)
                    current_delay *= backoff

            return None

        return wrapper
    return decorator


# ==================== 爬虫基类 ====================

class BaseScraper(ABC):
    """
    爬虫基类

    所有爬虫都应该继承此类,并实现以下方法:
    - get_price(): 获取单个饰品的价格
    - test_connection(): 测试连接是否正常
    """

    # User-Agent 池(轮换使用,避免被识别为爬虫)
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    def __init__(
        self,
        platform_name: str,
        use_proxy: bool = False,
        proxy_url: Optional[str] = None,
        timeout: int = 10,
        rate_limit_seconds: float = 2.0
    ):
        """
        初始化爬虫

        参数:
            platform_name: 平台名称(如 'steam', 'buff')
            use_proxy: 是否使用代理
            proxy_url: 代理URL(如 'http://127.0.0.1:33210')
            timeout: 请求超时时间(秒)
            rate_limit_seconds: 限流时间间隔(秒)
        """
        self.platform_name = platform_name
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds

        # 创建会话
        self.session = requests.Session()

        # 配置代理
        if use_proxy and proxy_url:
            self.session.proxies.update({
                'http': proxy_url,
                'https': proxy_url
            })
            logger.info(f"✅ [{platform_name}] 已启用代理: {proxy_url}")

        # 设置默认User-Agent
        self._rotate_user_agent()

        # 统计信息
        self.stats = {
            'total_requests': 0,
            'success_count': 0,
            'failed_count': 0,
            'last_request_time': None
        }

    def _rotate_user_agent(self):
        """轮换 User-Agent"""
        user_agent = random.choice(self.USER_AGENTS)
        self.session.headers.update({'User-Agent': user_agent})
        logger.debug(f"🔄 [{self.platform_name}] User-Agent: {user_agent[:50]}...")

    def _update_stats(self, success: bool):
        """
        更新统计信息

        参数:
            success: 请求是否成功
        """
        self.stats['total_requests'] += 1
        if success:
            self.stats['success_count'] += 1
        else:
            self.stats['failed_count'] += 1
        self.stats['last_request_time'] = datetime.now()

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        返回:
            统计数据字典
        """
        total = self.stats['total_requests']
        success_rate = (self.stats['success_count'] / total * 100) if total > 0 else 0

        return {
            'platform': self.platform_name,
            'total_requests': total,
            'success_count': self.stats['success_count'],
            'failed_count': self.stats['failed_count'],
            'success_rate': f"{success_rate:.2f}%",
            'last_request_time': self.stats['last_request_time'].isoformat() if self.stats['last_request_time'] else None
        }

    @abstractmethod
    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        """
        获取饰品价格(抽象方法,子类必须实现)

        参数:
            item_name: 饰品名称

        返回:
            价格数据字典,格式为:
            {
                'platform': str,          # 平台名称
                'item_name': str,         # 饰品名称
                'lowest_price': float,    # 最低价格
                'median_price': float,    # 中位价格(可选)
                'highest_price': float,   # 最高价格(可选)
                'volume': int,            # 交易量(可选)
                'timestamp': str,         # ISO格式时间戳
                'currency': str,          # 货币(如 'CNY')
            }
            如果获取失败,返回 None
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        测试连接是否正常(抽象方法,子类必须实现)

        返回:
            True: 连接正常
            False: 连接失败
        """
        pass

    def batch_get_prices(
        self,
        item_names: List[str],
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        批量获取饰品价格

        参数:
            item_names: 饰品名称列表
            progress_callback: 进度回调函数,签名为 (当前索引, 总数, 当前饰品名称)

        返回:
            价格数据列表(失败的项为None)
        """
        results = []
        total = len(item_names)

        logger.info(f"🚀 [{self.platform_name}] 开始批量获取 {total} 个饰品价格")

        for i, item_name in enumerate(item_names, 1):
            try:
                # 回调进度
                if progress_callback:
                    progress_callback(i, total, item_name)

                # 获取价格
                price_data = self.get_price(item_name)
                results.append(price_data)

                # 日志
                if price_data:
                    logger.success(f"  ✅ [{i}/{total}] {item_name}")
                else:
                    logger.warning(f"  ❌ [{i}/{total}] {item_name} - 获取失败")

            except Exception as e:
                logger.error(f"  ❌ [{i}/{total}] {item_name} - 异常: {e}")
                results.append(None)

        # 统计
        success_count = sum(1 for r in results if r is not None)
        logger.info(f"✅ [{self.platform_name}] 批量获取完成: {success_count}/{total} 成功")

        return results

    def close(self):
        """关闭会话"""
        self.session.close()
        logger.info(f"👋 [{self.platform_name}] 会话已关闭")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
        return False


# ==================== 工具函数 ====================

def parse_price_string(price_str: str) -> Optional[float]:
    """
    解析价格字符串为浮点数

    参数:
        price_str: 价格字符串(如 "¥35.50", "$10.99")

    返回:
        价格浮点数,解析失败返回None

    示例:
        >>> parse_price_string("¥35.50")
        35.5
        >>> parse_price_string("$10.99")
        10.99
    """
    if not price_str or price_str == 'N/A':
        return None

    try:
        # 移除货币符号和逗号
        cleaned = price_str.replace('¥', '').replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        logger.warning(f"⚠️ 无法解析价格字符串: {price_str}")
        return None


def validate_price_data(data: Dict[str, Any], required_fields: List[str] = None) -> bool:
    """
    验证价格数据格式

    参数:
        data: 价格数据字典
        required_fields: 必需字段列表

    返回:
        True: 数据有效
        False: 数据无效
    """
    if required_fields is None:
        required_fields = ['platform', 'item_name', 'timestamp']

    for field in required_fields:
        if field not in data or data[field] is None:
            logger.warning(f"⚠️ 数据验证失败: 缺少字段 '{field}'")
            return False

    return True
