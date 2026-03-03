from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ScraperTask(Base):
    __tablename__ = "scraper_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)

    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schedule_config: Mapped[Optional[dict]] = mapped_column(JSONB)

    item_filter: Mapped[Optional[dict]] = mapped_column(JSONB)

    priority: Mapped[int] = mapped_column(Integer, default=5)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=10)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    task_executions: Mapped[List["TaskExecution"]] = relationship(
        "TaskExecution",
        back_populates="task",
        lazy="noload",
    )
