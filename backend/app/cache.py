from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.config import get_settings

_memory: dict[str, tuple[float, str]] = {}
_redis = None
_redis_failed = False


class Cache:
    async def get(self, key: str) -> Any | None:
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        raise NotImplementedError


class MemoryCache(Cache):
    async def get(self, key: str) -> Any | None:
        item = _memory.get(key)
        if not item:
            return None
        expires, payload = item
        if expires < time.time():
            _memory.pop(key, None)
            return None
        return json.loads(payload)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        _memory[key] = (time.time() + ttl_seconds, json.dumps(value))


class RedisCache(Cache):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def get(self, key: str) -> Any | None:
        raw = await self.client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self.client.set(key, json.dumps(value), ex=ttl_seconds)


_cache: Cache | None = None
_lock = asyncio.Lock()


def reset_cache_for_tests() -> None:
    global _cache, _redis, _redis_failed
    _memory.clear()
    _cache = None
    _redis = None
    _redis_failed = False


async def get_cache() -> Cache:
    global _cache, _redis, _redis_failed
    if _cache is not None:
        return _cache
    async with _lock:
        if _cache is not None:
            return _cache
        settings = get_settings()
        if settings.redis_url and not _redis_failed:
            try:
                from redis.asyncio import Redis

                _redis = Redis.from_url(settings.redis_url, decode_responses=True)
                await _redis.ping()
                _cache = RedisCache(_redis)
                return _cache
            except Exception:
                _redis_failed = True
        _cache = MemoryCache()
        return _cache


async def cache_get(key: str) -> Any | None:
    return await (await get_cache()).get(key)


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    await (await get_cache()).set(key, value, ttl_seconds)
