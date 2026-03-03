from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PriceHistory(Base):
    __tablename__ = "price_history"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    item_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("items.id"),
        primary_key=True,
    )
    platform: Mapped[str] = mapped_column(String(50), primary_key=True)

    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    volume: Mapped[int] = mapped_column(Integer, default=0)
    sell_listings: Mapped[Optional[int]] = mapped_column(Integer)
    buy_orders: Mapped[Optional[int]] = mapped_column(Integer)

    data_source: Mapped[str] = mapped_column(String(50), default="scraper")
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_score: Mapped[int] = mapped_column(Integer, default=100)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="price_histories",
        lazy="noload",
    )
