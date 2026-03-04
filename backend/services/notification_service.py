from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable, Mapping, Any

import requests
from loguru import logger
from sqlalchemy import text

from backend.core.cache import get_dragonfly_client
from backend.core.database import get_sessionmaker
from backend.services.email_service import send_qq_email


DEFAULT_NOTIFICATION_CHANNEL = "notifications:arbitrage"
DEFAULT_TIERED_NOTIFICATION_CHANNEL = "notifications:tiered_alerts"
DEFAULT_NOTIFY_MIN_PROFIT_RATE = float(os.getenv("ARBITRAGE_NOTIFY_MIN_PROFIT_RATE", "8.0"))
DEFAULT_NOTIFY_MAX_ITEMS = int(os.getenv("ARBITRAGE_NOTIFY_MAX_ITEMS", "5"))
DEFAULT_TIERED_NOTIFY_MAX_ITEMS = int(os.getenv("TIERED_NOTIFY_MAX_ITEMS", "20"))
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("NOTIFY_WEBHOOK_TIMEOUT_SECONDS", "8"))
PLATFORM_LABELS = {
    "buff": "BUFF",
    "youpin": "悠悠有品",
    "steam": "Steam",
    "c5game": "C5",
}
SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}
SEVERITY_LABELS = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
}
EVENT_TYPE_LABELS = {
    "tiered_alerts": "分级预警",
    "market_maker_alerts": "庄家行为预警",
    "arbitrage_alerts": "套利预警",
}
ALERT_TYPE_LABELS = {
    "distribution_risk": "派发风险",
    "washout_phase": "洗盘阶段",
    "markup_phase": "主升阶段",
    "accumulation_phase": "吸筹阶段",
    "market_maker_tag": "庄家标签",
}


def _platform_label(platform: Any) -> str:
    raw = str(platform or "").strip().lower()
    return PLATFORM_LABELS.get(raw, str(platform or "-"))


def _event_type_label(event_type: Any) -> str:
    key = str(event_type or "").strip().lower()
    return EVENT_TYPE_LABELS.get(key, "分级预警")


def _alert_type_label(alert_type: Any) -> str:
    key = str(alert_type or "").strip().lower()
    return ALERT_TYPE_LABELS.get(key, str(alert_type or "未知类型"))


def _severity_label(severity: Any) -> str:
    key = _normalize_severity(severity, default="info")
    return SEVERITY_LABELS.get(key, "提示")


def _item_label(row: Mapping[str, Any]) -> str:
    return str(
        row.get("item_name_cn")
        or row.get("item_name")
        or row.get("name_cn")
        or row.get("item_name_en")
        or "-"
    )


def _arbitrage_action(row: Mapping[str, Any]) -> str:
    buy_platform = _platform_label(row.get("buy_platform"))
    sell_platform = _platform_label(row.get("sell_platform"))
    return f"买入{buy_platform}，卖出{sell_platform}"


def _tiered_action(row: Mapping[str, Any], event_type: str) -> str:
    alert_key = str(row.get("type") or row.get("event") or event_type or "").strip().lower()
    severity = _normalize_severity(row.get("severity") or row.get("level"), default="info")
    if alert_key == "distribution_risk":
        return "优先卖出或减仓，等待风险释放"
    if alert_key == "washout_phase":
        return "轻仓分批买入，避免追高"
    if alert_key == "accumulation_phase":
        return "观察回踩后分批布局"
    if alert_key == "markup_phase":
        return "可顺势跟随买入，设置止盈"
    if alert_key == "market_maker_tag":
        return "观察成交变化，谨慎追高"
    if severity in {"critical", "high"}:
        return "暂缓买入，优先控制仓位"
    if severity == "medium":
        return "保持观察，等待二次确认"
    return "继续观察，暂不操作"


def _qq_webhook_url() -> str:
    return (
        os.getenv("QQ_BOT_WEBHOOK_URL")
        or os.getenv("QQ_WEBHOOK_URL")
        or ""
    ).strip()


