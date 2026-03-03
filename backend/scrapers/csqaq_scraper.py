#!/usr/bin/env python3
"""
CSQAQ 企业接口抓取器

当前用于:
- 全量价格快照: /api/v1/goods/get_all_goods_info
- 基础库分页: /api/v1/goods/get_goods_template
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from loguru import logger

from backend.core.cache import allow_rate_limit
from .base_scraper import BaseScraper, rate_limit, retry


class CSQAQRateLimitError(RuntimeError):
    """CSQAQ 接口限频异常。"""

    def __init__(self, message: str, cooldown_seconds: int = 300) -> None:
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds


class CSQAQScraper(BaseScraper):
    """
    CSQAQ 企业接口抓取器
    
    官方文档: https://docs.csqaq.com/
    企业版 API 地址: https://private-api.csqaq.com
    频率限制:
        - 普通接口: 1 次/秒 (QPS = 1)
        - 企业全量接口: 5 分钟/次
    """
    BASE_URL_DEFAULT = "https://private-api.csqaq.com"
    ALL_GOODS_INFO_ENDPOINT = "/api/v1/goods/get_all_goods_info"
    GOODS_TEMPLATE_ENDPOINT = "/api/v1/goods/get_goods_template"
    CHART_ALL_ENDPOINT = "/api/v1/info/simple/chartAll"

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        rate_limit_seconds: float = 1.0,  # 遵循 1次/秒 限制
    ) -> None:
        super().__init__(
            platform_name="csqaq",
            use_proxy=False,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
        )
        token = api_token or os.getenv("CSQAQ_API_TOKEN") or os.getenv("CSQAQ_TOKEN")
        self.api_token = token.strip() if token else ""
        self.base_url = (base_url or os.getenv("CSQAQ_BASE_URL") or self.BASE_URL_DEFAULT).rstrip("/")

        if not self.api_token:
            logger.warning("[CSQAQ] Missing CSQAQ_API_TOKEN; requests will fail.")
        else:
            self.session.headers.update(
                {
                    "ApiToken": self.api_token,
                    "Content-Type": "application/json",
                }
            )
        self.global_qps_limit = max(1, int(os.getenv("CSQAQ_GLOBAL_QPS", "1")))
        self.global_qps_key = os.getenv("CSQAQ_GLOBAL_QPS_KEY", "quota:csqaq:global:qps")

    def _acquire_global_qps_slot(self) -> None:
        """
        使用 Redis 做跨进程全局 QPS 限流，避免多 Worker 并发突破企业 API 频率上限。
        """
        sleep_seconds = max(0.05, 1.0 / float(self.global_qps_limit))
        while True:
            try:
                allowed = allow_rate_limit(
                    self.global_qps_key,
                    self.global_qps_limit,
                    window_seconds=1,
                )
            except Exception as exc:
                # 若缓存不可用，降级为本地限流（由 @rate_limit 保底）。
                logger.warning("[CSQAQ] global qps limiter unavailable, fallback local limiter: {}", exc)
                return
            if allowed:
                return
            time.sleep(sleep_seconds)

    @staticmethod
    def _cooldown_from_message(message: str, default: int = 300) -> int:
        match = re.search(r"(\d+)\s*s", message or "", re.IGNORECASE)
        if not match:
            return default
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return default

    @staticmethod
    def _is_rate_limited(code: Any, message: str) -> bool:
        msg = (message or "").lower()
        return (
            str(code) == "429"
            or "频率" in message
            or "过快" in message
            or "limit" in msg
            or "too many" in msg
        )

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)  # 严格遵循单 IP 1次/秒 的限制
    def _post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_token:
            raise RuntimeError("CSQAQ_API_TOKEN not configured")
        self._acquire_global_qps_slot()

        url = f"{self.base_url}{path}"
        response = self.session.post(url, json=payload or {}, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("CSQAQ invalid response payload")

        code = data.get("code")
        message = str(data.get("msg") or data.get("message") or "")

        if code is None or str(code) in ("0", "200"):
            return data.get("data")

        if self._is_rate_limited(code, message):
            cooldown = self._cooldown_from_message(message, default=300)
            raise CSQAQRateLimitError(message or "rate_limited", cooldown_seconds=cooldown)

        raise RuntimeError(f"CSQAQ API error: code={code}, msg={message or 'unknown'}")

    def get_all_goods_info(self) -> List[Dict[str, Any]]:
        data = self._post(self.ALL_GOODS_INFO_ENDPOINT, payload={})
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def get_goods_template_page(self, page_index: int, page_size: int) -> Tuple[List[Dict[str, Any]], bool]:
        payload = {
            "page_index": page_index,
            "page_size": page_size,
        }
        data = self._post(self.GOODS_TEMPLATE_ENDPOINT, payload=payload)
        if not isinstance(data, dict):
            return [], False

        templates = data.get("template_info")
        if not isinstance(templates, list):
            templates = []
        templates = [row for row in templates if isinstance(row, dict)]
        has_next = bool(data.get("is_has_next_page"))
        return templates, has_next

    def get_chart_all(
        self,
        good_id: int | str,
        plat: int = 1,
        periods: str = "1day",
        max_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        payload = {
            "good_id": str(good_id),
            "plat": int(plat),
            "periods": periods,
        }
        if max_time is not None:
            payload["max_time"] = int(max_time)

        data = self._post(self.CHART_ALL_ENDPOINT, payload=payload)
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    @staticmethod
    def _normalize_template(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        market_hash_name = str(raw.get("market_hash_name") or "").strip()
        if not market_hash_name:
            return None

        item_type = str(raw.get("type_localized_name") or "").strip()
        normalized: Dict[str, Any] = {
            "market_hash_name": market_hash_name,
            "name_cn": str(raw.get("name") or "").strip() or None,
            "name_buff": str(raw.get("short_name") or "").strip() or None,
            "type": item_type or "unknown",
            "weapon_type": item_type or None,
            "skin_name": str(raw.get("short_name") or "").strip() or None,
            "quality": str(raw.get("quality_localized_name") or "").strip() or None,
            "rarity": str(raw.get("rarity_localized_name") or "").strip() or None,
            "image": str(raw.get("img") or "").strip() or None,
        }
        return normalized

    def iter_items(
        self,
        page_size: int = 1000,
        max_pages: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        page = 1
        while True:
            rows, has_next = self.get_goods_template_page(page_index=page, page_size=page_size)
            if not rows:
                break

            for row in rows:
                normalized = self._normalize_template(row)
                if normalized:
                    yield normalized

            if not has_next:
                break

            page += 1
            if max_pages is not None and page > max_pages:
                break

    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        rows = self.get_all_goods_info()
        target = item_name.strip().lower()
        for row in rows:
            market_hash_name = str(row.get("market_hash_name") or "").strip().lower()
            if market_hash_name != target:
                continue

            buff_price = row.get("buff_sell_price")
            youpin_price = row.get("yyyp_sell_price")
            if buff_price is None and youpin_price is None:
                return None

            return {
                "platform": "csqaq",
                "item_name": item_name,
                "buff_price": float(buff_price) if buff_price is not None else None,
                "youpin_price": float(youpin_price) if youpin_price is not None else None,
                "volume": row.get("buff_sell_num"),
                "youpin_volume": row.get("yyyp_sell_num"),
                "timestamp": row.get("updated_at") or datetime.utcnow().isoformat(),
                "currency": "CNY",
            }
        return None

    def test_connection(self) -> bool:
        try:
            rows, _ = self.get_goods_template_page(page_index=1, page_size=1)
            return isinstance(rows, list)
        except requests.RequestException as exc:
            logger.error("[CSQAQ] connection test failed: {}", exc)
            return False
        except Exception as exc:
            logger.error("[CSQAQ] connection test failed: {}", exc)
            return False
