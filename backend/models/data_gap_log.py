from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class DataGapLog(Base):
    __tablename__ = "data_gap_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("items.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)

    gap_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    fill_status: Mapped[str] = mapped_column(String(20), nullable=False)
    fill_method: Mapped[Optional[str]] = mapped_column(String(50))
    filled_points: Mapped[int] = mapped_column(Integer, default=0)

    gap_reason: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="data_gap_logs",
        lazy="noload",
    )
