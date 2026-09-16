"""A small resilient HTTP client wrapper around httpx.

Third-party event feeds rate-limit aggressively (HTTP 429) and have transient
5xx blips. Rather than let a single hiccup fail a user's search, this client:

  * retries idempotent GETs with capped exponential backoff + full jitter,
  * honors a server-provided `Retry-After` header when present,
  * treats 429 and 5xx as retryable and 4xx (except 429) as fatal, and
  * bounds total attempts so we fail fast instead of hanging a request.

It is provider-agnostic on purpose: every provider adapter shares one policy,
so backoff/timeout behavior is consistent no matter how many feeds we add.
"""
from __future__ import annotations

import asyncio
import random

import httpx


class RateLimitedError(RuntimeError):
    """Raised when a provider keeps returning 429 past our retry budget."""


class UpstreamError(RuntimeError):
    """Raised for non-retryable upstream failures (bad request, auth, etc.)."""


# Status codes worth retrying: rate limiting + transient server errors.
_RETRYABLE = {429, 500, 502, 503, 504}


class ResilientClient:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        base_backoff: float = 0.5,
        max_backoff: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` is an injection seam for tests (httpx.MockTransport).
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff

    async def aclose(self) -> None:
        await self._client.aclose()

    def _sleep_seconds(self, attempt: int, retry_after: str | None) -> float:
        """Backoff for `attempt` (0-indexed). Prefer server's Retry-After."""
        if retry_after:
            try:
                return min(float(retry_after), self._max_backoff)
            except ValueError:
                pass  # HTTP-date form is rare here; fall through to backoff
        # Exponential backoff with full jitter (AWS "Exponential Backoff and Jitter").
        ceiling = min(self._max_backoff, self._base_backoff * (2 ** attempt))
        return random.uniform(0, ceiling)

    async def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict:
        """GET a URL and parse JSON, retrying transient failures.

        Raises RateLimitedError / UpstreamError on exhaustion so callers can
        degrade gracefully (e.g. drop one provider from an aggregated search).
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(url, headers=headers, params=params)
            except httpx.RequestError as exc:  # network/timeout — retryable
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._sleep_seconds(attempt, None))
                    continue
                raise UpstreamError(f"network error calling {url}: {exc}") from exc

            if resp.status_code in _RETRYABLE:
                if attempt < self._max_retries:
                    await asyncio.sleep(
                        self._sleep_seconds(attempt, resp.headers.get("Retry-After"))
                    )
                    continue
                if resp.status_code == 429:
                    raise RateLimitedError(f"{url} rate-limited after {attempt + 1} tries")
                raise UpstreamError(f"{url} failed with {resp.status_code}")

            if resp.status_code >= 400:
                raise UpstreamError(f"{url} failed with {resp.status_code}: {resp.text[:200]}")

            return resp.json()

        # Unreachable, but keeps the type checker and future edits honest.
        raise UpstreamError(f"{url} failed: {last_exc}")
