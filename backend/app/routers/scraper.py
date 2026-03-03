from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func

from backend.app.dependencies import get_current_user
from backend.core.celery_app import celery_app
from backend.core.database import get_sessionmaker
from backend.models import PlatformConfig, ScraperTask, TaskExecution, User


router = APIRouter(tags=["scraper"])
LEGACY_MULTI_PLATFORM_TASK_SUFFIXES = (
    "scrape_items_by_priority",
    "scrape_all_platforms",
    "scrape_steam_price",
    "scrape_buff_price",
    "scrape_youpin_price",
)


def _legacy_multi_platform_enabled() -> bool:
    raw = os.getenv("ENABLE_LEGACY_MULTI_PLATFORM_SCRAPE", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class ScraperTaskRunRequest(BaseModel):
    item_name: Optional[str] = Field(default=None, alias="itemName")
    priority: Optional[str] = None
    use_proxy: bool = Field(default=True, alias="useProxy")
    opportunity: Optional[dict] = None
    min_profit_amount: Optional[float] = Field(default=None, alias="minProfitAmount")
    min_profit_rate: Optional[float] = Field(default=None, alias="minProfitRate")

    model_config = {
        "populate_by_name": True,
    }


@router.get("/api/scraper/platforms")
def list_scraper_platforms(_: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        rows = session.query(PlatformConfig).order_by(PlatformConfig.platform.asc()).all()
        data = [
            {
                "id": row.id,
                "platform": row.platform,
                "buy_fee_rate": float(row.buy_fee_rate),
                "sell_fee_rate": float(row.sell_fee_rate),
                "api_endpoint": row.api_endpoint,
                "rate_limit_per_minute": row.rate_limit_per_minute,
                "request_delay_min": float(row.request_delay_min),
                "request_delay_max": float(row.request_delay_max),
                "is_enabled": row.is_enabled,
                "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
            }
            for row in rows
        ]
        return {"success": True, "data": data}
    finally:
        session.close()


@router.get("/api/scraper/tasks")
def list_scraper_tasks(
    platform: Optional[str] = None,
    active: Optional[bool] = None,
    _: User = Depends(get_current_user),
) -> dict:
    session = get_sessionmaker()()
    try:
        task_query = session.query(ScraperTask)
        if platform:
            task_query = task_query.filter(ScraperTask.platform == platform)
        if active is not None:
            task_query = task_query.filter(ScraperTask.is_active == active)
        tasks = task_query.order_by(ScraperTask.id.asc()).all()

        subquery = (
            session.query(
                TaskExecution.task_id.label("task_id"),
                TaskExecution.platform.label("platform"),
                func.max(TaskExecution.time).label("max_time"),
            )
            .group_by(TaskExecution.task_id, TaskExecution.platform)
            .subquery()
        )

        latest_rows = (
            session.query(TaskExecution)
            .join(
                subquery,
                and_(
                    TaskExecution.task_id == subquery.c.task_id,
                    TaskExecution.platform == subquery.c.platform,
                    TaskExecution.time == subquery.c.max_time,
                ),
            )
            .all()
        )
        latest_map = {(row.task_id, row.platform): row for row in latest_rows}

        payload = []
        for task in tasks:
            latest = latest_map.get((task.id, task.platform))
            payload.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "platform": task.platform,
                    "task_type": task.task_type,
                    "schedule_type": task.schedule_type,
                    "schedule_config": task.schedule_config,
                    "item_filter": task.item_filter,
                    "priority": task.priority,
                    "max_concurrency": task.max_concurrency,
                    "timeout_seconds": task.timeout_seconds,
                    "max_retries": task.max_retries,
                    "is_active": task.is_active,
                    "is_running": task.is_running,
                    "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
                    "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
                    "latest_execution": None
                    if not latest
                    else {
                        "time": latest.time.isoformat(),
                        "status": latest.status,
                        "items_total": latest.items_total,
                        "items_processed": latest.items_processed,
                        "items_success": latest.items_success,
                        "items_failed": latest.items_failed,
                        "success_rate": float(latest.success_rate) if latest.success_rate is not None else None,
                        "duration_seconds": latest.duration_seconds,
                        "error_message": latest.error_message,
                    },
                }
            )

        return {"success": True, "data": payload}
    finally:
        session.close()


