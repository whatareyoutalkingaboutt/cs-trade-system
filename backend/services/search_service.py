from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import or_

from backend.core.cache import (
    cache_search_results,
    get_cached_search_results,
    get_hot_items_by_score,
    record_hot_items,
)
from backend.core.database import get_sessionmaker
from backend.models import Item
from backend.scrapers.steam_scraper import SteamMarketScraper
from backend.services.currency_service import convert_to_cny
from backend.services.item_detail_service import normalize_steam_price, should_enrich_wear
from backend.services.steamdt_price_service import fetch_steamdt_price_single, load_csqaq_goods_snapshot
from backend.services.wear_service import get_wear_by_inspect_url


BUFF_FEE_DIVISOR = 1.025
YOUPIN_FEE_DIVISOR = 1.025
SEARCH_ITEMS_SOURCE = os.getenv("SEARCH_ITEMS_SOURCE", "csqaq").strip().lower()
CSQAQ_PURE_SEARCH = os.getenv("CSQAQ_PURE_SEARCH", "true").strip().lower() in {"1", "true", "yes", "on"}

WEAR_ORDER = {
    "factory new": 0,
    "minimal wear": 1,
    "field-tested": 2,
    "well-worn": 3,
    "battle-scarred": 4,
    "崭新出厂": 0,
    "略有磨损": 1,
    "久经沙场": 2,
    "破损不堪": 3,
    "战痕累累": 4,
}
WEAR_PATTERN = re.compile(r"[（(]([^()（）]*)[）)]$")


def _platform_source_label(source: Optional[str], default_label: str) -> str:
    mapping = {
        "cache": "Cache",
        "direct_scraper": "Direct Scraper",
        "steamdt": "SteamDT API",
        "csqaq_api": "CSQAQ API",
    }
    if not source:
        return default_label
    return mapping.get(source, default_label)


def _use_csqaq_search() -> bool:
    return SEARCH_ITEMS_SOURCE == "csqaq" and CSQAQ_PURE_SEARCH


def _detect_price_source(payload_list: List[Dict[str, Any]]) -> Optional[str]:
    labels = set()
    for payload in payload_list:
        platforms = payload.get("platforms") or {}
        for platform_key in ("buff", "youyou"):
            platform_data = platforms.get(platform_key)
            if not isinstance(platform_data, dict):
                continue
            source_label = platform_data.get("source")
            if source_label:
                labels.add(str(source_label))

    if "CSQAQ API" in labels:
        return "csqaq_api"
    if "SteamDT API" in labels:
        return "steamdt_api"
    if "Direct Scraper" in labels:
        return "direct_scraper"
    if "Cache" in labels and len(labels) == 1:
        return "cache"
    return None


def _net_price(price: Optional[float], divisor: float) -> Optional[float]:
    if price is None:
        return None
    try:
        return round(float(price) / divisor, 2)
    except (TypeError, ValueError):
        return None


def _wear_rank(item: Item) -> int:
    candidates = [item.market_hash_name or "", item.name_cn or ""]
    for value in candidates:
        match = WEAR_PATTERN.search(value.strip())
        if not match:
            continue
        wear_text = match.group(1).strip().lower()
        if wear_text in WEAR_ORDER:
            return WEAR_ORDER[wear_text]
    return 99


def _steam_fetch_sync(item_name: str, use_proxy: bool) -> Optional[Dict[str, Any]]:
    with SteamMarketScraper(use_proxy=use_proxy) as scraper:
        return scraper.get_price(item_name)


