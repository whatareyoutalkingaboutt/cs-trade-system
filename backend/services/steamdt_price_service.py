from __future__ import annotations

import os
import time
import gc
from typing import Any, Dict, Optional

from loguru import logger

from backend.core.cache import (
    acquire_lock,
    append_csqaq_metric_points,
    get_json,
    get_latest_price,
    get_value,
    release_lock,
    set_json,
    set_value,
)
from backend.scrapers.buff_scraper import BuffScraper
from backend.scrapers.csqaq_scraper import CSQAQRateLimitError, CSQAQScraper
from backend.scrapers.steamdt_price_scraper import SteamDTPriceScraper
from backend.scrapers.youpin_scraper import YoupinScraper
from backend.services.price_service import PriceRecord, write_price
from backend.services.quota_service import reserve_price_single, release_price_single

PRICE_PRIMARY_SOURCE = os.getenv("PRICE_PRIMARY_SOURCE", "csqaq").strip().lower()
CSQAQ_PRIMARY_ENABLED = os.getenv("CSQAQ_PRIMARY_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CSQAQ_PRICE_CACHE_KEY = "csqaq:goods_info:cache"
CSQAQ_PRICE_STALE_KEY = "csqaq:goods_info:stale"
CSQAQ_PRICE_CACHE_TTL_SECONDS = int(os.getenv("CSQAQ_PRICE_CACHE_TTL_SECONDS", "300"))
CSQAQ_PRICE_STALE_TTL_SECONDS = int(os.getenv("CSQAQ_PRICE_STALE_TTL_SECONDS", "86400"))
CSQAQ_REFRESH_LOCK_KEY = "lock:csqaq:goods_info:refresh"
CSQAQ_REFRESH_LOCK_TTL_SECONDS = int(os.getenv("CSQAQ_REFRESH_LOCK_TTL_SECONDS", "30"))
CSQAQ_COOLDOWN_KEY = "quota:csqaq:get_all_goods_info:cooldown"
CSQAQ_COOLDOWN_SECONDS = int(os.getenv("CSQAQ_COOLDOWN_SECONDS", "300"))


def _cached_platform_price(item_id: int, platform: str) -> Optional[Dict[str, Any]]:
    payload = get_latest_price(item_id, platform=platform)
    if not payload:
        return None
    try:
        return {
            "price": float(payload.get("price", 0)),
            "currency": payload.get("currency"),
            "timestamp": payload.get("timestamp"),
            "volume": int(payload.get("volume")) if payload.get("volume") is not None else None,
            "sell_listings": int(payload.get("sell_listings")) if payload.get("sell_listings") is not None else None,
            "buy_orders": int(payload.get("buy_orders")) if payload.get("buy_orders") is not None else None,
        }
    except Exception:
        return None


def _has_csqaq_token() -> bool:
    token = os.getenv("CSQAQ_API_TOKEN") or os.getenv("CSQAQ_TOKEN")
    return bool(token and token.strip())


def _use_csqaq_primary() -> bool:
    return (
        PRICE_PRIMARY_SOURCE == "csqaq"
        and CSQAQ_PRIMARY_ENABLED
        and _has_csqaq_token()
    )


def _normalize_csqaq_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    item_id = row.get("id")
    market_hash_name = str(row.get("market_hash_name") or "").strip()
    if item_id is None or not market_hash_name:
        return None
    return {
        "id": int(item_id),
        "market_hash_name": market_hash_name,
        "name": row.get("name"),
        "buff_sell_price": row.get("buff_sell_price"),
        "buff_buy_price": row.get("buff_buy_price"),
        "buff_sell_num": row.get("buff_sell_num"),
        "buff_buy_num": row.get("buff_buy_num"),
        "steam_sell_price": row.get("steam_sell_price"),
        "steam_sell_num": row.get("steam_sell_num"),
        "steam_buy_num": row.get("steam_buy_num"),
        "yyyp_sell_price": row.get("yyyp_sell_price"),
        "yyyp_buy_price": row.get("yyyp_buy_price"),
        "yyyp_sell_num": row.get("yyyp_sell_num"),
        "yyyp_buy_num": row.get("yyyp_buy_num"),
        "updated_at": row.get("updated_at") or row.get("statistic_at"),
    }


def _build_csqaq_price_index(rows: list[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        normalized = _normalize_csqaq_row(row)
        if not normalized:
            continue
        row_id = str(normalized["id"])
        name = normalized["market_hash_name"]
        by_id[row_id] = normalized
        by_name[name] = normalized
        by_name[name.lower()] = normalized

    return {"by_id": by_id, "by_name": by_name}


def _get_csqaq_index(cache_key: str) -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
    payload = get_json(cache_key)
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("by_id"), dict) or not isinstance(payload.get("by_name"), dict):
        return None
    return payload


def _get_cached_csqaq_index() -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
    return _get_csqaq_index(CSQAQ_PRICE_CACHE_KEY)


def _get_stale_csqaq_index() -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
    return _get_csqaq_index(CSQAQ_PRICE_STALE_KEY)


def load_csqaq_goods_snapshot(use_cache: bool = True) -> list[Dict[str, Any]]:
    snapshot = _get_cached_csqaq_index() if use_cache else None
    if snapshot is None:
        if get_value(CSQAQ_COOLDOWN_KEY):
            snapshot = _get_stale_csqaq_index()
        else:
            snapshot = _refresh_csqaq_index()

    if not snapshot:
        return []
    by_id = snapshot.get("by_id") or {}
    if not isinstance(by_id, dict):
        return []
    return [row for row in by_id.values() if isinstance(row, dict)]


def _save_csqaq_index(payload: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
    set_json(CSQAQ_PRICE_CACHE_KEY, payload, ttl=CSQAQ_PRICE_CACHE_TTL_SECONDS)
    set_json(CSQAQ_PRICE_STALE_KEY, payload, ttl=CSQAQ_PRICE_STALE_TTL_SECONDS)
    _record_csqaq_snapshot_series(payload)


def _record_csqaq_snapshot_series(payload: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
    by_id = payload.get("by_id") or {}
    if not isinstance(by_id, dict):
        return

    points: list[dict] = []
    for row in by_id.values():
        if not isinstance(row, dict):
            continue
        try:
            item_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue

        timestamp = row.get("updated_at")
        if not timestamp:
            continue

        buff_sell_num = row.get("buff_sell_num")
        if buff_sell_num is not None:
            try:
                points.append(
                    {
                        "item_id": item_id,
                        "platform": "buff",
                        "metric": "sell_listings",
                        "time": timestamp,
                        "value": float(buff_sell_num),
                    }
                )
            except (TypeError, ValueError):
                pass

        buff_buy_price = row.get("buff_buy_price")
        if buff_buy_price is not None:
            try:
                points.append(
                    {
                        "item_id": item_id,
                        "platform": "buff",
                        "metric": "bid_price",
                        "time": timestamp,
                        "value": float(buff_buy_price),
                    }
                )
            except (TypeError, ValueError):
                pass

        youpin_sell_num = row.get("yyyp_sell_num")
        if youpin_sell_num is not None:
            try:
                points.append(
                    {
                        "item_id": item_id,
                        "platform": "youpin",
                        "metric": "sell_listings",
                        "time": timestamp,
                        "value": float(youpin_sell_num),
                    }
                )
            except (TypeError, ValueError):
                pass

        youpin_buy_price = row.get("yyyp_buy_price")
        if youpin_buy_price is not None:
            try:
                points.append(
                    {
                        "item_id": item_id,
                        "platform": "youpin",
                        "metric": "bid_price",
                        "time": timestamp,
                        "value": float(youpin_buy_price),
                    }
                )
            except (TypeError, ValueError):
                pass

    if points:
        append_csqaq_metric_points(points)


def _refresh_csqaq_index() -> Optional[Dict[str, Dict[str, Dict[str, Any]]]]:
    token = acquire_lock(CSQAQ_REFRESH_LOCK_KEY, ttl_seconds=CSQAQ_REFRESH_LOCK_TTL_SECONDS)
    if not token:
        return _get_cached_csqaq_index() or _get_stale_csqaq_index()
    rows: list[Dict[str, Any]] = []

    try:
        with CSQAQScraper() as scraper:
            rows = scraper.get_all_goods_info()
        payload = _build_csqaq_price_index(rows)
        if payload.get("by_id"):
            _save_csqaq_index(payload)
        return payload
    except CSQAQRateLimitError as exc:
        cooldown = max(CSQAQ_COOLDOWN_SECONDS, int(exc.cooldown_seconds))
        set_value(CSQAQ_COOLDOWN_KEY, str(int(time.time())), ttl_seconds=cooldown)
        logger.warning("CSQAQ get_all_goods_info rate limited: {}", exc)
        return _get_stale_csqaq_index()
    except Exception as exc:
        logger.warning("CSQAQ get_all_goods_info failed: {}", exc)
        return _get_stale_csqaq_index()
    finally:
        # 响应体巨大，转换索引后立刻释放，降低 2C2G 下驻留峰值。
        rows.clear()
        gc.collect()
        release_lock(CSQAQ_REFRESH_LOCK_KEY, token)


def _row_to_platform_payloads(row: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    timestamp = row.get("updated_at")

    buff_payload = None
    if row.get("buff_sell_price") is not None:
        buff_payload = {
            "lowest_price": row.get("buff_sell_price"),
            "volume": row.get("buff_sell_num"),
            "sell_listings": row.get("buff_sell_num"),
            "buy_orders": row.get("buff_buy_num"),
            "timestamp": timestamp,
            "currency": "CNY",
        }

    youpin_payload = None
    if row.get("yyyp_sell_price") is not None:
        youpin_payload = {
            "lowest_price": row.get("yyyp_sell_price"),
            "volume": row.get("yyyp_sell_num"),
            "sell_listings": row.get("yyyp_sell_num"),
            "buy_orders": row.get("yyyp_buy_num"),
            "timestamp": timestamp,
            "currency": "CNY",
        }

    return {"buff": buff_payload, "youpin": youpin_payload}


def _fetch_csqaq_price_single(
    item_id: int,
    item_name: str,
    use_cache: bool = True,
) -> Optional[Dict[str, Any]]:
    snapshot = _get_cached_csqaq_index() if use_cache else None
    if snapshot is None:
        if get_value(CSQAQ_COOLDOWN_KEY):
            snapshot = _get_stale_csqaq_index()
        else:
            snapshot = _refresh_csqaq_index()

    if not snapshot:
        return None

    row = snapshot["by_id"].get(str(item_id))
    if row is None:
        normalized_name = (item_name or "").strip()
        row = snapshot["by_name"].get(normalized_name) or snapshot["by_name"].get(normalized_name.lower())
    if row is None:
        return None

    platform_payloads = _row_to_platform_payloads(row)
    if not platform_payloads.get("buff") and not platform_payloads.get("youpin"):
        return None

    return {
        "buff": {
            "price": platform_payloads["buff"].get("lowest_price"),
            "currency": platform_payloads["buff"].get("currency", "CNY"),
            "timestamp": platform_payloads["buff"].get("timestamp"),
            "volume": platform_payloads["buff"].get("volume"),
            "sell_listings": platform_payloads["buff"].get("sell_listings"),
            "buy_orders": platform_payloads["buff"].get("buy_orders"),
        }
        if platform_payloads.get("buff")
        else None,
        "youpin": {
            "price": platform_payloads["youpin"].get("lowest_price"),
            "currency": platform_payloads["youpin"].get("currency", "CNY"),
            "timestamp": platform_payloads["youpin"].get("timestamp"),
            "volume": platform_payloads["youpin"].get("volume"),
            "sell_listings": platform_payloads["youpin"].get("sell_listings"),
            "buy_orders": platform_payloads["youpin"].get("buy_orders"),
        }
        if platform_payloads.get("youpin")
        else None,
        "source": "csqaq",
        "status": "realtime",
        "buff_data_source": "csqaq_api",
        "youpin_data_source": "csqaq_api",
    }


def _persist_platform_prices(
    item_id: int,
    buff_data: Optional[Dict[str, Any]],
    buff_source: str,
    youpin_data: Optional[Dict[str, Any]],
    youpin_source: str,
) -> None:
    if buff_data:
        write_price(
            PriceRecord(
                item_id=item_id,
                platform="buff",
                price=buff_data.get("lowest_price") or 0.0,
                currency=buff_data.get("currency", "CNY"),
                volume=buff_data.get("volume"),
                sell_listings=buff_data.get("sell_listings"),
                buy_orders=buff_data.get("buy_orders"),
                time=buff_data.get("timestamp"),
                data_source=buff_source,
            )
        )
    if youpin_data:
        write_price(
            PriceRecord(
                item_id=item_id,
                platform="youpin",
                price=youpin_data.get("lowest_price") or 0.0,
                currency=youpin_data.get("currency", "CNY"),
                volume=youpin_data.get("volume"),
                sell_listings=youpin_data.get("sell_listings"),
                time=youpin_data.get("timestamp"),
                data_source=youpin_source,
            )
        )


def _fetch_with_legacy_sources(
    item_id: int,
    item_name: str,
) -> Dict[str, Any]:
    buff_data = None
    youpin_data = None
    youpin_data_source = None

    try:
        with BuffScraper() as scraper:
            buff_data = scraper.get_price(item_name, item_id=item_id)
    except Exception as exc:
        logger.warning("Buff direct scrape failed: {}", exc)

    try:
        with YoupinScraper() as scraper:
            youpin_direct = scraper.get_price(item_name, item_id=item_id)
            if youpin_direct and youpin_direct.get("lowest_price") is not None:
                youpin_data = {
                    "lowest_price": youpin_direct.get("lowest_price"),
                    "volume": youpin_direct.get("volume"),
                    "sell_listings": youpin_direct.get("sell_listings"),
                    "timestamp": youpin_direct.get("timestamp"),
                    "currency": youpin_direct.get("currency", "CNY"),
                }
                youpin_data_source = "direct_scraper"
    except Exception as exc:
        logger.warning("Youpin direct scrape failed: {}", exc)

    steamdt_data = None
    if youpin_data is None:
        try:
            with SteamDTPriceScraper() as scraper:
                steamdt_data = scraper.get_price(item_name)
        except Exception as exc:
            logger.warning("SteamDT price fetch failed: {}", exc)

        if steamdt_data and steamdt_data.get("youpin_price") is not None:
            youpin_data = {
                "lowest_price": steamdt_data.get("youpin_price"),
                "volume": steamdt_data.get("youpin_volume"),
                "timestamp": steamdt_data.get("timestamp"),
                "currency": steamdt_data.get("currency", "CNY"),
            }
            youpin_data_source = "steamdt"

    if not buff_data and not youpin_data:
        return {
            "buff": None,
            "youpin": None,
            "source": "mixed",
            "status": "failed",
            "buff_data_source": None,
            "youpin_data_source": None,
        }

    _persist_platform_prices(
        item_id=item_id,
        buff_data=buff_data,
        buff_source="direct_scraper",
        youpin_data=youpin_data,
        youpin_source=youpin_data_source or "steamdt",
    )

    return {
        "buff": {
            "price": buff_data.get("lowest_price"),
            "currency": buff_data.get("currency", "CNY"),
            "timestamp": buff_data.get("timestamp"),
            "volume": buff_data.get("volume"),
            "sell_listings": buff_data.get("sell_listings"),
            "buy_orders": buff_data.get("buy_orders"),
        }
        if buff_data
        else None,
        "youpin": {
            "price": youpin_data.get("lowest_price"),
            "currency": youpin_data.get("currency", "CNY"),
            "timestamp": youpin_data.get("timestamp"),
            "volume": youpin_data.get("volume"),
            "sell_listings": youpin_data.get("sell_listings"),
        }
        if youpin_data
        else None,
        "source": "mixed",
        "status": "realtime",
        "buff_data_source": "direct_scraper" if buff_data else None,
        "youpin_data_source": youpin_data_source,
    }


def fetch_steamdt_price_single(
    item_id: int,
    item_name: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    if use_cache:
        buff_cached = _cached_platform_price(item_id, "buff")
        youpin_cached = _cached_platform_price(item_id, "youpin")
        if buff_cached or youpin_cached:
            return {
                "buff": buff_cached,
                "youpin": youpin_cached,
                "source": "cache",
                "status": "cached",
                "buff_data_source": "cache" if buff_cached else None,
                "youpin_data_source": "cache" if youpin_cached else None,
            }

    token, status = reserve_price_single(item_name)
    if not token:
        return {
            "buff": None,
            "youpin": None,
            "source": "mixed",
            "status": status,
            "buff_data_source": None,
            "youpin_data_source": None,
        }

    try:
        if _use_csqaq_primary():
            csqaq_result = _fetch_csqaq_price_single(item_id=item_id, item_name=item_name, use_cache=use_cache)
            if csqaq_result and (csqaq_result.get("buff") or csqaq_result.get("youpin")):
                buff_payload = csqaq_result.get("buff")
                youpin_payload = csqaq_result.get("youpin")
                _persist_platform_prices(
                    item_id=item_id,
                    buff_data={
                        "lowest_price": buff_payload.get("price"),
                        "volume": buff_payload.get("volume"),
                        "sell_listings": buff_payload.get("sell_listings"),
                        "buy_orders": buff_payload.get("buy_orders"),
                        "timestamp": buff_payload.get("timestamp"),
                        "currency": buff_payload.get("currency", "CNY"),
                    }
                    if buff_payload
                    else None,
                    buff_source="csqaq_api",
                    youpin_data={
                        "lowest_price": youpin_payload.get("price"),
                        "volume": youpin_payload.get("volume"),
                        "sell_listings": youpin_payload.get("sell_listings"),
                        "buy_orders": youpin_payload.get("buy_orders"),
                        "timestamp": youpin_payload.get("timestamp"),
                        "currency": youpin_payload.get("currency", "CNY"),
                    }
                    if youpin_payload
                    else None,
                    youpin_source="csqaq_api",
                )
                return csqaq_result

        return _fetch_with_legacy_sources(item_id=item_id, item_name=item_name)
    except Exception as exc:
        logger.warning("Direct price single failed: {}", exc)
        return {
            "buff": None,
            "youpin": None,
            "source": "mixed",
            "status": "failed",
            "buff_data_source": None,
            "youpin_data_source": None,
        }
    finally:
        if token:
            release_price_single(item_name, token)
