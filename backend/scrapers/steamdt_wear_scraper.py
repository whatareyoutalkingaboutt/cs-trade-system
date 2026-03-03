#!/usr/bin/env python3
"""
SteamDT wear/inspect scraper

Endpoints:
- /open/cs2/v1/wear
- /open/cs2/v1/inspect
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

import requests
from loguru import logger

from .base_scraper import BaseScraper, rate_limit, retry


class SteamDTWearScraper(BaseScraper):
    """SteamDT wear/inspect API client."""

    BASE_URL = "https://open.steamdt.com/open/cs2/v1"
    WEAR_ENDPOINT = "/wear"
    INSPECT_ENDPOINT = "/inspect"

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
        timeout: int = 10,
        rate_limit_seconds: float = 0.2,
    ):
        super().__init__(
            platform_name="steamdt_wear",
            use_proxy=False,
            timeout=timeout,
            rate_limit_seconds=rate_limit_seconds,
        )

        if api_key:
            candidate_keys = [api_key]
        else:
            candidate_keys = self._load_api_keys()

        candidate_keys = [key for key in candidate_keys if key.isascii()]
        if candidate_keys:
            key_index = 0
            key_index_raw = os.getenv("STEAMDT_API_KEY_INDEX")
            if key_index_raw:
                try:
                    key_index = max(0, int(key_index_raw))
                except ValueError:
                    key_index = 0
            self.api_key = candidate_keys[key_index % len(candidate_keys)]
        else:
            self.api_key = None

        if not self.api_key:
            logger.warning("[SteamDTWear] Missing STEAMDT_API_KEY; requests will fail.")
        else:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )

    def get_price(self, item_name: str) -> Optional[Dict[str, Any]]:
        logger.warning("[SteamDTWear] get_price is not supported in this scraper.")
        self._update_stats(success=False)
        return None

    def test_connection(self) -> bool:
        if not self.api_key:
            logger.error("[SteamDTWear] Missing API key; cannot test connection.")
            return False

        sample = os.getenv("STEAMDT_TEST_INSPECT_URL")
        if not sample:
            logger.warning("[SteamDTWear] STEAMDT_TEST_INSPECT_URL not set; skipping live test.")
            return True

        result = self.get_wear_by_inspect_url(sample)
        return result is not None

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(0.2)
    def get_wear_by_inspect_url(
        self,
        inspect_url: str,
        notify_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch wear data by inspect URL."""
        payload = {"inspectUrl": inspect_url}
        if notify_url:
            payload["notifyUrl"] = notify_url
        return self._post_json(self.WEAR_ENDPOINT, payload, inspect_url)

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    @rate_limit(0.2)
    def get_inspect_image_by_inspect_url(
        self,
        inspect_url: str,
        notify_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch inspect image data by inspect URL (requires wear already fetched)."""
        payload = {"inspectUrl": inspect_url}
        if notify_url:
            payload["notifyUrl"] = notify_url
        return self._post_json(self.INSPECT_ENDPOINT, payload, inspect_url)

    def _post_json(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        inspect_url: str,
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            logger.error("[SteamDTWear] API key not configured.")
            self._update_stats(success=False)
            return None

        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout:
            logger.error("[SteamDTWear] Request timed out.")
            self._update_stats(success=False)
            return None
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.error(f"[SteamDTWear] HTTP error: {status}")
            self._update_stats(success=False)
            return None
        except requests.exceptions.RequestException as exc:
            logger.error(f"[SteamDTWear] Request failed: {exc}")
            self._update_stats(success=False)
            return None
        except Exception as exc:
            logger.error(f"[SteamDTWear] Unexpected error: {exc}")
            self._update_stats(success=False)
            return None

        payload_data = self._extract_payload(data)
        if payload_data is None:
            self._update_stats(success=False)
            return None

        result = self._normalize_payload(payload_data, inspect_url)
        self._update_stats(success=True)
        return result

    def _extract_payload(self, data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            logger.error("[SteamDTWear] Invalid response payload.")
            return None

        if "success" in data:
            if not data.get("success"):
                error_msg = data.get("errorMsg") or data.get("message") or "unknown_error"
                logger.error(f"[SteamDTWear] API error: {error_msg}")
                return None
            return data.get("data") or {}

        code = data.get("code")
        if code is not None and str(code) not in ("0", "200"):
            error_msg = data.get("message") or data.get("msg") or data.get("error") or "unknown_error"
            logger.error(f"[SteamDTWear] API error: {error_msg}")
            return None

        return data.get("data") or data

    def _normalize_payload(self, payload: Dict[str, Any], inspect_url: str) -> Dict[str, Any]:
        return {
            "inspect_url": inspect_url,
            "float_value": self._get_first_number(payload, [
                "float", "floatValue", "float_value", "wear", "wearValue", "paintwear"
            ]),
            "paint_seed": self._get_first_number(payload, [
                "paintseed", "paint_seed", "paintSeed", "seed"
            ]),
            "paint_index": self._get_first_number(payload, [
                "paintindex", "paint_index", "paintIndex", "index"
            ]),
            "wear_category": self._get_first_string(payload, [
                "wearCategory", "wear_category", "wearType", "wear_type"
            ]),
            "image_url": self._get_first_string(payload, [
                "image", "imageUrl", "image_url", "url"
            ]),
            "timestamp": datetime.now().isoformat(),
            "raw": payload,
        }

    @staticmethod
    def _get_first_number(data: Dict[str, Any], keys: Sequence[str]) -> Optional[float]:
        for key in keys:
            if key in data:
                value = data.get(key)
                try:
                    if value is None:
                        continue
                    return float(str(value).replace(",", "").strip())
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _get_first_string(data: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            if key in data:
                value = data.get(key)
                if value is None:
                    continue
                return str(value)
        return None


if __name__ == "__main__":
    from dotenv import load_dotenv
    import sys

    load_dotenv()

    logger.remove()
    logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}")

    inspect_url = os.getenv("STEAMDT_TEST_INSPECT_URL")
    if not inspect_url:
        logger.error("STEAMDT_TEST_INSPECT_URL is not set.")
        sys.exit(1)

    with SteamDTWearScraper() as scraper:
        if not scraper.test_connection():
            logger.error("Connection test failed.")
            sys.exit(1)

        wear_data = scraper.get_wear_by_inspect_url(inspect_url)
        logger.info(f"Wear data: {wear_data}")

        inspect_data = scraper.get_inspect_image_by_inspect_url(inspect_url)
        logger.info(f"Inspect data: {inspect_data}")
