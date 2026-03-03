from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc

from backend.core.cache import get_arbitrage_opportunities
from backend.core.database import get_sessionmaker
from backend.models import ScraperTask, TaskExecution


ARBITRAGE_CHANNEL = "arbitrage:opportunities:channel"
ALERTS_CHANNEL = "alerts:price_anomalies"
SCRAPER_MONITOR_CHANNEL = "scraper:monitor:channel"
DEFAULT_ARBITRAGE_LIMIT = 50
DEFAULT_SCRAPER_RECENT_LIMIT = 5


def _build_dragonfly_url() -> str:
    url = os.getenv("DRAGONFLY_URL")
    if url:
        return url

    host = os.getenv("DRAGONFLYDB_HOST", "localhost")
    port = os.getenv("DRAGONFLYDB_PORT", "6379")
    password = os.getenv("DRAGONFLYDB_PASSWORD", "")
    db = os.getenv("DRAGONFLYDB_DB", "0")
    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


app = FastAPI(title="CS Item WebSocket Gateway")


async def _send_initial_arbitrage(websocket: WebSocket, limit: int) -> None:
    def _load_snapshot():
        return get_arbitrage_opportunities(limit=limit)

    snapshot = await asyncio.to_thread(_load_snapshot)
    payload = {
        "type": "arbitrage_snapshot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": [entry for _, entry in snapshot],
    }
    await websocket.send_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


async def _send_initial_scraper_monitor(websocket: WebSocket, recent_limit: int) -> None:
    def _load_snapshot():
        session = get_sessionmaker()()
        try:
            total_tasks = session.query(ScraperTask).count()
            active_tasks = session.query(ScraperTask).filter(ScraperTask.is_active.is_(True)).count()
            running_tasks = session.query(ScraperTask).filter(ScraperTask.is_running.is_(True)).count()
            latest_exec = (
                session.query(TaskExecution)
                .order_by(desc(TaskExecution.time))
                .limit(recent_limit)
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
                "total_tasks": total_tasks,
                "active_tasks": active_tasks,
                "running_tasks": running_tasks,
                "recent_executions": recent,
            }
        finally:
            session.close()

    snapshot = await asyncio.to_thread(_load_snapshot)
    payload = {
        "type": "scraper_monitor_snapshot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tasks": snapshot["total_tasks"],
            "active_tasks": snapshot["active_tasks"],
            "running_tasks": snapshot["running_tasks"],
        },
        "recent_executions": snapshot["recent_executions"],
    }
    await websocket.send_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


async def _stream_pubsub(websocket: WebSocket, channel: str) -> None:
    redis = Redis.from_url(_build_dragonfly_url(), decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    logger.info("[WS] Subscribed to {}", channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if data is None:
                continue
            await websocket.send_text(data)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis.close()
        logger.info("[WS] Unsubscribed from {}", channel)


async def _handle_socket(websocket: WebSocket, channel: str, initial_snapshot: Optional[int] = None) -> None:
    await websocket.accept()
    try:
        if initial_snapshot:
            await _send_initial_arbitrage(websocket, initial_snapshot)
        await _stream_pubsub(websocket, channel)
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected ({})", channel)
    except Exception as exc:
        logger.error("[WS] Error: {}", exc)
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/arbitrage")
async def ws_arbitrage(websocket: WebSocket) -> None:
    await _handle_socket(websocket, ARBITRAGE_CHANNEL, initial_snapshot=DEFAULT_ARBITRAGE_LIMIT)


@app.websocket("/ws/arbitrage/opportunities")
async def ws_arbitrage_opportunities(websocket: WebSocket) -> None:
    await _handle_socket(websocket, ARBITRAGE_CHANNEL, initial_snapshot=DEFAULT_ARBITRAGE_LIMIT)


@app.websocket("/ws/scraper/monitor")
async def ws_scraper_monitor(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await _send_initial_scraper_monitor(websocket, DEFAULT_SCRAPER_RECENT_LIMIT)
        await _stream_pubsub(websocket, SCRAPER_MONITOR_CHANNEL)
    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected ({})", SCRAPER_MONITOR_CHANNEL)
    except Exception as exc:
        logger.error("[WS] Error: {}", exc)
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    await _handle_socket(websocket, ALERTS_CHANNEL)
