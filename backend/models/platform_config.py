from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlatformConfig(Base):
    __tablename__ = "platform_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    buy_fee_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    sell_fee_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)

    api_endpoint: Mapped[Optional[str]] = mapped_column(String(255))
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text)

    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=20)
    request_delay_min: Mapped[float] = mapped_column(Numeric(4, 2), default=2.0)
    request_delay_max: Mapped[float] = mapped_column(Numeric(4, 2), default=3.0)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