@router.post("/api/scraper/tasks/{task_id}/run")
def run_scraper_task(task_id: int, payload: ScraperTaskRunRequest, _: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        task = session.query(ScraperTask).filter(ScraperTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if not task.is_active:
            raise HTTPException(status_code=409, detail="Task is inactive")

        task_map = {
            "scrape_items_by_priority": "backend.scrapers.celery_tasks.scrape_items_by_priority",
            "scrape_all_platforms": "backend.scrapers.celery_tasks.scrape_all_platforms",
            "scrape_steam_price": "backend.scrapers.celery_tasks.scrape_steam_price",
            "scrape_buff_price": "backend.scrapers.celery_tasks.scrape_buff_price",
            "scrape_youpin_price": "backend.scrapers.celery_tasks.scrape_youpin_price",
            "sync_base_items": "backend.scrapers.celery_tasks.sync_base_items",
            "sync_csqaq_all_prices": "backend.scrapers.celery_tasks.sync_csqaq_all_prices",
            "dispatch_high_priority_verify_queue": "backend.scrapers.celery_tasks.dispatch_high_priority_verify_queue",
            "refresh_item_baselines": "backend.scrapers.celery_tasks.refresh_item_baselines",
            "verify_and_alert_task": "backend.scrapers.celery_tasks.verify_and_alert_task",
        }
        celery_task = task_map.get(task.task_type, task.task_type)
        if (
            not _legacy_multi_platform_enabled()
            and any(celery_task.endswith(suffix) for suffix in LEGACY_MULTI_PLATFORM_TASK_SUFFIXES)
        ):
            raise HTTPException(
                status_code=409,
                detail="Legacy multi-platform scraping is disabled; system is running in CSQAQ-only mode",
            )
        args = []
        kwargs = {}

        if celery_task.endswith("scrape_items_by_priority"):
            priority = payload.priority or (task.item_filter or {}).get("priority")
            if not priority:
                raise HTTPException(status_code=400, detail="priority is required")
            args = [priority]
        elif celery_task.endswith("scrape_all_platforms"):
            item_name = payload.item_name or (task.item_filter or {}).get("item_name")
            if not item_name:
                raise HTTPException(status_code=400, detail="itemName is required")
            args = [item_name]
        elif celery_task.endswith("scrape_steam_price"):
            item_name = payload.item_name or (task.item_filter or {}).get("item_name")
            if not item_name:
                raise HTTPException(status_code=400, detail="itemName is required")
            args = [item_name, payload.use_proxy]
        elif celery_task.endswith("scrape_buff_price"):
            item_name = payload.item_name or (task.item_filter or {}).get("item_name")
            if not item_name:
                raise HTTPException(status_code=400, detail="itemName is required")
            args = [item_name]
        elif celery_task.endswith("scrape_youpin_price"):
            item_name = payload.item_name or (task.item_filter or {}).get("item_name")
            if not item_name:
                raise HTTPException(status_code=400, detail="itemName is required")
            args = [item_name]
        elif celery_task.endswith("verify_and_alert_task"):
            opportunity = payload.opportunity or (task.item_filter or {}).get("opportunity")
            if not isinstance(opportunity, dict):
                raise HTTPException(status_code=400, detail="opportunity is required")
            kwargs["opportunity"] = opportunity
            if payload.min_profit_amount is not None:
                kwargs["min_profit_amount"] = payload.min_profit_amount
            if payload.min_profit_rate is not None:
                kwargs["min_profit_rate"] = payload.min_profit_rate

        async_result: AsyncResult = celery_app.send_task(celery_task, args=args, kwargs=kwargs)
        task.celery_task_id = async_result.id
        task.is_running = True
        task.last_run_at = datetime.now(timezone.utc)
        session.commit()
        return {"success": True, "data": {"task_id": task.id, "celery_task_id": async_result.id}}
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/api/scraper/monitor/status")
def scraper_status(_: User = Depends(get_current_user)) -> dict:
    session = get_sessionmaker()()
    try:
        total_tasks = session.query(ScraperTask).count()
        active_tasks = session.query(ScraperTask).filter(ScraperTask.is_active == True).count()
        running_tasks = session.query(ScraperTask).filter(ScraperTask.is_running == True).count()
        latest_exec = (
            session.query(TaskExecution)
            .order_by(TaskExecution.time.desc())
            .limit(5)
            .all()
        )
        recent = [
            {
                "task_id": row.task_id,
                "platform": row.platform,
                "status": row.status,
                "time": row.time.isoformat(),
                "items_success": row.items_success,
                "items_failed": row.items_failed,
            }
            for row in latest_exec
        ]
        return {
            "success": True,
            "summary": {
                "total_tasks": total_tasks,
                "active_tasks": active_tasks,
                "running_tasks": running_tasks,
            },
            "recent_executions": recent,
        }
    finally:
        session.close()
