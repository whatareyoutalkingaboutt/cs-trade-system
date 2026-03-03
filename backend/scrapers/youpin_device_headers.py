from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict

NEEDED_KEYS = {
    "accept",
    "content-type",
    "deviceid",
    "deviceuk",
    "uk",
    "secret-v",
    "appversion",
    "app-version",
    "apptype",
    "platform",
    "b3",
    "traceparent",
    "tracestate",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "user-agent",
    "referer",
}


def load_headers(file_path: str) -> Dict[str, str]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Header file not found: {file_path}")
    with path.open("r", encoding="utf-8") as f:
        headers = json.load(f)
    if not isinstance(headers, dict):
        raise ValueError(f"Header file must be a JSON object: {file_path}")
    return {str(k): str(v) for k, v in headers.items()}


def build_market_url(template_id: str, game_id: str, list_type: str) -> str:
    return (
        "https://www.youpin898.com/market/goods-list"
        f"?listType={list_type}&templateId={template_id}&gameId={game_id}"
    )


async def _capture_headers(url: str, timeout_ms: int) -> Dict[str, str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Install it with: "
            "./venv/bin/python -m pip install playwright && "
            "./venv/bin/python -m playwright install"
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, str]] = loop.create_future()

        def on_request(request) -> None:
            if "queryOnSaleCommodityList" in request.url and not future.done():
                future.set_result(dict(request.headers))

        page.on("request", on_request)
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        try:
            headers = await asyncio.wait_for(future, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            headers = {}

        await browser.close()
        return headers


def refresh_headers(url: str, timeout_ms: int = 20000) -> Dict[str, str]:
    headers = asyncio.run(_capture_headers(url, timeout_ms))
    if not headers:
        raise RuntimeError("No headers captured from Youpin page.")
    return {k: v for k, v in headers.items() if k in NEEDED_KEYS}


def refresh_headers_to_file(url: str, out_path: str, timeout_ms: int = 20000) -> Dict[str, str]:
    headers = refresh_headers(url, timeout_ms=timeout_ms)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(headers, f, ensure_ascii=True, indent=2)
    return headers
