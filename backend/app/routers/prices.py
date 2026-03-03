from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.database import db_session, get_sessionmaker
from backend.models import Item, PriceHistory
from backend.services.item_detail_service import normalize_steam_price
from backend.services.kline_service import (
    generate_csqaq_dual_platform_trends,
    generate_csqaq_kline_with_indicators,
    generate_kline_with_indicators,
)


router = APIRouter(prefix="/api/prices", tags=["prices"])
DETAIL_ITEMS_SOURCE = os.getenv("SEARCH_ITEMS_SOURCE", "csqaq").strip().lower()
CSQAQ_PURE_DETAIL = os.getenv("CSQAQ_PURE_SEARCH", "true").strip().lower() in {"1", "true", "yes", "on"}


class LatestPriceRequest(BaseModel):
    market_hash_names: list[str] = Field(..., alias="marketHashNames")
    platform: Optional[str] = None

    model_config = {
        "populate_by_name": True,
    }


def _use_csqaq_kline() -> bool:
    return DETAIL_ITEMS_SOURCE == "csqaq" and CSQAQ_PURE_DETAIL


def _build_kline_response(
    market_hash_name: str,
    platform: str = "buff",
    interval: str = "1h",
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> dict:
    if _use_csqaq_kline():
        try:
            good_id, data = generate_csqaq_kline_with_indicators(
                market_hash_name=market_hash_name,
                platform=platform,
                interval=interval,
                lookback_days=lookback_days,
                use_cache=use_cache,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "success": True,
            "item_id": good_id,
            "market_hash_name": market_hash_name,
            "platform": platform,
            "interval": interval,
            "source": "csqaq_api",
            "data": data,
        }

    with db_session() as session:
        item = session.query(Item).filter(Item.market_hash_name == market_hash_name).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        data = generate_kline_with_indicators(
            item_id=item.id,
            platform=platform,
            interval=interval,
            lookback_days=lookback_days,
            use_cache=use_cache,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "item_id": item.id,
        "market_hash_name": item.market_hash_name,
        "platform": platform,
        "interval": interval,
        "source": "database",
        "data": data,
    }


@router.get("/kline")
def get_kline(
    market_hash_name: str = Query(..., alias="marketHashName"),
    platform: str = "buff",
    interval: str = "1h",
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> dict:
    return _build_kline_response(
        market_hash_name=market_hash_name,
        platform=platform,
        interval=interval,
        lookback_days=lookback_days,
        use_cache=use_cache,
    )


@router.get("/kline/{market_hash_name}")
def get_kline_by_path(
    market_hash_name: str,
    platform: str = "buff",
    interval: str = "1h",
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> dict:
    return _build_kline_response(
        market_hash_name=market_hash_name,
        platform=platform,
        interval=interval,
        lookback_days=lookback_days,
        use_cache=use_cache,
    )


@router.get("/trends")
def get_multi_platform_trends(
    market_hash_name: str = Query(..., alias="marketHashName"),
    interval: str = "1h",
    lookback_days: Optional[int] = None,
    use_cache: bool = True,
) -> dict:
    if not _use_csqaq_kline():
        raise HTTPException(status_code=400, detail="Multi-platform trends currently require CSQAQ mode")

    try:
        payload = generate_csqaq_dual_platform_trends(
            market_hash_name=market_hash_name,
            interval=interval,
            lookback_days=lookback_days,
            use_cache=use_cache,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "source": "csqaq_api",
        "data": payload,
    }


@router.get("/latest/{item_id}")
def get_latest_price(item_id: int, platform: Optional[str] = None) -> dict:
    session = get_sessionmaker()()
    try:
        query = session.query(PriceHistory).filter(PriceHistory.item_id == item_id)
        if platform:
            query = query.filter(PriceHistory.platform == platform)

        row = query.order_by(PriceHistory.time.desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail="Price not found")

        price_value = float(row.price)
        net_price = normalize_steam_price(price_value) if row.platform == "steam" else None
        return {
            "success": True,
            "data": {
                "time": row.time.isoformat(),
                "item_id": row.item_id,
                "platform": row.platform,
                "price": price_value,
                "net_price": net_price,
                "currency": row.currency,
                "volume": row.volume,
                "data_source": row.data_source,
                "quality_score": row.quality_score,
            },
        }
    finally:
        session.close()


@router.post("/latest")
def get_latest_prices(payload: LatestPriceRequest) -> dict:
    session = get_sessionmaker()()
    try:
        names = [name.strip() for name in payload.market_hash_names if name.strip()]
        if not names:
            raise HTTPException(status_code=400, detail="marketHashNames is required")

        items = session.query(Item).filter(Item.market_hash_name.in_(names)).all()
        item_map = {item.market_hash_name: item for item in items}
        data = []
        for name in names:
            item = item_map.get(name)
            if not item:
                continue

            query = session.query(PriceHistory).filter(PriceHistory.item_id == item.id)
            if payload.platform:
                query = query.filter(PriceHistory.platform == payload.platform)

            row = query.order_by(PriceHistory.time.desc()).first()
            if not row:
                continue

            price_value = float(row.price)
            net_price = normalize_steam_price(price_value) if row.platform == "steam" else None
            data.append(
                {
                    "market_hash_name": name,
                    "item_id": item.id,
                    "platform": row.platform,
                    "price": price_value,
                    "net_price": net_price,
                    "currency": row.currency,
                    "volume": row.volume,
                    "time": row.time.isoformat(),
                }
            )
        return {"success": True, "data": data}
    finally:
        session.close()


@router.get("/history/{item_id}")
def get_price_history(
    item_id: int,
    platform: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 500,
) -> dict:
    session = get_sessionmaker()()
    try:
        query = session.query(PriceHistory).filter(PriceHistory.item_id == item_id)
        if platform:
            query = query.filter(PriceHistory.platform == platform)
        if start_time:
            query = query.filter(PriceHistory.time >= datetime.fromisoformat(start_time))
        if end_time:
            query = query.filter(PriceHistory.time <= datetime.fromisoformat(end_time))

        rows = query.order_by(PriceHistory.time.desc()).limit(limit).all()
        data = [
            {
                "time": row.time.isoformat(),
                "item_id": row.item_id,
                "platform": row.platform,
                "price": float(row.price),
                "currency": row.currency,
                "volume": row.volume,
                "data_source": row.data_source,
                "quality_score": row.quality_score,
            }
            for row in rows
        ]
        return {"success": True, "data": data}
    finally:
        session.close()
