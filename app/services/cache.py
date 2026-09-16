"""A tiny async-safe TTL cache.

Purpose is request-reduction: identical searches within the TTL window reuse one
upstream response instead of re-hitting a rate-limited API, and geography ID
lookups (city -> geoCityId) are cached for a full day since they barely change.

Intentionally in-memory and dependency-free. The interface (`get`/`set`) is the
seam: swapping in Redis for a multi-process deployment is a drop-in replacement.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + ttl_seconds, value)

    async def get_or_set(self, key: str, ttl_seconds: int, factory) -> Any:
        """Return cached value, or await `factory()`, store, and return it."""
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        await self.set(key, value, ttl_seconds)
        return value
