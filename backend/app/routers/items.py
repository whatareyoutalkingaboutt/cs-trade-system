from __future__ import annotations

from typing import Optional

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.dependencies import get_current_user
from backend.core.cache import get_json
from backend.core.database import get_sessionmaker
from backend.models import Item, User
from backend.services.base_sync_service import sync_base_items
from backend.services.item_detail_service import fetch_item_detail, fetch_item_detail_from_csqaq
from backend.services.search_service import search_items


router = APIRouter(tags=["items"])
DETAIL_ITEMS_SOURCE = os.getenv("SEARCH_ITEMS_SOURCE", "csqaq").strip().lower()
CSQAQ_PURE_DETAIL = os.getenv("CSQAQ_PURE_SEARCH", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class ItemCreate(BaseModel):
    market_hash_name: str = Field(..., alias="marketHashName")
    name_cn: Optional[str] = Field(default=None, alias="nameCn")
    name_buff: Optional[str] = Field(default=None, alias="nameBuff")
    type: str
    weapon_type: Optional[str] = Field(default=None, alias="weaponType")
    skin_name: Optional[str] = Field(default=None, alias="skinName")
    quality: Optional[str] = None
    rarity: Optional[str] = None
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    steam_url: Optional[str] = Field(default=None, alias="steamUrl")
    buff_url: Optional[str] = Field(default=None, alias="buffUrl")
    is_active: bool = Field(default=True, alias="isActive")
    priority: int = 5

    model_config = {
        "populate_by_name": True,
    }


class ItemUpdate(BaseModel):
    market_hash_name: Optional[str] = Field(default=None, alias="marketHashName")
    name_cn: Optional[str] = Field(default=None, alias="nameCn")
    name_buff: Optional[str] = Field(default=None, alias="nameBuff")
    type: Optional[str] = None
    weapon_type: Optional[str] = Field(default=None, alias="weaponType")
    skin_name: Optional[str] = Field(default=None, alias="skinName")
    quality: Optional[str] = None
    rarity: Optional[str] = None
    image_url: Optional[str] = Field(default=None, alias="imageUrl")
    steam_url: Optional[str] = Field(default=None, alias="steamUrl")
    buff_url: Optional[str] = Field(default=None, alias="buffUrl")
    is_active: Optional[bool] = Field(default=None, alias="isActive")
    priority: Optional[int] = None

    model_config = {
        "populate_by_name": True,
    }


class ItemPriorityUpdate(BaseModel):
    priority: int


def _use_csqaq_detail() -> bool:
    return DETAIL_ITEMS_SOURCE == "csqaq" and CSQAQ_PURE_DETAIL


@router.get("/api/items")
def list_items(
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    active: Optional[bool] = None,
) -> dict:
    session = get_sessionmaker()()
    try:
        query = session.query(Item)
        if q:
            keyword = f"%{q.strip()}%"
            query = query.filter(
                (Item.market_hash_name.ilike(keyword))
                | (Item.name_cn.ilike(keyword))
            )
        if active is not None:
            query = query.filter(Item.is_active == active)

        total = query.count()
        rows = (
            query.order_by(Item.priority.desc(), Item.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = [
            {
                "id": row.id,
                "market_hash_name": row.market_hash_name,
                "name_cn": row.name_cn,
                "type": row.type,
                "rarity": row.rarity,
                "priority": row.priority,
                "is_active": row.is_active,
            }
            for row in rows
        ]
        return {"success": True, "total": total, "data": items}
    finally:
        session.close()


@router.get("/api/items/search")
async def search_items_endpoint(
    q: str = "",
    limit: int = 20,
    inspect_url: Optional[str] = Query(default=None, alias="inspectUrl"),
    use_proxy: bool = True,
    use_cache: bool = True,
) -> dict:
    result = await search_items(
        query=q,
        limit=limit,
        inspect_url=inspect_url,
        use_proxy=use_proxy,
        use_cache=use_cache,
    )
    return {
        "success": True,
        "source": result.get("source"),
        "item_source": result.get("item_source"),
        "price_source": result.get("price_source"),
        "data": result["data"],
    }


@router.post("/api/items")
def create_item(payload: ItemCreate, _: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        market_hash_name = payload.market_hash_name.strip()
        exists = (
            session.query(Item)
            .filter(Item.market_hash_name == market_hash_name)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Item already exists")

        item = Item(
            market_hash_name=market_hash_name,
            name_cn=payload.name_cn.strip() if payload.name_cn else None,
            name_buff=payload.name_buff.strip() if payload.name_buff else None,
            type=payload.type.strip(),
            weapon_type=payload.weapon_type.strip() if payload.weapon_type else None,
            skin_name=payload.skin_name.strip() if payload.skin_name else None,
            quality=payload.quality.strip() if payload.quality else None,
            rarity=payload.rarity.strip() if payload.rarity else None,
            image_url=payload.image_url.strip() if payload.image_url else None,
            steam_url=payload.steam_url.strip() if payload.steam_url else None,
            buff_url=payload.buff_url.strip() if payload.buff_url else None,
            is_active=payload.is_active,
            priority=payload.priority,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return {"success": True, "data": {"id": item.id}}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/api/items/sync/base")
def sync_items_base(
    page_size: int = 1000,
    max_pages: Optional[int] = None,
    _: User = Depends(get_current_user),
) -> dict:
    result = sync_base_items(page_size=page_size, max_pages=max_pages)
    return {"success": True, "data": result}


@router.get("/api/items/rankings")
def get_item_rankings() -> dict:
    """
    获取 24H 热门饰品排行（涨幅榜与活跃榜）。
    数据由 Celery 定时计算并写入缓存，这里仅做缓存直出。
    """
    gainers = get_json("rankings:top_gainers") or []
    volume = get_json("rankings:top_volume") or []
    meta = get_json("rankings:meta") or {}
    return {
        "success": True,
        "top_gainers": gainers,
        "top_volume": volume,
        "meta": meta,
    }


@router.get("/api/items/{item_id}")
def get_item(item_id: int) -> dict:
    session = get_sessionmaker()()
    try:
        row = session.query(Item).filter(Item.id == item_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Item not found")
        return {
            "success": True,
            "data": {
                "id": row.id,
                "market_hash_name": row.market_hash_name,
                "name_cn": row.name_cn,
                "name_buff": row.name_buff,
                "type": row.type,
                "weapon_type": row.weapon_type,
                "skin_name": row.skin_name,
                "quality": row.quality,
                "rarity": row.rarity,
                "image_url": row.image_url,
                "steam_url": row.steam_url,
                "buff_url": row.buff_url,
                "priority": row.priority,
                "is_active": row.is_active,
            },
        }
    finally:
        session.close()


@router.get("/api/item/detail")
async def get_item_detail(
    item_id: Optional[int] = None,
    market_hash_name: Optional[str] = Query(default=None, alias="marketHashName"),
    inspect_url: Optional[str] = Query(default=None, alias="inspectUrl"),
    use_proxy: bool = True,
    persist: bool = False,
    use_cache: bool = True,
    cache_ttl: Optional[int] = Query(default=None, alias="cacheTtl"),
) -> dict:
    if item_id is None and not market_hash_name:
        raise HTTPException(status_code=400, detail="item_id or marketHashName is required")

    if _use_csqaq_detail():
        detail = await fetch_item_detail_from_csqaq(
            item_id=item_id,
            market_hash_name=market_hash_name,
            inspect_url=inspect_url,
            use_cache=use_cache,
            cache_ttl=cache_ttl or 86400,
        )
        if detail:
            return {"success": True, "data": detail}

    session = get_sessionmaker()()
    try:
        query = session.query(Item)
        if item_id is not None:
            item = query.filter(Item.id == item_id).first()
        else:
            normalized_name = market_hash_name.strip() if market_hash_name else None
            item = query.filter(Item.market_hash_name == normalized_name).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
    finally:
        session.close()

    detail = await fetch_item_detail(
        item=item,
        inspect_url=inspect_url,
        use_proxy=use_proxy,
        persist=persist,
        use_cache=use_cache,
        cache_ttl=cache_ttl or 86400,
    )

    return {"success": True, "data": detail}


@router.put("/api/items/{item_id}")
def update_item(item_id: int, payload: ItemUpdate, _: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        data = payload.model_dump(exclude_unset=True, by_alias=True)
        market_hash_name = data.get("marketHashName")
        if market_hash_name:
            normalized = market_hash_name.strip()
            duplicate = (
                session.query(Item)
                .filter(Item.market_hash_name == normalized, Item.id != item_id)
                .first()
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="marketHashName already exists")
            item.market_hash_name = normalized

        mapping = {
            "nameCn": "name_cn",
            "nameBuff": "name_buff",
            "weaponType": "weapon_type",
            "skinName": "skin_name",
            "imageUrl": "image_url",
            "steamUrl": "steam_url",
            "buffUrl": "buff_url",
            "isActive": "is_active",
        }
        for key, value in data.items():
            if key in {"marketHashName"}:
                continue
            attr = mapping.get(key, key)
            if isinstance(value, str):
                value = value.strip()
            setattr(item, attr, value)

        session.commit()
        return {"success": True, "data": {"id": item.id}}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.patch("/api/items/{item_id}/priority")
def update_item_priority(item_id: int, payload: ItemPriorityUpdate, _: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        item.priority = payload.priority
        session.commit()
        return {"success": True, "data": {"id": item.id, "priority": item.priority}}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
