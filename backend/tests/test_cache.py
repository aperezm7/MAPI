import time

import pytest

from app.cache import MemoryCache, reset_cache_for_tests
from app.rate_limit import AsyncRateLimiter


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


@pytest.mark.asyncio
async def test_memory_cache_roundtrip():
    cache = MemoryCache()
    await cache.set("k", {"ok": True}, ttl_seconds=30)
    assert await cache.get("k") == {"ok": True}


@pytest.mark.asyncio
async def test_memory_cache_expiry():
    cache = MemoryCache()
    await cache.set("gone", {"x": 1}, ttl_seconds=0)
    time.sleep(0.02)
    assert await cache.get("gone") is None


@pytest.mark.asyncio
async def test_rate_limiter_enforces_interval():
    limiter = AsyncRateLimiter(0.05)
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.04
