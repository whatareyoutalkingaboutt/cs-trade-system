#!/usr/bin/env python3
"""
Buff 平台爬虫 (直连 Buff API)

替代 SteamDT API 的 Buff 价格获取方式。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger
from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.models import Item
from .base_scraper import BaseScraper, rate_limit, retry


BASE_URL = "https://buff.163.com"
BUFF_URL_RE = re.compile(r"/goods/(\d+)")

BASE_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "x-requested-with": "XMLHttpRequest",
    "referer": "https://buff.163.com/market/csgo",
}


def _default_docs_file(filename: str) -> Optional[str]:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "docs" / "buff" / filename
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


def _select_max_price(items: list[Dict[str, Any]]) -> Optional[Decimal]:
    prices = [_parse_price(item.get("price")) for item in items]
    prices = [price for price in prices if price is not None]
    return max(prices) if prices else None


def _split_name_wear(name: str) -> tuple[str, Optional[str]]:
    if not name:
        return "", None
    for open_sym, close_sym in ((" (", ")"), ("（", "）")):
        if name.endswith(close_sym) and open_sym in name:
            base, wear = name.rsplit(open_sym, 1)
            wear = wear[: -len(close_sym)]
            return base.strip(), wear.strip()
    return name.strip(), None


def _extract_goods_info(
    sell_orders: Optional[Dict[str, Any]],
    goods_id: str,
) -> Optional[Dict[str, Any]]:
    if not sell_orders:
        return None
    goods_infos = sell_orders.get("goods_infos")
    if isinstance(goods_infos, dict):
        return goods_infos.get(str(goods_id))
    return None


def _extract_name_wear(goods_info: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not goods_info:
        return {"name": None, "wear": None}
    name_raw = goods_info.get("short_name") or goods_info.get("name") or ""
    split_name, split_wear = _split_name_wear(name_raw)
    wear = None
    tags = goods_info.get("tags") or {}
    exterior = tags.get("exterior") or {}
    if isinstance(exterior, dict):
        wear = exterior.get("localized_name") or exterior.get("internal_name")
    if not wear:
        market_hash = goods_info.get("market_hash_name") or ""
        _, parsed_wear = _split_name_wear(market_hash)
        wear = parsed_wear or split_wear
    return {"name": split_name or None, "wear": wear}


def _load_cookies(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Buff] Failed to load cookies: {}", exc)
        return {}
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items()}
    if isinstance(payload, list):
        cookies: Dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            cookies[str(name)] = str(item.get("value", ""))
        return cookies
    return {}


@lru_cache(maxsize=4)
def _load_goods_id_map(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[Buff] Failed to parse goods map {}: {}", file_path, exc)
        return {}

    if isinstance(payload, dict) and "items" in payload and isinstance(payload["items"], dict):
        payload = payload["items"]

    mapping: Dict[str, str] = {}
    if isinstance(payload, dict):
        keys = list(payload.keys())
        all_digit_keys = bool(keys) and all(str(k).isdigit() for k in keys)
        for key, value in payload.items():
            if all_digit_keys and isinstance(value, dict):
                name = (
                    value.get("market_hash_name")
                    or value.get("marketHashName")
                    or value.get("name")
                    or value.get("short_name")
                )
                if name:
                    mapping[str(name)] = str(key)
                continue

            name = str(key)
            goods_id = None
            if isinstance(value, dict):
                goods_id = value.get("goods_id") or value.get("id") or value.get("goodsId")
            else:
                goods_id = value
            if goods_id is not None:
                mapping[name] = str(goods_id)
        return mapping

    if isinstance(payload, list):
        if payload and all(isinstance(item, str) and str(item).isdigit() for item in payload):
            logger.warning(
                "[Buff] %s is a goods_id list, not a name->id map; falling back to search/DB resolver.",
                file_path,
            )
            return {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("market_hash_name") or item.get("marketHashName") or item.get("name")
            goods_id = item.get("goods_id") or item.get("id") or item.get("goodsId")
            if name and goods_id is not None:
                mapping[str(name)] = str(goods_id)

    return mapping


def _pick_proxy(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    env_val = os.getenv("BUFF_PROXY_URL") or os.getenv("BUFF_PROXY")
    if env_val:
        return env_val
    env_list = os.getenv("BUFF_PROXIES")
    if not env_list:
        return None
    for part in env_list.split(","):
        part = part.strip()
        if part:
            return part
    return None


class BuffScraper(BaseScraper):
    """
    Buff 直连爬虫

    使用 Buff 官方 API 接口获取价格信息。
    """

    def __init__(
        self,
        timeout: int = 12,
        rate_limit_seconds: float = 1.5,
        use_proxy: Optional[bool] = None,
        proxy_url: Optional[str] = None,
        cookies_file: Optional[str] = None,
        goods_id_map_file: Optional[str] = None,
        search_enabled: Optional[bool] = None,
    ):
        proxy_url = _pick_proxy(proxy_url)
        if use_proxy is None:
            use_proxy = bool(proxy_url)

        super().__init__(
            platform_name="buff",
            use_proxy=use_proxy,
            proxy_url=proxy_url,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
        )

        self.session.headers.update(dict(BASE_HEADERS))
        self.cookies_file = cookies_file or os.getenv("BUFF_COOKIES_FILE") or _default_docs_file("buff_cookies.json")
        self.goods_id_map_file = (
            goods_id_map_file
            or os.getenv("BUFF_GOODS_ID_MAP_FILE")
            or _default_docs_file("buff_goods_id_map.json")
        )
        self.search_enabled = search_enabled
        if self.search_enabled is None:
            raw = os.getenv("BUFF_SEARCH_ENABLED", "").strip().lower()
            if raw in {"1", "true", "yes"}:
                self.search_enabled = True
            elif raw in {"0", "false", "no"}:
                self.search_enabled = False
            else:
                self.search_enabled = bool(self.cookies_file)

        self.cookies = _load_cookies(self.cookies_file)
        if self.cookies:
            self.session.cookies.update(self.cookies)

        self.goods_id_map = _load_goods_id_map(self.goods_id_map_file)
        if self.goods_id_map:
            logger.info("[Buff] Loaded goods_id map: {} items", len(self.goods_id_map))

    def _request_json(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} for {url}")
        data = resp.json()
        if data.get("code") != "OK":
            raise RuntimeError(f"Buff API error: {data}")
        return data.get("data") or {}

    def _resolve_goods_id_from_db(self, item_name: str, item_id: Optional[int]) -> Optional[str]:
        session = get_sessionmaker()()
        try:
            if item_id is not None:
                buff_url = session.execute(
                    select(Item.buff_url).where(Item.id == item_id)
                ).scalar_one_or_none()
            else:
                buff_url = session.execute(
                    select(Item.buff_url).where(Item.market_hash_name == item_name)
                ).scalar_one_or_none()
        finally:
            session.close()

        if not buff_url:
            return None

        match = BUFF_URL_RE.search(str(buff_url))
        if not match:
            return None
        return match.group(1)

    def _search_goods_id(self, item_name: str) -> Optional[str]:
        if not self.search_enabled:
            return None
        if not self.cookies:
            logger.warning("[Buff] Search requires cookies; BUFF_COOKIES_FILE not set")
            return None

        url = f"{BASE_URL}/api/market/goods"
        params = {
            "game": "csgo",
            "page_num": 1,
            "search": item_name,
            "_": int(time.time() * 1000),
        }
        data = self._request_json(url, params)
        items = data.get("items") or []
        if not items:
            return None

        lowered = item_name.lower()
        for item in items:
            candidate = (
                str(item.get("market_hash_name") or "")
                or str(item.get("name") or "")
                or str(item.get("short_name") or "")
            )
            if candidate.lower() == lowered:
                return str(item.get("id") or item.get("goods_id"))

        first = items[0]
        return str(first.get("id") or first.get("goods_id"))

    def _resolve_goods_id(self, item_name: str, item_id: Optional[int]) -> Optional[str]:
        normalized = (item_name or "").strip()
        if normalized.isdigit():
            return normalized

        if self.goods_id_map and item_name in self.goods_id_map:
            return self.goods_id_map[item_name]

        goods_id = self._resolve_goods_id_from_db(item_name, item_id)
        if goods_id:
            return goods_id

        return self._search_goods_id(item_name)

    def _fetch_sell_orders(
        self,
        goods_id: str,
        page_num: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        url = f"{BASE_URL}/api/market/goods/sell_order"
        params = {
            "game": "csgo",
            "goods_id": goods_id,
            "page_num": page_num,
            "page_size": page_size,
            "_": int(time.time() * 1000),
        }
        return self._request_json(url, params)

    def _fetch_buy_orders(
        self,
        goods_id: str,
        page_num: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        url = f"{BASE_URL}/api/market/goods/buy_order"
        params = {
            "game": "csgo",
            "goods_id": goods_id,
            "page_num": page_num,
            "page_size": page_size,
            "_": int(time.time() * 1000),
        }
        return self._request_json(url, params)

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)
    def get_price(self, item_name: str, item_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        logger.info("🎲 [Buff] 获取价格: {}", item_name)
        goods_id = self._resolve_goods_id(item_name, item_id)
        if not goods_id:
            logger.warning("⚠️ [Buff] 未找到 goods_id: {}", item_name)
            self._update_stats(success=False)
            return None

        try:
            sell_orders = self._fetch_sell_orders(goods_id)
            buy_orders = self._fetch_buy_orders(goods_id)
        except Exception as exc:
            logger.error("❌ [Buff] 请求失败: {}", exc)
            self._update_stats(success=False)
            return None

        sell_items = sell_orders.get("items") or []
        min_price = _select_min_price(sell_items)
        sell_count = sell_orders.get("total_count") or sell_orders.get("totalCount")
        buy_count = buy_orders.get("total_count") or buy_orders.get("totalCount")

        if min_price is None:
            logger.warning("⚠️ [Buff] 无在售价格: {}", item_name)
            self._update_stats(success=False)
            return None

        payload = {
            "platform": "buff",
            "item_name": item_name,
            "lowest_price": float(min_price),
            "volume": int(sell_count) if sell_count is not None else None,
            "sell_listings": int(sell_count) if sell_count is not None else None,
            "buy_orders": int(buy_count) if buy_count is not None else None,
            "timestamp": datetime.now().isoformat(),
            "currency": "CNY",
            "goods_id": str(goods_id),
        }
        self._update_stats(success=True)
        logger.success("✅ [Buff] 最低价: {}", payload["lowest_price"])
        return payload

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)
    def get_goods_snapshot(
        self,
        goods_id: str,
        page_num: int = 1,
        page_size: int = 10,
    ) -> Dict[str, Any]:
        logger.info("🎲 [Buff] 获取商品快照: {}", goods_id)
        sell_orders = self._fetch_sell_orders(goods_id, page_num=page_num, page_size=page_size)
        buy_orders = self._fetch_buy_orders(goods_id, page_num=page_num, page_size=page_size)

        goods_info = _extract_goods_info(sell_orders, goods_id)
        name_wear = _extract_name_wear(goods_info)

        sell_items = sell_orders.get("items") or []
        buy_items = buy_orders.get("items") or []
        sell_min_price = _select_min_price(sell_items)
        buy_max_price = _select_max_price(buy_items)

        sell_count = sell_orders.get("total_count") or sell_orders.get("totalCount")
        buy_count = buy_orders.get("total_count") or buy_orders.get("totalCount")

        payload = {
            "goods_id": str(goods_id),
            "name": name_wear.get("name"),
            "wear": name_wear.get("wear"),
            "sell_count": int(sell_count) if sell_count is not None else None,
            "buy_count": int(buy_count) if buy_count is not None else None,
            "sell_min_price": float(sell_min_price) if sell_min_price is not None else None,
            "buy_max_price": float(buy_max_price) if buy_max_price is not None else None,
            "currency": "CNY",
            "timestamp": datetime.now().isoformat(),
            "sell_orders": sell_orders,
            "buy_orders": buy_orders,
        }
        self._update_stats(success=True)
        return payload

    def test_connection(self) -> bool:
        test_goods = os.getenv("BUFF_TEST_GOODS_ID", "35650")
        try:
            _ = self._fetch_sell_orders(str(test_goods))
            logger.success("✅ [Buff] 连接测试成功")
            return True
        except Exception as exc:
            logger.error("❌ [Buff] 连接测试失败: {}", exc)
            return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Buff direct scraper test")
    parser.add_argument("--item", required=True, help="Market hash name")
    args = parser.parse_args()

    with BuffScraper() as scraper:
        print(scraper.get_price(args.item))
