from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from loguru import logger
from sqlalchemy import select, text, func
from sqlalchemy.dialects.postgresql import insert

from backend.core.cache import get_value, set_value
from backend.core.database import get_sessionmaker
from backend.models import Item
from backend.scrapers.csqaq_scraper import CSQAQRateLimitError, CSQAQScraper
from backend.scrapers.steamdt_base_scraper import SteamDTBaseScraper

HASH_FIELDS = (
    "market_hash_name",
    "name_cn",
    "name_buff",
    "type",
    "weapon_type",
    "skin_name",
    "quality",
    "rarity",
    "image_url",
    "steam_url",
    "buff_url",
)


def _is_non_ascii(value: Optional[str]) -> bool:
    if not value:
        return False
    return not str(value).isascii()


def _normalize_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _pick_first(payload: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        if key in payload:
            value = _normalize_value(payload.get(key))
            if value:
                return value
    return None


def normalize_base_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    market_hash_name = _pick_first(
        raw,
        (
            "market_hash_name",
            "marketHashName",
            "market_hash",
            "marketNameEn",
            "name_en",
            "nameEn",
        ),
    )
    if not market_hash_name:
        return None

    item_type = _pick_first(raw, ("type", "itemType", "category", "item_type")) or "unknown"

    normalized = {
        "market_hash_name": market_hash_name,
        "name_cn": _pick_first(
            raw,
            (
                "name_cn",
                "nameCn",
                "marketNameCn",
                "cn_name",
                "marketName",
                "name",
            ),
        ),
        "name_buff": _pick_first(raw, ("name_buff", "nameBuff", "buff_name")),
        "type": item_type,
        "weapon_type": _pick_first(raw, ("weapon_type", "weaponType", "weapon")),
        "skin_name": _pick_first(raw, ("skin_name", "skinName", "skin")),
        "quality": _pick_first(raw, ("quality", "qualityName")),
        "rarity": _pick_first(raw, ("rarity", "rarityName")),
        "image_url": _pick_first(raw, ("image", "imageUrl", "iconUrl", "icon")),
        "steam_url": _pick_first(raw, ("steam_url", "steamUrl", "marketUrl", "steamMarketUrl")),
        "buff_url": _pick_first(raw, ("buff_url", "buffUrl")),
    }

    return normalized


def _compute_item_hash(payload: Dict[str, Any]) -> str:
    data = {key: payload.get(key) for key in HASH_FIELDS}
    blob = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def _ensure_item_hash_column(session) -> None:
    session.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS data_hash VARCHAR(32)"))


def upsert_items(items: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    session = get_sessionmaker()()
    created = 0
    updated = 0
    try:
        items_list = [item for item in items if item]
        if not items_list:
            return 0, 0

        _ensure_item_hash_column(session)

        names = [item["market_hash_name"] for item in items_list if item.get("market_hash_name")]
        existing_rows = session.execute(
            select(Item.market_hash_name, Item.data_hash, Item.name_cn).where(
                Item.market_hash_name.in_(names)
            )
        ).all()
        existing = {row.market_hash_name: (row.data_hash, row.name_cn) for row in existing_rows}

        for payload in items_list:
            name = payload["market_hash_name"]
            existing_entry = existing.get(name)
            if not existing_entry:
                continue
            _, existing_name_cn = existing_entry
            payload_name_cn = payload.get("name_cn")
            if _is_non_ascii(existing_name_cn) and (not payload_name_cn or payload_name_cn.isascii()):
                payload["name_cn"] = existing_name_cn

        for payload in items_list:
            payload["data_hash"] = _compute_item_hash(payload)

        to_write = []
        for payload in items_list:
            name = payload["market_hash_name"]
            new_hash = payload["data_hash"]
            old_hash = existing.get(name, (None, None))[0]
            if old_hash == new_hash:
                continue
            if old_hash is None:
                created += 1
                payload.setdefault("is_active", True)
                payload.setdefault("priority", 5)
            else:
                updated += 1
            to_write.append(payload)

        if to_write:
            table = Item.__table__
            insert_stmt = insert(table).values(to_write)
            update_fields = {
                "name_cn": func.coalesce(insert_stmt.excluded.name_cn, table.c.name_cn),
                "name_buff": func.coalesce(insert_stmt.excluded.name_buff, table.c.name_buff),
                "type": func.coalesce(insert_stmt.excluded.type, table.c.type),
                "weapon_type": func.coalesce(insert_stmt.excluded.weapon_type, table.c.weapon_type),
                "skin_name": func.coalesce(insert_stmt.excluded.skin_name, table.c.skin_name),
                "quality": func.coalesce(insert_stmt.excluded.quality, table.c.quality),
                "rarity": func.coalesce(insert_stmt.excluded.rarity, table.c.rarity),
                "image_url": func.coalesce(insert_stmt.excluded.image_url, table.c.image_url),
                "steam_url": func.coalesce(insert_stmt.excluded.steam_url, table.c.steam_url),
                "buff_url": func.coalesce(insert_stmt.excluded.buff_url, table.c.buff_url),
                "data_hash": insert_stmt.excluded.data_hash,
            }

            session.execute(
                insert_stmt.on_conflict_do_update(
                    index_elements=[Item.market_hash_name],
                    set_=update_fields,
                    where=Item.__table__.c.data_hash.is_distinct_from(
                        insert_stmt.excluded.data_hash
                    ),
                )
            )

        session.commit()
        return created, updated
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sync_base_items(
    page_size: int = 1000,
    max_pages: Optional[int] = None,
) -> Dict[str, Any]:
    if get_value("quota:base_last_run"):
        return {
            "total": 0,
            "created": 0,
            "updated": 0,
            "skipped": True,
            "reason": "daily_quota_exhausted",
        }

    primary = os.getenv("BASE_SYNC_PRIMARY_SOURCE", "csqaq").strip().lower()

    def _iter_from_csqaq() -> list[Dict[str, Any]]:
        with CSQAQScraper() as scraper:
            return list(scraper.iter_items(page_size=page_size, max_pages=max_pages))

    def _iter_from_steamdt() -> list[Dict[str, Any]]:
        with SteamDTBaseScraper() as scraper:
            return list(scraper.iter_items(page_size=page_size, max_pages=max_pages))

    raw_items: list[Dict[str, Any]] = []
    try:
        if primary == "csqaq":
            try:
                raw_items = _iter_from_csqaq()
                logger.info("Base sync fetched from CSQAQ: {} rows", len(raw_items))
            except CSQAQRateLimitError as exc:
                cooldown = max(60, int(exc.cooldown_seconds))
                set_value("quota:base_last_run", str(int(datetime.utcnow().timestamp())), ttl_seconds=cooldown)
                return {
                    "total": 0,
                    "created": 0,
                    "updated": 0,
                    "skipped": True,
                    "reason": "rate_limited",
                }
            except Exception as exc:
                logger.warning("CSQAQ base sync failed, fallback to SteamDT: {}", exc)
                raw_items = _iter_from_steamdt()
                logger.info("Base sync fetched from SteamDT fallback: {} rows", len(raw_items))
        else:
            try:
                raw_items = _iter_from_steamdt()
                logger.info("Base sync fetched from SteamDT: {} rows", len(raw_items))
            except Exception as exc:
                logger.warning("SteamDT base sync failed, fallback to CSQAQ: {}", exc)
                raw_items = _iter_from_csqaq()
                logger.info("Base sync fetched from CSQAQ fallback: {} rows", len(raw_items))
    except Exception as exc:
        message = str(exc)
        if "上限" in message or "quota" in message or "limit" in message:
            set_value("quota:base_last_run", str(int(datetime.utcnow().timestamp())), ttl_seconds=86400)
            return {
                "total": 0,
                "created": 0,
                "updated": 0,
                "skipped": True,
                "reason": "daily_quota_exhausted",
            }
        raise

    normalized = [normalize_base_item(item) for item in raw_items]
    normalized = [item for item in normalized if item]

    created, updated = upsert_items(normalized)
    set_value("quota:base_last_run", str(int(datetime.utcnow().timestamp())), ttl_seconds=86400)
    logger.info(
        "Base sync complete: total=%s created=%s updated=%s",
        len(normalized),
        created,
        updated,
    )

    return {
        "total": len(normalized),
        "created": created,
        "updated": updated,
    }
