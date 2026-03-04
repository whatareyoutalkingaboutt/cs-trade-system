from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text

from backend.app.dependencies import get_current_user
from backend.core.database import get_sessionmaker
from backend.models import User


router = APIRouter(prefix="/api/alerts", tags=["alerts"])

SEVERITY_LABELS = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
}

TRIGGER_LABELS = {
    "arbitrage_alert": "套利告警",
    "arbitrage_alerts": "套利告警",
    "tiered_alerts": "分级预警",
    "market_maker_alerts": "庄家行为预警",
}

ALERT_TYPE_LABELS = {
    "distribution_risk": "派发风险",
    "washout_phase": "洗盘阶段",
    "markup_phase": "主升阶段",
    "accumulation_phase": "吸筹阶段",
    "market_maker_tag": "庄家标签",
}

PLATFORM_LABELS = {
    "buff": "BUFF",
    "youpin": "悠悠有品",
    "steam": "Steam",
    "c5game": "C5",
}


def _normalize_severity(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "warn": "medium",
        "warning": "medium",
        "urgent": "critical",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in SEVERITY_LABELS else "info"


def _to_payload_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        payload = payload.strip()
        if not payload:
            return {}
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _platform_label(value: Any) -> str:
    key = str(value or "").strip().lower()
    return PLATFORM_LABELS.get(key, str(value or "-"))


def _derive_action(payload: dict[str, Any], trigger_type: str, severity: str) -> str:
    action = str(payload.get("action") or "").strip()
    if action:
        return action

    event_key = str(payload.get("type") or payload.get("event") or trigger_type or "").strip().lower()
    if event_key in {"arbitrage_alert", "arbitrage_alerts"}:
        buy = _platform_label(payload.get("buy_platform"))
        sell = _platform_label(payload.get("sell_platform"))
        return f"买入{buy}，卖出{sell}"
    if event_key == "distribution_risk":
        return "优先卖出或减仓，等待风险释放"
    if event_key == "washout_phase":
        return "轻仓分批买入，避免追高"
    if event_key == "accumulation_phase":
        return "观察回踩后分批布局"
    if event_key == "markup_phase":
        return "可顺势跟随买入，设置止盈"
    if event_key == "market_maker_tag":
        return "观察成交变化，谨慎追高"
    if severity in {"critical", "high"}:
        return "暂缓买入，优先控制仓位"
    if severity == "medium":
        return "保持观察，等待二次确认"
    return "继续观察，暂不操作"


@router.get("/logs")
def list_alert_logs(
    limit: int = 50,
    offset: int = 0,
    trigger_type: Optional[str] = None,
    severity: Optional[str] = None,
    keyword: Optional[str] = None,
    _: User = Depends(get_current_user),
) -> dict:
    page_limit = max(1, min(int(limit), 200))
    page_offset = max(0, int(offset))

    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": page_limit, "offset": page_offset}
    count_params: dict[str, Any] = {}

    trigger = str(trigger_type or "").strip().lower()
    if trigger:
        conditions.append("LOWER(trigger_type) = :trigger_type")
        params["trigger_type"] = trigger
        count_params["trigger_type"] = trigger

    level = str(severity or "").strip().lower()
    if level:
        conditions.append("LOWER(severity) = :severity")
        params["severity"] = level
        count_params["severity"] = level

    kw = str(keyword or "").strip()
    if kw:
        conditions.append("(COALESCE(market_hash_name, '') ILIKE :keyword OR COALESCE(message, '') ILIKE :keyword)")
        keyword_like = f"%{kw}%"
        params["keyword"] = keyword_like
        count_params["keyword"] = keyword_like

    where_clause = " AND ".join(conditions)
    list_sql = text(
        f"""
        SELECT
            id,
            event_time,
            item_id,
            market_hash_name,
            buy_platform,
            sell_platform,
            trigger_type,
            severity,
            message,
            payload
        FROM alert_logs
        WHERE {where_clause}
        ORDER BY event_time DESC, id DESC
        LIMIT :limit
        OFFSET :offset
        """
    )
    count_sql = text(f"SELECT COUNT(1) FROM alert_logs WHERE {where_clause}")

    session = get_sessionmaker()()
    try:
        total = int(session.execute(count_sql, count_params).scalar() or 0)
        rows = session.execute(list_sql, params).mappings().all()
    finally:
        session.close()

    data: list[dict[str, Any]] = []
    for row in rows:
        payload = _to_payload_dict(row.get("payload"))
        severity_key = _normalize_severity(row.get("severity"))
        trigger_key = str(row.get("trigger_type") or "").strip().lower()
        alert_type_key = str(payload.get("type") or payload.get("event") or trigger_key).strip().lower()
        action = _derive_action(payload, trigger_key, severity_key)
        event_time = row.get("event_time")
        item_name = str(
            payload.get("item_name_cn")
            or payload.get("item_name")
            or payload.get("name_cn")
            or payload.get("market_hash_name")
            or row.get("market_hash_name")
            or "-"
        )

        data.append(
            {
                "id": row.get("id"),
                "event_time": event_time.isoformat() if isinstance(event_time, datetime) else str(event_time or ""),
                "item_id": row.get("item_id"),
                "item_name": item_name,
                "severity": severity_key,
                "severity_label": SEVERITY_LABELS.get(severity_key, "提示"),
                "trigger_type": trigger_key,
                "trigger_label": TRIGGER_LABELS.get(trigger_key, trigger_key or "告警"),
                "alert_type": alert_type_key,
                "alert_type_label": ALERT_TYPE_LABELS.get(alert_type_key, alert_type_key or "未知类型"),
                "message": str(row.get("message") or payload.get("message") or payload.get("detail") or "-"),
                "action": action,
                "payload": payload,
            }
        )

    return {
        "success": True,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
        "data": data,
    }