def publish_notification(
    event_type: str,
    data: Any,
    channel: str = DEFAULT_NOTIFICATION_CHANNEL,
) -> int:
    payload = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    client = get_dragonfly_client()
    client.publish(channel, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return 1


def _post_webhook_text(content: str) -> bool:
    webhook_url = _qq_webhook_url()
    if not webhook_url:
        return False

    candidates = [
        {"content": content},
        {"msg_type": "text", "content": {"text": content}},
        {"msgtype": "text", "text": {"content": content}},
        {"message": content},  # 新增: 原生兼容 NapCatQQ / Go-cqhttp (OneBot v11) 协议
    ]
    for payload in candidates:
        try:
            resp = requests.post(webhook_url, json=payload, timeout=DEFAULT_WEBHOOK_TIMEOUT_SECONDS)
            if 200 <= resp.status_code < 300:
                return True
        except Exception as exc:
            logger.warning("[Notify] QQ webhook request failed: {}", exc)
            continue
    return False


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_severity(profit_rate: float | None) -> str:
    if profit_rate is None:
        return "info"
    if profit_rate >= 20:
        return "critical"
    if profit_rate >= 8:
        return "high"
    if profit_rate >= 3:
        return "medium"
    return "info"


def _normalize_severity(value: Any, default: str = "info") -> str:
    text = str(value or "").strip().lower()
    if text in SEVERITY_RANK:
        return text
    aliases = {
        "warn": "medium",
        "warning": "medium",
        "urgent": "critical",
    }
    if text in aliases:
        return aliases[text]
    return default


def _persist_alert_logs(rows: list[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    values: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        profit_rate = _safe_float(row.get("profit_rate"))
        item_label = _item_label(row)
        buy_platform = str(row.get("buy_platform") or "")
        sell_platform = str(row.get("sell_platform") or "")
        action = str(row.get("action") or _arbitrage_action(row))
        payload = dict(row)
        payload.setdefault("action", action)
        values.append(
            {
                "event_time": now,
                "item_id": _safe_int(row.get("item_id")),
                "market_hash_name": str(row.get("item_name_en") or item_label),
                "buy_platform": buy_platform or None,
                "sell_platform": sell_platform or None,
                "trigger_type": "arbitrage_alert",
                "severity": _resolve_severity(profit_rate),
                "message": (
                    f"{item_label}：{_platform_label(buy_platform)}买入，{_platform_label(sell_platform)}卖出；"
                    f"收益率={row.get('profit_rate')}%，预计净利润={row.get('net_profit')}元；建议={action}"
                ),
                "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            }
        )

    session = get_sessionmaker()()
    inserted = 0
    try:
        insert_stmt = text(
            """
            INSERT INTO alert_logs
                (event_time, item_id, market_hash_name, buy_platform, sell_platform, trigger_type, severity, message, payload)
            VALUES
                (:event_time, :item_id, :market_hash_name, :buy_platform, :sell_platform, :trigger_type, :severity, :message, CAST(:payload AS JSONB))
            """
        )
        for value in values:
            try:
                session.execute(insert_stmt, value)
                session.commit()
                inserted += 1
                continue
            except Exception as exc:
                session.rollback()
                if value.get("item_id") is not None and "ForeignKeyViolation" in str(exc):
                    retry = dict(value)
                    retry["item_id"] = None
                    try:
                        session.execute(insert_stmt, retry)
                        session.commit()
                        inserted += 1
                        continue
                    except Exception as retry_exc:
                        session.rollback()
                        logger.warning("[Notify] persist alert_logs fallback failed: {}", retry_exc)
                        continue
                logger.warning("[Notify] persist alert_logs failed: {}", exc)
                continue
        return inserted
    finally:
        session.close()


def notify_arbitrage_opportunities(
    opportunities: Iterable[Mapping[str, Any]],
    min_profit_rate: float = DEFAULT_NOTIFY_MIN_PROFIT_RATE,
    max_items: int = DEFAULT_NOTIFY_MAX_ITEMS,
    channel: str = DEFAULT_NOTIFICATION_CHANNEL,
) -> dict:
    filtered = []
    for row in opportunities:
        try:
            profit_rate = float(row.get("profit_rate") or 0.0)
        except Exception:
            profit_rate = 0.0
        if profit_rate < min_profit_rate:
            continue
        filtered.append(row)

    filtered.sort(key=lambda item: float(item.get("profit_rate") or 0.0), reverse=True)
    top_items = filtered[:max(0, max_items)]
    enriched_top_items: list[dict[str, Any]] = []
    for row in top_items:
        payload = dict(row)
        payload["action"] = str(payload.get("action") or _arbitrage_action(payload))
        enriched_top_items.append(payload)

    if enriched_top_items:
        publish_notification(
            event_type="arbitrage_alerts",
            data=enriched_top_items,
            channel=channel,
        )
    db_logged = _persist_alert_logs(enriched_top_items)

    sent_webhook = False
    sent_email = False
    if enriched_top_items:
        lines = ["[套利告警] 检测到可执行机会："]
        html_lines = [
            "<h3>套利雷达发现以下机会：</h3>",
            "<table border='1' cellspacing='0' cellpadding='6'>",
            "<tr><th>序号</th><th>饰品</th><th>买入平台</th><th>卖出平台</th><th>收益率</th><th>预计净利润(元)</th><th>操作建议</th></tr>",
        ]

        for idx, row in enumerate(enriched_top_items, start=1):
            item_name = _item_label(row)
            buy_platform = _platform_label(row.get("buy_platform"))
            sell_platform = _platform_label(row.get("sell_platform"))
            action = str(row.get("action") or _arbitrage_action(row))
            text_line = (
                f"{idx}. 饰品：{item_name}；买入平台：{buy_platform}；卖出平台：{sell_platform}；"
                f"收益率：{row.get('profit_rate', '-')}%；预计净利润：{row.get('net_profit', '-')}元；"
                f"建议：{action}"
            )
            lines.append(text_line)

            html_lines.append(
                (
                    f"<tr><td>{idx}</td><td>{item_name}</td><td>{buy_platform}</td><td>{sell_platform}</td>"
                    f"<td>{row.get('profit_rate', '-')}%</td><td>{row.get('net_profit', '-')}</td>"
                    f"<td>{action}</td></tr>"
                )
            )

        html_lines.append("</table>")

        # 原有的 Webhook 推送
        sent_webhook = _post_webhook_text("\n".join(lines))
        # 新增的 QQ 邮件推送
        subject = f"套利告警：发现 {len(enriched_top_items)} 个可执行机会"
        sent_email = send_qq_email(subject, "".join(html_lines))

    return {
        "notification_channel": channel,
        "alert_candidates": len(filtered),
        "published": len(enriched_top_items),
        "db_logged": db_logged,
        "webhook_sent": sent_webhook,
        "email_sent": sent_email,
    }


def _persist_tiered_alert_logs(alerts: list[Mapping[str, Any]], trigger_type: str) -> int:
    if not alerts:
        return 0
    now = datetime.now(timezone.utc)
    insert_values: list[dict[str, Any]] = []
    for row in alerts:
        payload = dict(row)
        severity = _normalize_severity(payload.get("severity") or payload.get("level"), default="info")
        payload.setdefault("action", _tiered_action(payload, trigger_type))
        item_name = str(
            payload.get("item_name_cn")
            or payload.get("item_name")
            or payload.get("name_cn")
            or payload.get("market_hash_name")
            or payload.get("title")
            or payload.get("item")
            or "-"
        )
        insert_values.append(
            {
                "event_time": now,
                "item_id": _safe_int(payload.get("item_id")),
                "market_hash_name": item_name,
                "buy_platform": None,
                "sell_platform": None,
                "trigger_type": trigger_type,
                "severity": severity,
                "message": str(payload.get("message") or payload.get("detail") or payload.get("type") or "tiered_alert"),
                "payload": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            }
        )

    session = get_sessionmaker()()
    inserted = 0
    try:
        insert_stmt = text(
            """
            INSERT INTO alert_logs
                (event_time, item_id, market_hash_name, buy_platform, sell_platform, trigger_type, severity, message, payload)
            VALUES
                (:event_time, :item_id, :market_hash_name, :buy_platform, :sell_platform, :trigger_type, :severity, :message, CAST(:payload AS JSONB))
            """
        )
        for value in insert_values:
            try:
                session.execute(insert_stmt, value)
                session.commit()
                inserted += 1
            except Exception as exc:
                session.rollback()
                logger.warning("[Notify] persist tiered alert failed: {}", exc)
        return inserted
    finally:
        session.close()


def notify_tiered_alerts(
    alerts: Iterable[Mapping[str, Any]],
    *,
    event_type: str = "tiered_alerts",
    channel: str = DEFAULT_TIERED_NOTIFICATION_CHANNEL,
    max_items: int = DEFAULT_TIERED_NOTIFY_MAX_ITEMS,
    min_severity: str = "medium",
) -> dict:
    rows = [dict(row) for row in alerts if isinstance(row, Mapping)]
    if not rows:
        return {
            "notification_channel": channel,
            "event_type": event_type,
            "received": 0,
            "published": 0,
            "db_logged": 0,
            "webhook_sent": False,
            "email_sent": False,
        }

    threshold = SEVERITY_RANK.get(_normalize_severity(min_severity, default="medium"), 2)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        severity = _normalize_severity(row.get("severity") or row.get("level"), default="info")
        if SEVERITY_RANK.get(severity, 0) < threshold:
            continue
        row["severity"] = severity
        row["action"] = str(row.get("action") or _tiered_action(row, event_type))
        filtered.append(row)

    filtered.sort(key=lambda item: SEVERITY_RANK.get(str(item.get("severity") or "info"), 0), reverse=True)
    top_items = filtered[:max(0, int(max_items))]
    if top_items:
        publish_notification(event_type=event_type, data=top_items, channel=channel)

    db_logged = _persist_tiered_alert_logs(top_items, trigger_type=event_type)

    sent_webhook = False
    sent_email = False
    if top_items:
        event_label = _event_type_label(event_type)
        lines = [f"[{event_label}] 告警明细："]
        html_lines = [
            f"<h3>{event_label}</h3>",
            "<table border='1' cellspacing='0' cellpadding='6'>",
            "<tr><th>等级</th><th>类型</th><th>商品</th><th>详情</th><th>操作建议</th></tr>",
        ]

        for row in top_items:
            severity = _normalize_severity(row.get("severity"), default="info")
            severity_label = _severity_label(severity)
            item_name = str(
                row.get("item_name_cn")
                or row.get("item_name")
                or row.get("name_cn")
                or row.get("market_hash_name")
                or row.get("title")
                or row.get("item")
                or "-"
            )
            alert_type = _alert_type_label(row.get("type") or row.get("event") or event_type)
            message = str(row.get("message") or row.get("detail") or "-")
            action = str(row.get("action") or _tiered_action(row, event_type))
            lines.append(f"[{severity_label}] {alert_type} | {item_name} | {message} | 建议：{action}")
            html_lines.append(
                f"<tr><td>{severity_label}</td><td>{alert_type}</td><td>{item_name}</td><td>{message}</td><td>{action}</td></tr>"
            )

        html_lines.append("</table>")
        sent_webhook = _post_webhook_text("\n".join(lines))
        subject = f"{event_label}（{len(top_items)}条）"
        sent_email = send_qq_email(subject, "".join(html_lines))

    return {
        "notification_channel": channel,
        "event_type": event_type,
        "received": len(rows),
        "published": len(top_items),
        "db_logged": db_logged,
        "webhook_sent": sent_webhook,
        "email_sent": sent_email,
    }