async def _build_item_payload(
    item: Item,
    inspect_url: Optional[str],
    use_proxy: bool,
    use_cache: bool,
) -> Dict[str, Any]:
    steam_task = asyncio.to_thread(_steam_fetch_sync, item.market_hash_name, use_proxy)
    steamdt_task = asyncio.to_thread(fetch_steamdt_price_single, item.id, item.market_hash_name, use_cache)

    wear_task = None
    wear_needed = should_enrich_wear(item)
    if inspect_url and wear_needed:
        wear_task = asyncio.to_thread(get_wear_by_inspect_url, inspect_url, None, use_cache, 3600)

    results = await asyncio.gather(
        steam_task,
        steamdt_task,
        wear_task if wear_task is not None else asyncio.sleep(0, result=None),
        return_exceptions=True,
    )

    steam_result = results[0] if not isinstance(results[0], Exception) else None
    steamdt_result = results[1] if not isinstance(results[1], Exception) else {}
    wear_result = results[2] if not isinstance(results[2], Exception) else None

    steam_price_raw = None
    steam_currency = None
    steam_timestamp = None
    if steam_result:
        steam_price_raw = steam_result.get("lowest_price")
        steam_currency = steam_result.get("currency")
        steam_timestamp = steam_result.get("timestamp")

    steam_price_cny = convert_to_cny(steam_price_raw, steam_currency)
    steam_net_price = normalize_steam_price(steam_price_cny)

    steamdt_status = steamdt_result.get("status") if isinstance(steamdt_result, dict) else None
    buff_payload = steamdt_result.get("buff") if isinstance(steamdt_result, dict) else None
    buff_data_source = steamdt_result.get("buff_data_source") if isinstance(steamdt_result, dict) else None
    youpin_payload = steamdt_result.get("youpin") if isinstance(steamdt_result, dict) else None
    youpin_data_source = steamdt_result.get("youpin_data_source") if isinstance(steamdt_result, dict) else None

    buff_price = convert_to_cny(buff_payload.get("price"), buff_payload.get("currency")) if buff_payload else None
    youpin_price = convert_to_cny(youpin_payload.get("price"), youpin_payload.get("currency")) if youpin_payload else None

    platforms = {
        "steam": {
            "raw_price": steam_price_cny,
            "net_price": steam_net_price,
            "link": item.steam_url,
            "last_update": steam_timestamp,
            "status": "realtime" if steam_result else "unavailable",
            "source": "VPN Scraper",
        },
        "buff": {
            "raw_price": buff_price,
            "net_price": _net_price(buff_price, BUFF_FEE_DIVISOR),
            "link": item.buff_url,
            "last_update": buff_payload.get("timestamp") if buff_payload else None,
            "status": steamdt_status or "unavailable",
            "source": _platform_source_label(buff_data_source, "Direct Scraper"),
        }
        if buff_payload or steamdt_status
        else None,
        "youyou": {
            "raw_price": youpin_price,
            "net_price": _net_price(youpin_price, YOUPIN_FEE_DIVISOR),
            "link": item.buff_url,
            "last_update": youpin_payload.get("timestamp") if youpin_payload else None,
            "status": steamdt_status or "unavailable",
            "source": _platform_source_label(youpin_data_source, "SteamDT API"),
        }
        if youpin_payload or steamdt_status
        else None,
    }
    platforms["steam_official"] = platforms.get("steam")

    best_arbitrage = _calculate_best_arbitrage(platforms)

    wear_data = None
    if inspect_url and wear_result:
        wear_data = {
            "min_wear": None,
            "max_wear": None,
            "current_lowest_wear": wear_result.get("float_value"),
            "wear_rank": None,
            "source": "SteamDT v1/wear",
        }
    elif wear_needed and not inspect_url:
        wear_data = {
            "min_wear": None,
            "max_wear": None,
            "current_lowest_wear": None,
            "wear_rank": None,
            "source": None,
        }

    return {
        "item_name": item.market_hash_name,
        "display_name": item.name_cn or item.market_hash_name,
        "item_id": str(item.id),
        "base_info": {
            "image": item.image_url,
            "category": item.weapon_type or item.type,
            "rarity": item.rarity,
            "name_cn": item.name_cn,
        },
        "wear_data": wear_data,
        "wear_info": wear_data,
        "platforms": platforms,
        "best_arbitrage": best_arbitrage,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _calculate_best_arbitrage(platforms: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    entries = []
    for name, payload in platforms.items():
        if name == "steam_official":
            continue
        if not payload or payload.get("net_price") is None:
            continue
        net_price = payload["net_price"]
        net_cents = int(round(float(net_price) * 100))
        entries.append((name, net_cents))

    best = None
    for buy_name, buy_price in entries:
        for sell_name, sell_price in entries:
            if sell_price <= buy_price:
                continue
            profit = sell_price - buy_price
            profit_pct = profit / buy_price * 100 if buy_price else 0
            if best is None or profit > best["profit_amount"]:
                best = {
                    "path": f"{buy_name} -> {sell_name}",
                    "profit_amount": round(profit / 100, 2),
                    "profit_pct": f"{profit_pct:.1f}%",
                }
    return best


def _build_csqaq_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    market_hash_name = str(row.get("market_hash_name") or "")
    display_name = str(row.get("name") or "").strip() or market_hash_name
    updated_at = row.get("updated_at") or datetime.now(timezone.utc).isoformat()

    steam_price = convert_to_cny(row.get("steam_sell_price"), "CNY")
    buff_price = convert_to_cny(row.get("buff_sell_price"), "CNY")
    youpin_price = convert_to_cny(row.get("yyyp_sell_price"), "CNY")

    platforms = {
        "steam": {
            "raw_price": steam_price,
            "net_price": normalize_steam_price(steam_price),
            "link": None,
            "last_update": updated_at,
            "status": "realtime" if steam_price is not None else "unavailable",
            "source": "CSQAQ API",
            "volume": row.get("steam_sell_num"),
        },
        "buff": {
            "raw_price": buff_price,
            "net_price": _net_price(buff_price, BUFF_FEE_DIVISOR),
            "link": None,
            "last_update": updated_at,
            "status": "realtime" if buff_price is not None else "unavailable",
            "source": "CSQAQ API",
            "volume": row.get("buff_sell_num"),
            "sell_listings": row.get("buff_sell_num"),
            "buy_orders": row.get("buff_buy_num"),
        },
        "youyou": {
            "raw_price": youpin_price,
            "net_price": _net_price(youpin_price, YOUPIN_FEE_DIVISOR),
            "link": None,
            "last_update": updated_at,
            "status": "realtime" if youpin_price is not None else "unavailable",
            "source": "CSQAQ API",
            "volume": row.get("yyyp_sell_num"),
            "sell_listings": row.get("yyyp_sell_num"),
            "buy_orders": row.get("yyyp_buy_num"),
        },
    }
    platforms["steam_official"] = platforms.get("steam")

    return {
        "item_name": market_hash_name,
        "display_name": display_name,
        "item_id": str(row.get("id") or market_hash_name),
        "base_info": {
            "image": None,
            "category": None,
            "rarity": None,
            "name_cn": display_name,
        },
        "wear_data": None,
        "wear_info": None,
        "platforms": platforms,
        "best_arbitrage": _calculate_best_arbitrage(platforms),
        "updated_at": updated_at,
    }


def _filter_csqaq_rows(rows: List[Dict[str, Any]], keyword: str, limit: int) -> List[Dict[str, Any]]:
    normalized = keyword.strip().lower()
    if not normalized:
        return rows[:limit]

    matched: List[Dict[str, Any]] = []
    for row in rows:
        market_hash_name = str(row.get("market_hash_name") or "").lower()
        name_cn = str(row.get("name") or "").lower()
        if normalized in market_hash_name or normalized in name_cn:
            matched.append(row)
            if len(matched) >= limit:
                break
    return matched


async def search_items(
    query: str,
    limit: int = 20,
    inspect_url: Optional[str] = None,
    use_proxy: bool = True,
    use_cache: bool = True,
) -> Dict[str, Any]:
    normalized_query = query.strip()
    if normalized_query and use_cache:
        cached = get_cached_search_results(normalized_query)
        if cached is not None:
            item_source = "csqaq_api" if _use_csqaq_search() else "database"
            price_source = _detect_price_source(cached) if isinstance(cached, list) else None
            return {
                "source": price_source or "cache",
                "item_source": item_source,
                "price_source": price_source,
                "data": cached,
            }

    if _use_csqaq_search():
        csqaq_rows = load_csqaq_goods_snapshot(use_cache=use_cache)
        matched_rows = _filter_csqaq_rows(csqaq_rows, normalized_query, limit)
        payloads = [_build_csqaq_payload(row) for row in matched_rows]

        if normalized_query:
            cache_search_results(normalized_query, payloads)

        return {
            "source": "csqaq_api",
            "item_source": "csqaq_api",
            "price_source": "csqaq_api",
            "data": payloads,
        }

    session = get_sessionmaker()()
    try:
        if normalized_query:
            keyword = f"%{normalized_query}%"
            items = (
                session.query(Item)
                .filter(
                    or_(
                        Item.market_hash_name.ilike(keyword),
                        Item.name_cn.ilike(keyword),
                    )
                )
                .order_by(Item.priority.desc(), Item.id.asc())
                .limit(limit)
                .all()
            )
            items = sorted(
                items,
                key=lambda row: (
                    _wear_rank(row),
                    -(row.priority or 0),
                    row.id,
                ),
            )
        else:
            hot_ids = get_hot_items_by_score(limit)
            if hot_ids:
                items = (
                    session.query(Item)
                    .filter(Item.id.in_(hot_ids))
                    .order_by(Item.priority.desc(), Item.id.asc())
                    .all()
                )
            else:
                items = (
                    session.query(Item)
                    .order_by(Item.priority.desc(), Item.id.asc())
                    .limit(limit)
                    .all()
                )
    finally:
        session.close()

    payloads = await asyncio.gather(
        *[
            _build_item_payload(item, inspect_url, use_proxy, use_cache)
            for item in items
        ]
    )

    if normalized_query:
        cache_search_results(normalized_query, payloads)

    record_hot_items([item.id for item in items])

    price_source = _detect_price_source(payloads)
    return {
        "source": price_source or "database",
        "item_source": "database",
        "price_source": price_source,
        "data": payloads,
    }
