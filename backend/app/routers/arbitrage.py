from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import get_current_user
from backend.core.cache import get_arbitrage_opportunities
from backend.models import User
from backend.services.arbitrage_service import (
    analyze_and_cache_opportunities,
    analyze_arbitrage_opportunities,
)


router = APIRouter(prefix="/api/arbitrage", tags=["arbitrage"])


@router.get("/opportunities")
def get_arbitrage_opportunity_list(
    limit: int = 50,
    refresh: bool = False,
    _: User = Depends(get_current_user),
) -> dict:
    if refresh:
        analyze_and_cache_opportunities()

    try:
        cached = get_arbitrage_opportunities(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cache unavailable: {exc}") from exc

    return {
        "success": True,
        "limit": limit,
        "data": [payload for _, payload in cached],
    }


@router.get("/calculate/{item_id}")
def calculate_arbitrage(
    item_id: int,
    min_profit_amount: float = 0.0,
    min_profit_rate: float = 0.0,
    _: User = Depends(get_current_user),
) -> dict:
    opportunities = analyze_arbitrage_opportunities(
        item_ids=[item_id],
        min_profit_amount=min_profit_amount,
        min_profit_rate=min_profit_rate,
        include_all_pairs=True,
    )
    data = [
        {
            "item_id": opp.item_id,
            "item_name": opp.item_name,
            "buy_platform": opp.buy_platform,
            "sell_platform": opp.sell_platform,
            "buy_price": round(opp.buy_price, 2),
            "sell_price": round(opp.sell_price, 2),
            "buy_fee_rate": round(opp.buy_fee_rate, 4),
            "sell_fee_rate": round(opp.sell_fee_rate, 4),
            "buy_cost": round(opp.buy_cost, 2),
            "sell_revenue": round(opp.sell_revenue, 2),
            "net_profit": round(opp.net_profit, 2),
            "profit_rate": round(opp.profit_rate, 2),
            "currency": opp.currency,
            "buy_time": opp.buy_time.isoformat(),
            "sell_time": opp.sell_time.isoformat(),
            "calculated_at": opp.calculated_at.isoformat(),
        }
        for opp in opportunities
    ]
    return {"success": True, "data": data}
