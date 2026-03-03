from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from loguru import logger

from backend.core.cache import get_json, set_json
from backend.services.quota_service import reserve_inspect, reserve_wear
from backend.scrapers.steamdt_wear_scraper import SteamDTWearScraper

WEAR_CACHE_TTL_SECONDS = 86400
INSPECT_CACHE_TTL_SECONDS = 86400


def _hash_key(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _wear_cache_key(inspect_url: str) -> str:
    return f"wear:inspect:{_hash_key(inspect_url)}"


def _inspect_cache_key(inspect_url: str) -> str:
    return f"inspect:image:{_hash_key(inspect_url)}"


def get_wear_by_inspect_url(
    inspect_url: str,
    notify_url: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl: int = WEAR_CACHE_TTL_SECONDS,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if use_cache:
        try:
            cached = get_json(_wear_cache_key(inspect_url))
        except Exception as exc:
            logger.warning("Wear cache read failed: {}", exc)
            cached = None
        if cached is not None:
            return cached

    if not reserve_wear(_hash_key(inspect_url)):
        logger.warning("Wear quota hit for inspect_url: {}", inspect_url)
        return None

    with SteamDTWearScraper(api_key=api_key) as scraper:
        result = scraper.get_wear_by_inspect_url(inspect_url, notify_url=notify_url)

    if result is not None and use_cache:
        try:
            set_json(_wear_cache_key(inspect_url), result, ttl=cache_ttl)
        except Exception as exc:
            logger.warning("Wear cache write failed: {}", exc)

    return result


def get_inspect_image_by_inspect_url(
    inspect_url: str,
    notify_url: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl: int = INSPECT_CACHE_TTL_SECONDS,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if use_cache:
        try:
            cached = get_json(_inspect_cache_key(inspect_url))
        except Exception as exc:
            logger.warning("Inspect cache read failed: {}", exc)
            cached = None
        if cached is not None:
            return cached

    allowed, count = reserve_inspect()
    if not allowed:
        logger.warning("Inspect quota exhausted: {}", count)
        return None

    with SteamDTWearScraper(api_key=api_key) as scraper:
        result = scraper.get_inspect_image_by_inspect_url(inspect_url, notify_url=notify_url)

    if result is not None and use_cache:
        try:
            set_json(_inspect_cache_key(inspect_url), result, ttl=cache_ttl)
        except Exception as exc:
            logger.warning("Inspect cache write failed: {}", exc)

    return result
