from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.app.main as main_module
import backend.app.routers.arbitrage as arbitrage_router_module
import backend.app.routers.prices as prices_router_module
import backend.app.routers.wear as wear_router_module
from backend.app.dependencies import get_current_user
from backend.app.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main_module, "ensure_default_admin", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authed_client(client: TestClient):
    fake_user = SimpleNamespace(
        id=1,
        username="tester",
        email="tester@example.com",
        is_active=True,
        is_superuser=True,
        last_login_at=None,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_health_and_root(client: TestClient):
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}

    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.json()["docs"] == "/docs"


def test_wear_lookup_success(monkeypatch: pytest.MonkeyPatch, authed_client: TestClient):
    monkeypatch.setattr(
        wear_router_module,
        "get_wear_by_inspect_url",
        lambda *args, **kwargs: {"wear": 0.1234, "seed": 321},
    )

    resp = authed_client.post(
        "/api/wear",
        json={"inspectUrl": "steam://example", "useCache": True},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"]["seed"] == 321


def test_wear_lookup_upstream_failure(monkeypatch: pytest.MonkeyPatch, authed_client: TestClient):
    monkeypatch.setattr(wear_router_module, "get_wear_by_inspect_url", lambda *args, **kwargs: None)

    resp = authed_client.post("/api/wear", json={"inspectUrl": "steam://example"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "SteamDT wear lookup failed"


def test_prices_kline_csqaq_path(monkeypatch: pytest.MonkeyPatch, client: TestClient):
    monkeypatch.setattr(prices_router_module, "DETAIL_ITEMS_SOURCE", "csqaq")
    monkeypatch.setattr(prices_router_module, "CSQAQ_PURE_DETAIL", True)
    monkeypatch.setattr(
        prices_router_module,
        "generate_csqaq_kline_with_indicators",
        lambda **kwargs: (98765, {"candles": [{"close": 100.0}]}),
    )

    resp = client.get("/api/prices/kline", params={"marketHashName": "AK-47 | Redline"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["source"] == "csqaq_api"
    assert payload["item_id"] == 98765


def test_arbitrage_opportunities_refresh(monkeypatch: pytest.MonkeyPatch, authed_client: TestClient):
    state = {"refreshed": False}

    def _refresh() -> None:
        state["refreshed"] = True

    monkeypatch.setattr(arbitrage_router_module, "analyze_and_cache_opportunities", _refresh)
    monkeypatch.setattr(
        arbitrage_router_module,
        "get_arbitrage_opportunities",
        lambda limit: [("key-1", {"item_id": 1, "net_profit": 1.23})],
    )

    resp = authed_client.get("/api/arbitrage/opportunities", params={"refresh": "true", "limit": 1})
    assert resp.status_code == 200
    payload = resp.json()
    assert state["refreshed"] is True
    assert payload["success"] is True
    assert payload["limit"] == 1
    assert payload["data"] == [{"item_id": 1, "net_profit": 1.23}]
