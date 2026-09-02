from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Minimum interval between outbound calls to a host."""

    def __init__(self, min_interval_seconds: float = 0.08) -> None:
        self.min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


gbif_limiter = AsyncRateLimiter(0.08)
inat_limiter = AsyncRateLimiter(0.15)
iucn_limiter = AsyncRateLimiter(0.2)
llm_limiter = AsyncRateLimiter(0.05)
