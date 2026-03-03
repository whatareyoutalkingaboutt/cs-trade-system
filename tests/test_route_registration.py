from __future__ import annotations

from collections import Counter

from backend.app.main import app


def _method_path_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        methods = (route.methods or set()) - {"HEAD", "OPTIONS"}
        for method in methods:
            pairs.append((method, route.path))
    return pairs


def test_no_duplicate_method_path_routes() -> None:
    pairs = _method_path_pairs()
    duplicates = [(key, count) for key, count in Counter(pairs).items() if count > 1]
    assert not duplicates, f"Duplicate routes found: {duplicates}"


def test_key_api_routes_present() -> None:
    pairs = set(_method_path_pairs())
    expected = {
        ("POST", "/api/auth/login"),
        ("GET", "/api/items"),
        ("GET", "/api/prices/kline"),
        ("GET", "/api/arbitrage/opportunities"),
        ("POST", "/api/wear"),
        ("GET", "/api/scraper/tasks"),
    }
    missing = [pair for pair in expected if pair not in pairs]
    assert not missing, f"Missing expected routes: {missing}"
