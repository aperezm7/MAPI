"""Per-client capacity (Redis when configured, otherwise this process) and credit costs."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from app.accounts import Client, add_spent, current_spent, record_query, resolve_request
from app.config import get_settings

_memory: dict[str, tuple[float, int]] = {}
_redis = None
_redis_failed = False

PRICES = {
    "map": "cost_map",
    "plan": "cost_plan",
    "resolve": "cost_resolve",
    "download": "cost_download",
    "export": "cost_export",
    "inat": "cost_inat",
}

DAILY_KIND = {"map": "map", "export": "map", "plan": "plan"}


def price(kind: str) -> float:
    field = PRICES.get(kind)
    if not field:
        return 0.0
    return float(getattr(get_settings(), field))


def prices() -> dict[str, float]:
    return {kind: price(kind) for kind in PRICES}


def reset_usage_for_tests() -> None:
    global _redis, _redis_failed
    _memory.clear()
    _redis = None
    _redis_failed = False


async def _redis_client():
    global _redis, _redis_failed
    settings = get_settings()
    if not settings.redis_url or _redis_failed:
        return None
    if _redis is not None:
        return _redis
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        return client
    except Exception:
        _redis_failed = True
        return None


async def _incr(key: str, ttl_seconds: int) -> int:
    client = await _redis_client()
    if client is not None:
        count = int(await client.incr(key))
        if count == 1:
            await client.expire(key, ttl_seconds)
        return count
    now = time.time()
    current, expiry = _memory.get(key, (0, 0.0))
    if expiry < now:
        current = 0
    current += 1
    _memory[key] = (current, now + ttl_seconds)
    return current


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


async def admit(request: Request, kind: str) -> Client:
    """Identify the caller and reject the request when a quota or the monthly budget is spent."""
    client = resolve_request(request)
    if client.unlimited:
        return client
    rpm = await _incr(f"mapi:rpm:{client.id}", 60)
    if client.requests_per_minute is not None and rpm > client.requests_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit of {client.requests_per_minute} requests per minute reached for {client.name}.",
        )
    cost = price(kind)
    budget = client.budget
    if budget is not None and current_spent(client) + cost > budget + 1e-9:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly credit budget of {budget:g} is used up ({current_spent(client):g} spent).",
        )
    bucket = DAILY_KIND.get(kind)
    if bucket == "map" and client.maps_per_day is not None:
        used = await _incr(f"mapi:day:{client.id}:{_today()}:map", 172800)
        if used > client.maps_per_day:
            raise HTTPException(status_code=429, detail=f"Daily map limit of {client.maps_per_day} reached for {client.name}.")
    elif bucket == "plan" and client.plans_per_day is not None:
        used = await _incr(f"mapi:day:{client.id}:{_today()}:plan", 172800)
        if used > client.plans_per_day:
            raise HTTPException(status_code=429, detail=f"Daily planner limit of {client.plans_per_day} reached for {client.name}.")
    return client


def settle(client: Client, kind: str, summary: str, body: object, ok: bool) -> None:
    cost = price(kind) if ok and not client.unlimited else 0.0
    record_query(client.id, kind, summary, json.dumps(body, default=str), cost, "ok" if ok else "error")
    add_spent(client.id, cost)


def summarize_query(query) -> str:
    names = []
    for taxon in getattr(query, "taxa", None) or []:
        name = getattr(taxon, "canonicalName", None) or getattr(taxon, "q", None)
        if name:
            names.append(name)
    if not names:
        single = getattr(query, "taxon", None)
        name = getattr(single, "canonicalName", None) or getattr(single, "q", None)
        if name:
            names.append(name)
    place_names = []
    for place in getattr(query, "places", None) or []:
        name = getattr(place, "title", None) or getattr(place, "q", None) or getattr(place, "iso2", None)
        if name:
            place_names.append(name)
    if not place_names:
        single = getattr(query, "place", None)
        name = getattr(single, "title", None) or getattr(single, "q", None) or getattr(single, "iso2", None)
        if name:
            place_names.append(name)
    parts = [part for part in (", ".join(names) or None, ", ".join(place_names) or None) if part]
    return " · ".join(parts) or "unscoped query"
