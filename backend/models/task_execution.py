from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TaskExecution(Base):
    __tablename__ = "task_executions"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scraper_tasks.id"), primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), primary_key=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255))

    items_total: Mapped[int] = mapped_column(Integer, default=0)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    items_success: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))

    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    avg_response_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    requests_per_second: Mapped[Optional[float]] = mapped_column(Numeric(6, 2))

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_details: Mapped[Optional[dict]] = mapped_column(JSONB)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    task: Mapped["ScraperTask"] = relationship(
        "ScraperTask",
        back_populates="task_executions",
        lazy="noload",
    )
