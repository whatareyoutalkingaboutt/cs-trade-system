#!/usr/bin/env python3
"""
SteamDT 价格爬虫 (单品价格)

用于获取 Buff / Youpin / Steam 的聚合价格。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from .base_scraper import BaseScraper, rate_limit, retry


class SteamDTPriceScraper(BaseScraper):
    """SteamDT price single API client."""

    BASE_URL = "https://open.steamdt.com/open/cs2/v1"
    PRICE_SINGLE_ENDPOINT = "/price/single"

    @staticmethod
    def _split_keys(raw: str) -> list[str]:
        parts = [part.strip() for part in raw.replace(";", ",").split(",")]
        return [part for part in parts if part]

    @staticmethod
    def _dedupe(keys: list[str]) -> list[str]:
        seen = set()
        result = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            result.append(key)
        return result

    @classmethod
    def _load_api_keys(cls) -> list[str]:
        keys: list[str] = []
        single = os.getenv("STEAMDT_API_KEY")
        if single:
            keys.append(single)

        multi = os.getenv("STEAMDT_API_KEYS")
        if multi:
            keys.extend(cls._split_keys(multi))

        for idx in range(1, 10):
            value = os.getenv(f"STEAMDT_API_KEY_{idx}")
            if value:
                keys.append(value)

        return cls._dedupe([key for key in keys if key])

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 12,
        rate_limit_seconds: float = 1.0,
    ):
        super().__init__(
            platform_name="steamdt_price",
            use_proxy=False,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
        )

        if api_key:
            candidate_keys = [api_key]
        else:
            candidate_keys = self._load_api_keys()

        self.api_keys = [key for key in candidate_keys if key.isascii()]
        self.api_key_index = 0
        self.api_key = None

        if self.api_keys:
            self._set_api_key(0)
        else:
            logger.warning("[SteamDT] Missing STEAMDT_API_KEY; requests will fail.")

    def _set_api_key(self, index: int) -> None:
        if not self.api_keys:
            self.api_key = None
            return
        self.api_key_index = index % len(self.api_keys)
        self.api_key = self.api_keys[self.api_key_index]
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _extract_platform_row(self, payload: Any, platform: str) -> Optional[Dict[str, Any]]:
        target = platform.upper()
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                if str(row.get("platform", "")).upper() == target:
                    return row
        if isinstance(payload, dict):
            for key in ("items", "list", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return self._extract_platform_row(value, platform)
        return None

    def _parse_price(self, row: Optional[Dict[str, Any]]) -> Optional[float]:
        if not row:
            return None
        for key in ("sellPrice", "price", "lowest_price", "lowestPrice"):
            value = row.get(key)
            if value is None:
                continue
            try:
                return float(str(value).replace("¥", "").replace("$", "").replace(",", "").strip())
            except ValueError:
                continue
        return None

    def _parse_volume(self, row: Optional[Dict[str, Any]]) -> Optional[int]:
        if not row:
            return None
        value = row.get("sellCount") or row.get("volume")
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)
    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            logger.warning("[SteamDT] Missing API key; cannot fetch price.")
            return None

        url = f"{self.BASE_URL}{self.PRICE_SINGLE_ENDPOINT}"
        params = {"marketHashName": item_name}

        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        code = data.get("code")
        if code is not None and str(code) not in ("0", "200"):
            message = data.get("message") or data.get("msg") or data.get("error") or "unknown"
            raise RuntimeError(f"SteamDT error: {message}")

        payload = data.get("data", {})

        buff_row = self._extract_platform_row(payload, "BUFF")
        youpin_row = self._extract_platform_row(payload, "YOUPIN")
        steam_row = self._extract_platform_row(payload, "STEAM")

        buff_price = self._parse_price(buff_row)
        youpin_price = self._parse_price(youpin_row)
        steam_price = self._parse_price(steam_row)

        if buff_price is None and youpin_price is None and steam_price is None:
            return None

        return {
            "platform": "steamdt",
            "item_name": item_name,
            "buff_price": buff_price,
            "steam_price": steam_price,
            "youpin_price": youpin_price,
            "volume": self._parse_volume(buff_row),
            "youpin_volume": self._parse_volume(youpin_row),
            "timestamp": datetime.now().isoformat(),
            "currency": "CNY",
        }

    def test_connection(self) -> bool:
        sample = os.getenv("STEAMDT_TEST_ITEM", "AK-47 | Redline (Field-Tested)")
        try:
            return self.get_price(sample) is not None
        except Exception as exc:
            logger.error("[SteamDT] Connection test failed: {}", exc)
            return False
