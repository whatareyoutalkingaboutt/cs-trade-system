from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_hash_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name_cn: Mapped[Optional[str]] = mapped_column(String(255))
    name_buff: Mapped[Optional[str]] = mapped_column(String(255))

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    weapon_type: Mapped[Optional[str]] = mapped_column(String(50))
    skin_name: Mapped[Optional[str]] = mapped_column(String(100))
    quality: Mapped[Optional[str]] = mapped_column(String(50))
    rarity: Mapped[Optional[str]] = mapped_column(String(50))

    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    steam_url: Mapped[Optional[str]] = mapped_column(String(500))
    buff_url: Mapped[Optional[str]] = mapped_column(String(500))
    data_hash: Mapped[Optional[str]] = mapped_column(String(32))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    price_histories: Mapped[List["PriceHistory"]] = relationship(
        "PriceHistory",
        back_populates="item",
        lazy="noload",
    )
    data_gap_logs: Mapped[List["DataGapLog"]] = relationship(
        "DataGapLog",
        back_populates="item",
        lazy="noload",
    )
