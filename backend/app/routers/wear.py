from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app.dependencies import get_current_user
from backend.models import User
from backend.services.wear_service import get_wear_by_inspect_url


router = APIRouter(tags=["wear"])


class WearRequest(BaseModel):
    inspect_url: str = Field(..., alias="inspectUrl")
    notify_url: Optional[str] = Field(default=None, alias="notifyUrl")
    use_cache: bool = Field(default=True, alias="useCache")
    cache_ttl: Optional[int] = Field(default=None, alias="cacheTtl")

    model_config = {
        "populate_by_name": True,
    }


@router.post("/api/wear")
async def wear_lookup(payload: WearRequest, _: User = Depends(get_current_user)) -> dict:
    result = get_wear_by_inspect_url(
        payload.inspect_url,
        notify_url=payload.notify_url,
        use_cache=payload.use_cache,
        cache_ttl=payload.cache_ttl or 86400,
    )

    if result is None:
        raise HTTPException(status_code=502, detail="SteamDT wear lookup failed")

    return {"success": True, "data": result}
