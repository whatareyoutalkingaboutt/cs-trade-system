from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SystemHeartbeat(Base):
    __tablename__ = "system_heartbeats"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    component: Mapped[str] = mapped_column(String(50), primary_key=True)
    instance_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    cpu_percent: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    memory_percent: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    active_tasks: Mapped[int] = mapped_column(Integer, default=0)

    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
