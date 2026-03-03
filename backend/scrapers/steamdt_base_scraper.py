#!/usr/bin/env python3
"""
SteamDT base scraper

Endpoint:
- /open/cs2/v1/base
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

import requests
from loguru import logger

from .base_scraper import BaseScraper, rate_limit, retry


class SteamDTBaseScraper(BaseScraper):
    """SteamDT base API client (items catalog)."""

    BASE_URL = "https://open.steamdt.com/open/cs2/v1"
    BASE_ENDPOINT = "/base"

    @staticmethod
    def _split_keys(raw: str) -> list[str]:
        parts = re.split(r"[,\s;]+", raw.strip())
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
        timeout: int = 20,
        rate_limit_seconds: float = 1.0,
    ):
        super().__init__(
            platform_name="steamdt_base",
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
            key_index = 0
            key_index_raw = os.getenv("STEAMDT_API_KEY_INDEX")
            if key_index_raw:
                try:
                    key_index = max(0, int(key_index_raw))
                except ValueError:
                    key_index = 0
            self._set_api_key(key_index)
        else:
            self.api_key = None

        if not self.api_keys:
            logger.warning("[SteamDTBase] Missing STEAMDT_API_KEY; requests will fail.")

    def _set_api_key(self, index: int, reason: Optional[str] = None) -> None:
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
        if reason:
            logger.warning(
                "[SteamDTBase] Switched API key (index=%s) due to: %s",
                self.api_key_index,
                reason,
            )

    def _rotate_api_key(self, reason: str) -> bool:
        if not self.api_keys or len(self.api_keys) < 2:
            return False
        next_index = (self.api_key_index + 1) % len(self.api_keys)
        if next_index == self.api_key_index:
            return False
        self._set_api_key(next_index, reason=reason)
        return True

    @staticmethod
    def _should_rotate_key(message: str) -> bool:
        if not message:
            return False
        lowered = message.lower()
        keywords = (
            "quota",
            "limit",
            "too many",
            "rate",
            "429",
            "unauthorized",
            "forbidden",
            "invalid",
            "expired",
            "apikey",
            "api key",
            "401",
            "403",
            "上限",
            "限制",
            "频率",
            "次数",
        )
        return any(keyword in lowered for keyword in keywords)

    def get_price(self, item_name: str):  # pragma: no cover - not used
        logger.warning("[SteamDTBase] get_price is not supported in this scraper.")
        self._update_stats(success=False)
        return None

    def test_connection(self) -> bool:
        if not self.api_keys:
            logger.error("[SteamDTBase] Missing API key; cannot test connection.")
            return False
        try:
            self.fetch_page(page=1, page_size=1)
        except Exception:
            return False
        return True

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(1.0)
    def fetch_page(self, page: Optional[int] = None, page_size: Optional[int] = None) -> Any:
        if not self.api_keys or not self.api_key:
            raise RuntimeError("SteamDT API key not configured")

        params: Dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["pageSize"] = page_size

        url = f"{self.BASE_URL}{self.BASE_ENDPOINT}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else None
            if status in (401, 403, 429):
                self._rotate_api_key(reason=f"http_{status}")
            raise

        payload = response.json()
        try:
            data = self._extract_payload(payload)
        except RuntimeError as exc:
            if self._should_rotate_key(str(exc)):
                self._rotate_api_key(reason=str(exc))
            raise
        if data is None:
            raise RuntimeError("SteamDT base response invalid")
        return data

    def iter_items(
        self,
        page_size: int = 1000,
        max_pages: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        page = 1
        while True:
            data = self.fetch_page(page=page, page_size=page_size)
            items = self._extract_items(data)
            if not items:
                break

            for item in items:
                if isinstance(item, dict):
                    yield item

            if not self._has_more(data, page=page, page_size=page_size, fetched=len(items)):
                break

            page += 1
            if max_pages is not None and page > max_pages:
                break

    @staticmethod
    def _extract_payload(data: Any) -> Optional[Any]:
        if not isinstance(data, dict):
            return data

        if "success" in data:
            if not data.get("success"):
                error_msg = data.get("errorMsg") or data.get("message") or "unknown_error"
                logger.error(f"[SteamDTBase] API error: {error_msg}")
                raise RuntimeError(f"SteamDT base error: {error_msg}")
            return data.get("data") or {}

        code = data.get("code")
        if code is not None and str(code) not in ("0", "200"):
            error_msg = data.get("message") or data.get("msg") or data.get("error") or "unknown_error"
            logger.error(f"[SteamDTBase] API error: {error_msg}")
            raise RuntimeError(f"SteamDT base error: {error_msg}")

        return data.get("data") or data

    @staticmethod
    def _extract_items(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if not isinstance(data, dict):
            return []

        for key in ("items", "list", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _has_more(data: Any, page: int, page_size: int, fetched: int) -> bool:
        if not isinstance(data, dict):
            return False

        if data.get("hasMore") is True or data.get("has_more") is True:
            return True

        next_page = data.get("nextPage") or data.get("next_page")
        if isinstance(next_page, int):
            return next_page > page

        total = data.get("total") or data.get("totalCount") or data.get("count")
        if isinstance(total, int) and page_size > 0:
            return page * page_size < total

        return False
