#!/usr/bin/env python3
"""
Youpin 直连爬虫 (API 直抓)

需要提供设备指纹请求头 (YOUPIN_HEADERS_FILE) 与模板映射表。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from .base_scraper import BaseScraper, rate_limit, retry


BASE_URL = "https://api.youpin898.com"

BASE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "referer": "https://www.youpin898.com/",
}


def _default_docs_file(filename: str) -> Optional[str]:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "docs" / "youpin" / filename
    if candidate.is_file():
        return str(candidate)
    return None


def _parse_price(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _select_min_price(items: list[Dict[str, Any]]) -> Optional[Decimal]:
    prices = [_parse_price(item.get("price")) for item in items]
    prices = [price for price in prices if price is not None]
    return min(prices) if prices else None


def _load_headers(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Youpin] Failed to load headers: {}", exc)
        return {}
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items()}
    return {}


@lru_cache(maxsize=4)
def _load_template_map(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Youpin] Failed to parse template map {}: {}", file_path, exc)
        return {}

    if isinstance(payload, dict) and "items" in payload and isinstance(payload["items"], dict):
        payload = payload["items"]

    mapping: Dict[str, str] = {}

    def _add_mapping(name: Optional[str], template_id: Optional[Any]) -> None:
        if not name or template_id is None:
            return
        normalized = str(name).strip()
        if not normalized:
            return
        mapping[normalized] = str(template_id)

    if isinstance(payload, dict):
        for key, value in payload.items():
            names: list[str] = []
            template_id = None

            if str(key).isdigit():
                template_id = str(key)
                if isinstance(value, dict):
                    for candidate in (
                        value.get("hash_name"),
                        value.get("hashName"),
                        value.get("commodityHashName"),
                        value.get("market_hash_name"),
                        value.get("name"),
                        value.get("commodityName"),
                    ):
                        if candidate:
                            names.append(str(candidate))
                else:
                    names.append(str(value))
            else:
                names.append(str(key))
                if isinstance(value, dict):
                    template_id = value.get("template_id") or value.get("templateId") or value.get("id")
                    for candidate in (
                        value.get("hash_name"),
                        value.get("hashName"),
                        value.get("commodityHashName"),
                        value.get("market_hash_name"),
                        value.get("name"),
                        value.get("commodityName"),
                    ):
                        if candidate:
                            names.append(str(candidate))
                else:
                    template_id = value

            for name in names:
                _add_mapping(name, template_id)

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("hash_name")
                or item.get("hashName")
                or item.get("commodityHashName")
                or item.get("market_hash_name")
                or item.get("name")
                or item.get("commodityName")
            )
            template_id = item.get("template_id") or item.get("templateId") or item.get("id")
            _add_mapping(name, template_id)

    return mapping


def _pick_proxy(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    env_val = os.getenv("YOUPIN_PROXY_URL") or os.getenv("YOUPIN_PROXY")
    if env_val:
        return env_val
    env_list = os.getenv("YOUPIN_PROXIES")
    if not env_list:
        return None
    for part in env_list.split(","):
        part = part.strip()
        if part:
            return part
    return None


class YoupinScraper(BaseScraper):
    """
    Youpin 直连爬虫
    """

    def __init__(
        self,
        timeout: int = 15,
        rate_limit_seconds: float = 1.8,
        use_proxy: Optional[bool] = None,
        proxy_url: Optional[str] = None,
        headers_file: Optional[str] = None,
        template_map_file: Optional[str] = None,
    ):
        proxy_url = _pick_proxy(proxy_url)
        if use_proxy is None:
            use_proxy = bool(proxy_url)

        super().__init__(
            platform_name="youpin",
            use_proxy=use_proxy,
            proxy_url=proxy_url,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
        )

        self.headers_file = headers_file or os.getenv("YOUPIN_HEADERS_FILE") or _default_docs_file("youpin_headers.json")
        self.template_map_file = (
            template_map_file
            or os.getenv("YOUPIN_TEMPLATE_MAP_FILE")
            or _default_docs_file("youpin_name_map_from_dump.json")
            or _default_docs_file("youpin_name_map_full.json")
        )

        self.device_headers = _load_headers(self.headers_file)
        if not self.device_headers:
            logger.warning("[Youpin] Missing device headers; requests may fail")

        self.template_map = _load_template_map(self.template_map_file)
        if self.template_map:
            logger.info("[Youpin] Loaded template map: {} items", len(self.template_map))

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = dict(BASE_HEADERS)
        headers.update(self.device_headers)
        resp = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}")
        data = resp.json()
        if data.get("Code") != 0:
            raise RuntimeError(f"Youpin API error: {data}")
        return data

    def _resolve_template_id(self, item_name: str) -> Optional[str]:
        normalized = (item_name or "").strip()
        if normalized.isdigit():
            return normalized

        if item_name in self.template_map:
            return self.template_map[item_name]
        return None

    def _query_on_sale(self, template_id: str) -> Dict[str, Any]:
        url = f"{BASE_URL}/api/homepage/pc/goods/market/queryOnSaleCommodityList"
        payload = {
            "gameId": "730",
            "listType": "10",
            "templateId": str(template_id),
            "listSortType": 1,
            "sortType": 0,
            "pageIndex": 1,
            "pageSize": 10,
        }
        data = self._post_json(url, payload)
        return {"items": data.get("Data") or [], "total_count": data.get("TotalCount")}

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)
    def get_price(self, item_name: str, item_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        logger.info("🎲 [Youpin] 获取价格: {}", item_name)
        template_id = self._resolve_template_id(item_name)
        if not template_id:
            logger.warning("⚠️ [Youpin] 未找到 template_id: {}", item_name)
            self._update_stats(success=False)
            return None

        try:
            sale = self._query_on_sale(template_id)
        except Exception as exc:
            logger.error("❌ [Youpin] 请求失败: {}", exc)
            self._update_stats(success=False)
            return None

        items = sale.get("items") or []
        min_price = _select_min_price(items)
        sell_count = sale.get("total_count")

        if min_price is None:
            logger.warning("⚠️ [Youpin] 无在售价格: {}", item_name)
            self._update_stats(success=False)
            return None

        payload = {
            "platform": "youpin",
            "item_name": item_name,
            "lowest_price": float(min_price),
            "volume": int(sell_count) if sell_count is not None else None,
            "sell_listings": int(sell_count) if sell_count is not None else None,
            "timestamp": datetime.now().isoformat(),
            "currency": "CNY",
            "template_id": str(template_id),
        }
        self._update_stats(success=True)
        logger.success("✅ [Youpin] 最低价: {}", payload["lowest_price"])
        return payload

    def test_connection(self) -> bool:
        sample_name = os.getenv("YOUPIN_TEST_ITEM", "AK-47 | Redline (Field-Tested)")
        template_id = self._resolve_template_id(sample_name)
        if not template_id:
            logger.warning("[Youpin] Missing template mapping for test item")
            return False
        try:
            _ = self._query_on_sale(template_id)
            logger.success("✅ [Youpin] 连接测试成功")
            return True
        except Exception as exc:
            logger.error("❌ [Youpin] 连接测试失败: {}", exc)
            return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Youpin direct scraper test")
    parser.add_argument("--item", required=True, help="Market hash name")
    args = parser.parse_args()

    with YoupinScraper() as scraper:
        print(scraper.get_price(args.item))
