from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from backend.models import Item
from backend.scrapers.steam_scraper import SteamMarketScraper
from backend.services.price_service import PriceRecord, write_price
from backend.services.steamdt_price_service import fetch_steamdt_price_single, load_csqaq_goods_snapshot
from backend.services.wear_service import get_wear_by_inspect_url


STEAM_FEE_DIVISOR = 1.15


def normalize_steam_price(price: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    try:
        return round(float(price) / STEAM_FEE_DIVISOR, 2)
    except (TypeError, ValueError):
        return None


def should_enrich_wear(item: Item) -> bool:
    text = " ".join(
        [
            item.market_hash_name or "",
            item.type or "",
            item.weapon_type or "",
            item.skin_name or "",
        ]
    ).lower()
    keywords = ("glove", "knife", "dagger", "karambit", "bayonet", "m9", "手套", "刀", "匕首")
    return any(keyword in text for keyword in keywords)


def should_enrich_wear_by_name(item_name: Optional[str]) -> bool:
    text = (item_name or "").lower()
    keywords = ("glove", "knife", "dagger", "karambit", "bayonet", "m9", "手套", "刀", "匕首")
    return any(keyword in text for keyword in keywords)


def _steam_fetch_sync(item_name: str, use_proxy: bool) -> Optional[Dict[str, Any]]:
    with SteamMarketScraper(use_proxy=use_proxy) as scraper:
        return scraper.get_price(item_name)


def _steamdt_fetch_sync(item_id: int, item_name: str, use_cache: bool) -> Dict[str, Any]:
    return fetch_steamdt_price_single(item_id, item_name, use_cache=use_cache)


def _find_csqaq_row(
    rows: list[Dict[str, Any]],
    item_id: Optional[int],
    market_hash_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    if item_id is not None:
        for row in rows:
            try:
                if int(row.get("id")) == int(item_id):
                    return row
            except (TypeError, ValueError):
                continue

    normalized_name = (market_hash_name or "").strip().lower()
    if normalized_name:
        for row in rows:
            current_name = str(row.get("market_hash_name") or "").strip().lower()
            if current_name == normalized_name:
                return row

    return None


async def fetch_item_detail_from_csqaq(
    item_id: Optional[int] = None,
    market_hash_name: Optional[str] = None,
    inspect_url: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl: int = 86400,
) -> Optional[Dict[str, Any]]:
    rows = load_csqaq_goods_snapshot(use_cache=use_cache)
    row = _find_csqaq_row(rows, item_id=item_id, market_hash_name=market_hash_name)
    if not row:
        return None

    item_name = str(row.get("market_hash_name") or "").strip()
    display_name = str(row.get("name") or "").strip() or None
    row_item_id = row.get("id")
    updated_at = row.get("updated_at") or datetime.now(timezone.utc).isoformat()

    steam_price = row.get("steam_sell_price")
    buff_price = row.get("buff_sell_price")
    youpin_price = row.get("yyyp_sell_price")

    wear_requested = bool(inspect_url)
    wear_needed = should_enrich_wear_by_name(item_name)
    wear_result = None
    errors: Dict[str, str] = {}
    if wear_requested and inspect_url:
        try:
            wear_result = await asyncio.to_thread(
                get_wear_by_inspect_url,
                inspect_url,
                None,
                use_cache,
                cache_ttl,
            )
        except Exception as exc:
            errors["wear"] = str(exc)
    elif wear_needed:
        errors["wear"] = "inspectUrl is required for wear enrichment"

    return {
        "item_id": row_item_id if row_item_id is not None else item_id,
        "market_hash_name": item_name,
        "name_cn": display_name,
        "type": None,
        "weapon_type": None,
        "skin_name": None,
        "rarity": None,
        "quality": None,
        "image_url": None,
        "steam_url": None,
        "buff_url": None,
        "updated_at": updated_at,
        "prices": {
            "steam": {
                "price": steam_price,
                "net_price": normalize_steam_price(steam_price),
                "currency": "CNY",
                "volume": row.get("steam_sell_num"),
                "sell_listings": row.get("steam_sell_num"),
                "buy_orders": row.get("steam_buy_num"),
                "timestamp": updated_at,
                "status": "realtime" if steam_price is not None else "unavailable",
                "source": "csqaq_api",
            }
            if steam_price is not None
            else None,
            "buff": {
                "price": buff_price,
                "currency": "CNY",
                "volume": row.get("buff_sell_num"),
                "sell_listings": row.get("buff_sell_num"),
                "buy_orders": row.get("buff_buy_num"),
                "timestamp": updated_at,
                "status": "realtime" if buff_price is not None else "unavailable",
                "source": "csqaq_api",
            }
            if buff_price is not None
            else None,
            "youpin": {
                "price": youpin_price,
                "currency": "CNY",
                "volume": row.get("yyyp_sell_num"),
                "sell_listings": row.get("yyyp_sell_num"),
                "buy_orders": row.get("yyyp_buy_num"),
                "timestamp": updated_at,
                "status": "realtime" if youpin_price is not None else "unavailable",
                "source": "csqaq_api",
            }
            if youpin_price is not None
            else None,
        },
        "wear": wear_result,
        "wear_requested": wear_requested,
        "wear_needed": wear_needed,
        "errors": errors or None,
        "source": "csqaq_api",
        "item_source": "csqaq_api",
        "price_source": "csqaq_api",
    }


async def fetch_item_detail(
    item: Item,
    inspect_url: Optional[str],
    use_proxy: bool = True,
    persist: bool = False,
    use_cache: bool = True,
    cache_ttl: int = 86400,
) -> Dict[str, Any]:
    item_name = item.market_hash_name
    tasks = [
        asyncio.to_thread(_steam_fetch_sync, item_name, use_proxy),
        asyncio.to_thread(_steamdt_fetch_sync, item.id, item_name, use_cache),
    ]
    wear_task = None
    wear_needed = should_enrich_wear(item)
    wear_enabled = bool(inspect_url)
    if wear_enabled:
        wear_task = asyncio.to_thread(
            get_wear_by_inspect_url,
            inspect_url,
            None,
            use_cache,
            cache_ttl,
        )
        tasks.append(wear_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    steam_result = results[0]
    buff_result = results[1]
    wear_result = results[2] if wear_task is not None else None

    errors: Dict[str, str] = {}
    if isinstance(steam_result, Exception):
        errors["steam"] = str(steam_result)
        steam_result = None
    if isinstance(buff_result, Exception):
        errors["buff"] = str(buff_result)
        buff_result = None
    if wear_task is not None and isinstance(wear_result, Exception):
        errors["wear"] = str(wear_result)
        wear_result = None
    if wear_needed and not inspect_url:
        errors.setdefault("wear", "inspectUrl is required for wear enrichment")

    steam_price = None
    if steam_result:
        steam_price = steam_result.get("lowest_price")

    buff_price = None
    youpin_price = None
    buff_payload = None
    youpin_payload = None
    buff_data_source = None
    youpin_data_source = None
    if isinstance(buff_result, dict):
        buff_payload = buff_result.get("buff")
        youpin_payload = buff_result.get("youpin")
        buff_data_source = buff_result.get("buff_data_source")
        youpin_data_source = buff_result.get("youpin_data_source")
        if buff_payload:
            buff_price = buff_payload.get("price")
        if youpin_payload:
            youpin_price = youpin_payload.get("price")

    steam_net_price = normalize_steam_price(steam_price)

    if persist:
        try:
            if steam_price is not None:
                write_price(
                    PriceRecord(
                        item_name=item_name,
                        platform="steam",
                        price=steam_price,
                        currency=steam_result.get("currency", "CNY") if steam_result else "CNY",
                        volume=steam_result.get("volume") if steam_result else None,
                        time=steam_result.get("timestamp") if steam_result else None,
                        data_source="scraper",
                    )
                )
            if buff_price is not None:
                write_price(
                    PriceRecord(
                        item_name=item_name,
                        platform="buff",
                        price=buff_price,
                        currency=buff_payload.get("currency", "CNY") if buff_payload else "CNY",
                        volume=buff_payload.get("volume") if buff_payload else None,
                        sell_listings=buff_payload.get("sell_listings") if buff_payload else None,
                        buy_orders=buff_payload.get("buy_orders") if buff_payload else None,
                        time=buff_payload.get("timestamp") if buff_payload else None,
                        data_source=buff_data_source or "direct_scraper",
                    )
                )
            if youpin_price is not None:
                write_price(
                    PriceRecord(
                        item_name=item_name,
                        platform="youpin",
                        price=youpin_price,
                        currency=youpin_payload.get("currency", "CNY") if youpin_payload else "CNY",
                        volume=youpin_payload.get("volume") if youpin_payload else None,
                        sell_listings=youpin_payload.get("sell_listings") if youpin_payload else None,
                        time=youpin_payload.get("timestamp") if youpin_payload else None,
                        data_source=youpin_data_source or "steamdt",
                    )
                )
        except Exception as exc:
            logger.warning("Item detail persist failed: {}", exc)

    return {
        "item_id": item.id,
        "market_hash_name": item.market_hash_name,
        "name_cn": item.name_cn,
        "type": item.type,
        "weapon_type": item.weapon_type,
        "skin_name": item.skin_name,
        "rarity": item.rarity,
        "quality": item.quality,
        "image_url": item.image_url,
        "steam_url": item.steam_url,
        "buff_url": item.buff_url,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "prices": {
            "steam": {
                "price": steam_price,
                "net_price": steam_net_price,
                "currency": steam_result.get("currency") if steam_result else None,
                "volume": steam_result.get("volume") if steam_result else None,
                "timestamp": steam_result.get("timestamp") if steam_result else None,
            }
            if steam_result
            else None,
            "buff": {
                "price": buff_price,
                "currency": buff_payload.get("currency") if buff_payload else None,
                "volume": buff_payload.get("volume") if buff_payload else None,
                "sell_listings": buff_payload.get("sell_listings") if buff_payload else None,
                "buy_orders": buff_payload.get("buy_orders") if buff_payload else None,
                "timestamp": buff_payload.get("timestamp") if buff_payload else None,
                "status": buff_result.get("status") if isinstance(buff_result, dict) else None,
            }
            if buff_payload or isinstance(buff_result, dict)
            else None,
            "youpin": {
                "price": youpin_price,
                "currency": youpin_payload.get("currency") if youpin_payload else None,
                "volume": youpin_payload.get("volume") if youpin_payload else None,
                "sell_listings": youpin_payload.get("sell_listings") if youpin_payload else None,
                "timestamp": youpin_payload.get("timestamp") if youpin_payload else None,
                "status": buff_result.get("status") if isinstance(buff_result, dict) else None,
            }
            if youpin_payload or isinstance(buff_result, dict)
            else None,
        },
        "wear": wear_result,
        "wear_requested": wear_enabled,
        "wear_needed": wear_needed,
        "errors": errors or None,
    }
