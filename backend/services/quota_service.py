from __future__ import annotations

from typing import Optional

from backend.core.cache import (
    acquire_lock,
    allow_rate_limit,
    increment_limit,
    release_lock,
)


PRICE_SINGLE_LIMIT_PER_MINUTE = 60
WEAR_LIMIT_PER_HOUR = 36000
INSPECT_LIMIT_PER_DAY = 100


def reserve_price_single(item_name: str) -> tuple[Optional[str], str]:
    if not allow_rate_limit("quota:price_single:minute", PRICE_SINGLE_LIMIT_PER_MINUTE, 60):
        return None, "quota_exceeded"
    lock_key = f"lock:price_single:{item_name}"
    token = acquire_lock(lock_key, ttl_seconds=10)
    if not token:
        return None, "locked"
    return token, "ok"


def release_price_single(item_name: str, token: str) -> bool:
    return release_lock(f"lock:price_single:{item_name}", token)


def reserve_wear(inspect_key: str) -> bool:
    return allow_rate_limit(f"quota:wear:{inspect_key}", 1, 3600)


def reserve_inspect() -> tuple[bool, int]:
    return increment_limit("quota:inspect:day", INSPECT_LIMIT_PER_DAY, 86400)
