from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterable, Optional, Tuple

import redis
from dotenv import load_dotenv

load_dotenv()

LATEST_PRICE_TTL_SECONDS = 300
HOT_ITEMS_TTL_SECONDS = 600
ARBITRAGE_TTL_SECONDS = 300
KLINE_TTL_SECONDS = 1800
SEARCH_CACHE_TTL_SECONDS = 120
CSQAQ_SERIES_MAX_POINTS = 2880
BASELINE_TTL_SECONDS = 7200
LATEST_PRICE_SNAPSHOT_HASH_KEY = "items:latest_price"
HIGH_PRIORITY_VERIFY_QUEUE_KEY = "queue:verify:high_priority"
HIGH_PRIORITY_VERIFY_PAYLOAD_HASH_KEY = "queue:verify:high_priority:payload"

_client: Optional[redis.Redis] = None


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


def get_dragonfly_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(_build_dragonfly_url(), decode_responses=True)
    return _client


def close_dragonfly_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def set_json(key: str, value: Any, ttl: Optional[int] = None) -> None:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    client = get_dragonfly_client()
    if ttl is None:
        client.set(key, payload)
    else:
        client.setex(key, ttl, payload)


def get_json(key: str) -> Optional[Any]:
    client = get_dragonfly_client()
    payload = client.get(key)
    if payload is None:
        return None
    return json.loads(payload)


def latest_price_key(item_id: int, platform: Optional[str] = None) -> str:
    if platform:
        return f"price:latest:{item_id}:{platform}"
    return f"price:latest:{item_id}"


def cache_latest_price(
    item_id: int,
    price_payload: dict,
    platform: Optional[str] = None,
    ttl: int = LATEST_PRICE_TTL_SECONDS,
) -> None:
    key = latest_price_key(item_id, platform)
    client = get_dragonfly_client()
    client.hset(key, mapping=price_payload)
    client.expire(key, ttl)


def get_latest_price(item_id: int, platform: Optional[str] = None) -> Optional[dict]:
    client = get_dragonfly_client()
    data = client.hgetall(latest_price_key(item_id, platform))
    return data or None


def cache_latest_price_snapshot(
    market_hash_name: str,
    snapshot_payload: dict,
    ttl: Optional[int] = None,
) -> None:
    if not market_hash_name:
        return
    payload = json.dumps(snapshot_payload, ensure_ascii=True, separators=(",", ":"))
    client = get_dragonfly_client()
    client.hset(LATEST_PRICE_SNAPSHOT_HASH_KEY, market_hash_name, payload)
    if ttl is not None:
        client.expire(LATEST_PRICE_SNAPSHOT_HASH_KEY, max(1, int(ttl)))


def get_latest_price_snapshot(market_hash_name: str) -> Optional[dict]:
    if not market_hash_name:
        return None
    client = get_dragonfly_client()
    raw = client.hget(LATEST_PRICE_SNAPSHOT_HASH_KEY, market_hash_name)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def get_all_latest_price_snapshots() -> dict[str, dict]:
    client = get_dragonfly_client()
    raw_map = client.hgetall(LATEST_PRICE_SNAPSHOT_HASH_KEY)
    result: dict[str, dict] = {}
    for market_hash_name, raw in raw_map.items():
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            result[market_hash_name] = payload
    return result


def baseline_key(market_hash_name: str) -> str:
    return f"items:baseline:{market_hash_name}"


def cache_item_baseline(
    market_hash_name: str,
    baseline_payload: dict,
    ttl: int = BASELINE_TTL_SECONDS,
) -> None:
    if not market_hash_name:
        return
    set_json(baseline_key(market_hash_name), baseline_payload, ttl=ttl)


def get_item_baseline(market_hash_name: str) -> Optional[dict]:
    if not market_hash_name:
        return None
    payload = get_json(baseline_key(market_hash_name))
    if isinstance(payload, dict):
        return payload
    return None


