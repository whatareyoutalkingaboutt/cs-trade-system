from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def _usd_cny_rate() -> Decimal:
    raw = os.getenv("USD_CNY_RATE", "7.2")
    try:
        return Decimal(raw)
    except Exception:
        return Decimal("7.2")


def convert_to_cny(price: Optional[float], currency: Optional[str]) -> Optional[float]:
    if price is None:
        return None
    if currency is None or currency.upper() == "CNY":
        return float(price)
    if currency.upper() in {"USD", "USDT"}:
        value = Decimal(str(price)) * _usd_cny_rate()
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return float(price)
