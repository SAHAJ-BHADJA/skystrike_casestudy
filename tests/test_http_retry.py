"""The resilience policy (retry/backoff on 429 + 5xx) is core to reliability."""
import httpx
import pytest

from app.services.http_client import RateLimitedError, ResilientClient, UpstreamError


def _client(handler, **kw):
    # base_backoff=0 keeps the test fast (jitter of [0, 0] == 0s sleeps).
    return ResilientClient(base_backoff=0, transport=httpx.MockTransport(handler), **kw)


async def test_retries_then_succeeds_on_429():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, max_retries=3)
    data = await client.get_json("https://api.test/events")
    assert data == {"ok": True}
    assert calls["n"] == 3
    await client.aclose()


async def test_raises_rate_limited_after_exhaustion():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = _client(handler, max_retries=2)
    with pytest.raises(RateLimitedError):
        await client.get_json("https://api.test/events")
    await client.aclose()


async def test_4xx_is_fatal_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = _client(handler, max_retries=3)
    with pytest.raises(UpstreamError):
        await client.get_json("https://api.test/events")
    assert calls["n"] == 1  # not retried
    await client.aclose()


async def test_5xx_is_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"events": []})

    client = _client(handler, max_retries=2)
    data = await client.get_json("https://api.test/events")
    assert data == {"events": []}
    assert calls["n"] == 2
    await client.aclose()