def hot_items_key(limit: int) -> str:
    return f"items:hot:top:{limit}"


def cache_hot_items(
    item_ids: Iterable[int],
    limit: int,
    ttl: int = HOT_ITEMS_TTL_SECONDS,
) -> None:
    key = hot_items_key(limit)
    client = get_dragonfly_client()
    pipeline = client.pipeline()
    pipeline.delete(key)
    item_list = list(item_ids)
    if item_list:
        pipeline.rpush(key, *item_list)
    pipeline.expire(key, ttl)
    pipeline.execute()


def get_hot_items(limit: int) -> list[int]:
    client = get_dragonfly_client()
    values = client.lrange(hot_items_key(limit), 0, -1)
    return [int(value) for value in values]


def kline_key(item_id: int, platform: str, interval: str) -> str:
    return f"kline:{item_id}:{platform}:{interval}"


def cache_kline(
    item_id: int,
    platform: str,
    interval: str,
    payload: list[dict],
    ttl: int = KLINE_TTL_SECONDS,
) -> None:
    set_json(kline_key(item_id, platform, interval), payload, ttl=ttl)


def get_kline(
    item_id: int,
    platform: str,
    interval: str,
) -> Optional[list[dict]]:
    data = get_json(kline_key(item_id, platform, interval))
    if data is None:
        return None
    return data


def cache_arbitrage_opportunities(
    opportunities: Iterable[Tuple[float, dict]],
    ttl: int = ARBITRAGE_TTL_SECONDS,
) -> None:
    key = "arbitrage:opportunities"
    client = get_dragonfly_client()
    mapping = {
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")): score
        for score, payload in opportunities
    }
    pipeline = client.pipeline()
    pipeline.delete(key)
    if mapping:
        pipeline.zadd(key, mapping)
    pipeline.expire(key, ttl)
    pipeline.execute()


def get_arbitrage_opportunities(limit: int = 50) -> list[Tuple[float, dict]]:
    client = get_dragonfly_client()
    results = client.zrevrange("arbitrage:opportunities", 0, limit - 1, withscores=True)
    return [(score, json.loads(payload)) for payload, score in results]


def _candidate_member_key(candidate: dict) -> Optional[str]:
    item_id = candidate.get("item_id")
    if item_id is None:
        return None
    try:
        return str(int(item_id))
    except (TypeError, ValueError):
        value = str(item_id).strip()
        return value or None


def enqueue_high_priority_verify_candidate(candidate: dict, score: float) -> bool:
    member = _candidate_member_key(candidate)
    if member is None:
        return False

    payload = json.dumps(candidate, ensure_ascii=True, separators=(",", ":"))
    client = get_dragonfly_client()
    current_score = client.zscore(HIGH_PRIORITY_VERIFY_QUEUE_KEY, member)
    target_score = float(score)
    if current_score is not None:
        target_score = max(target_score, float(current_score))

    pipeline = client.pipeline()
    pipeline.hset(HIGH_PRIORITY_VERIFY_PAYLOAD_HASH_KEY, member, payload)
    pipeline.zadd(HIGH_PRIORITY_VERIFY_QUEUE_KEY, {member: target_score})
    pipeline.execute()
    return True


def pop_high_priority_verify_candidates(limit: int = 1) -> list[dict]:
    client = get_dragonfly_client()
    popped = client.zpopmax(HIGH_PRIORITY_VERIFY_QUEUE_KEY, max(1, int(limit)))
    if not popped:
        return []

    members = [member for member, _ in popped]
    payloads = client.hmget(HIGH_PRIORITY_VERIFY_PAYLOAD_HASH_KEY, members)
    if members:
        client.hdel(HIGH_PRIORITY_VERIFY_PAYLOAD_HASH_KEY, *members)

    result: list[dict] = []
    for raw in payloads:
        if raw is None:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            result.append(payload)
    return result


