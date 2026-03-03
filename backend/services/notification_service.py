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
DEFAULT_NOTIFY_MIN_PROFIT_RATE = float(os.getenv("ARBITRAGE_NOTIFY_MIN_PROFIT_RATE", "8.0"))
DEFAULT_NOTIFY_MAX_ITEMS = int(os.getenv("ARBITRAGE_NOTIFY_MAX_ITEMS", "5"))
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("NOTIFY_WEBHOOK_TIMEOUT_SECONDS", "8"))
PLATFORM_LABELS = {
    "buff": "BUFF",
    "youpin": "悠悠有品",
    "steam": "Steam",
    "c5game": "C5",
}


def _platform_label(platform: Any) -> str:
    raw = str(platform or "").strip().lower()
    return PLATFORM_LABELS.get(raw, str(platform or "-"))


def _item_label(row: Mapping[str, Any]) -> str:
    return str(row.get("item_name") or row.get("item_name_en") or "-")


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
                    f"收益率={row.get('profit_rate')}%，预计净利润={row.get('net_profit')}元"
                ),
                "payload": json.dumps(dict(row), ensure_ascii=True, separators=(",", ":")),
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
    if top_items:
        publish_notification(
            event_type="arbitrage_alerts",
            data=top_items,
            channel=channel,
        )
    db_logged = _persist_alert_logs(top_items)

    sent_webhook = False
    sent_email = False
    if top_items:
        lines = ["[套利告警] 检测到可执行机会："]
        html_lines = [
            "<h3>套利雷达发现以下机会：</h3>",
            "<table border='1' cellspacing='0' cellpadding='6'>",
            "<tr><th>序号</th><th>饰品</th><th>买入平台</th><th>卖出平台</th><th>收益率</th><th>预计净利润(元)</th></tr>",
        ]

        for idx, row in enumerate(top_items, start=1):
            item_name = _item_label(row)
            buy_platform = _platform_label(row.get("buy_platform"))
            sell_platform = _platform_label(row.get("sell_platform"))
            text_line = (
                f"{idx}. 饰品：{item_name}；买入平台：{buy_platform}；卖出平台：{sell_platform}；"
                f"收益率：{row.get('profit_rate', '-')}%；预计净利润：{row.get('net_profit', '-')}元"
            )
            lines.append(text_line)

            html_lines.append(
                (
                    f"<tr><td>{idx}</td><td>{item_name}</td><td>{buy_platform}</td><td>{sell_platform}</td>"
                    f"<td>{row.get('profit_rate', '-')}%</td><td>{row.get('net_profit', '-')}</td></tr>"
                )
            )

        html_lines.append("</table>")

        # 原有的 Webhook 推送
        sent_webhook = _post_webhook_text("\n".join(lines))
        # 新增的 QQ 邮件推送
        subject = f"套利告警：发现 {len(top_items)} 个可执行机会"
        sent_email = send_qq_email(subject, "".join(html_lines))

    return {
        "notification_channel": channel,
        "alert_candidates": len(filtered),
        "published": len(top_items),
        "db_logged": db_logged,
        "webhook_sent": sent_webhook,
        "email_sent": sent_email,
    }