def get_high_priority_verify_queue_size() -> int:
    client = get_dragonfly_client()
    return int(client.zcard(HIGH_PRIORITY_VERIFY_QUEUE_KEY))


def get_value(key: str) -> Optional[str]:
    client = get_dragonfly_client()
    return client.get(key)


def set_value(key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
    client = get_dragonfly_client()
    if ttl_seconds is None:
        client.set(key, value)
    else:
        client.setex(key, ttl_seconds, value)


def acquire_lock(key: str, ttl_seconds: int = 10) -> Optional[str]:
    client = get_dragonfly_client()
    token = str(uuid.uuid4())
    if client.set(key, token, nx=True, ex=ttl_seconds):
        return token
    return None


def release_lock(key: str, token: str) -> bool:
    client = get_dragonfly_client()
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """
    return client.eval(script, 1, key, token) == 1


def allow_daily(key: str, ttl_seconds: int = 86400, value: Optional[str] = None) -> bool:
    client = get_dragonfly_client()
    payload = value or str(int(time.time()))
    return bool(client.set(key, payload, nx=True, ex=ttl_seconds))


def increment_limit(key: str, limit: int, ttl_seconds: int) -> tuple[bool, int]:
    client = get_dragonfly_client()
    pipeline = client.pipeline()
    pipeline.incr(key)
    pipeline.expire(key, ttl_seconds, nx=True)
    count, _ = pipeline.execute()
    return count <= limit, int(count)


def allow_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    client = get_dragonfly_client()
    now = time.time()
    pipeline = client.pipeline()
    pipeline.zadd(key, {now: now})
    pipeline.zremrangebyscore(key, 0, now - window_seconds)
    pipeline.zcard(key)
    pipeline.expire(key, window_seconds)
    _, _, count, _ = pipeline.execute()
    return int(count) <= limit


def cache_search_results(query: str, payload: Any, ttl: int = SEARCH_CACHE_TTL_SECONDS) -> None:
    key = f"search:items:{query}"
    set_json(key, payload, ttl=ttl)


def get_cached_search_results(query: str) -> Optional[Any]:
    return get_json(f"search:items:{query}")


def record_hot_items(item_ids: Iterable[int]) -> None:
    client = get_dragonfly_client()
    pipeline = client.pipeline()
    for item_id in item_ids:
        pipeline.zincrby("items:hot:search", 1, str(item_id))
    pipeline.execute()


def get_hot_items_by_score(limit: int = 20) -> list[int]:
    client = get_dragonfly_client()
    values = client.zrevrange("items:hot:search", 0, limit - 1)
    return [int(value) for value in values]


def csqaq_metric_series_key(item_id: int, platform: str, metric: str) -> str:
    return f"csqaq:series:{metric}:{item_id}:{platform}"


def append_csqaq_metric_points(
    points: Iterable[dict],
    max_points: int = CSQAQ_SERIES_MAX_POINTS,
) -> None:
    client = get_dragonfly_client()
    pipeline = client.pipeline()
    for point in points:
        try:
            item_id = int(point["item_id"])
            platform = str(point["platform"]).strip().lower()
            metric = str(point["metric"]).strip().lower()
            timestamp = str(point["time"])
            value = float(point["value"])
        except Exception:
            continue
        key = csqaq_metric_series_key(item_id, platform, metric)
        payload = json.dumps(
            {"time": timestamp, "value": value},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        pipeline.rpush(key, payload)
        pipeline.ltrim(key, -max_points, -1)
    pipeline.execute()


def get_csqaq_metric_series(
    item_id: int,
    platform: str,
    metric: str,
    limit: int = CSQAQ_SERIES_MAX_POINTS,
) -> list[dict]:
    client = get_dragonfly_client()
    key = csqaq_metric_series_key(item_id, platform, metric)
    values = client.lrange(key, -limit, -1)
    result: list[dict] = []
    for raw in values:
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("time") is not None:
            result.append(row)
    return result
