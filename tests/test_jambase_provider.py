"""JamBaseProvider integration test with a mocked transport.

Exercises the full live path — city-ID resolution, /events call, normalization,
and graceful degradation — without touching the network or needing a key.
"""
import httpx
import pytest

from app.config import Settings
from app.models import EventQuery
from app.providers.jambase import JamBaseProvider
from app.services.cache import TTLCache
from app.services.http_client import ResilientClient

CITIES = {"success": True, "cities": [{"identifier": "jambase:123", "name": "Nashville"}]}
EVENTS = {
    "success": True,
    "pagination": {"page": 1, "perPage": 30, "totalItems": 1, "totalPages": 1},
    "events": [
        {
            "identifier": "jambase:1",
            "name": "Mocked Show",
            "startDate": "2026-10-01T20:00:00",
            "location": {"name": "Club", "address": {"addressLocality": "Nashville", "addressRegion": "TN"}},
            "performer": [{"name": "Act", "genre": ["rock"]}],
            "offers": [{"priceSpecification": {"minPrice": 20, "priceCurrency": "USD"}}],
        }
    ],
}


def _provider(handler) -> JamBaseProvider:
    settings = Settings(jambase_api_key="test-key")
    client = ResilientClient(base_backoff=0, transport=httpx.MockTransport(handler))
    return JamBaseProvider(settings, client, TTLCache())


async def test_search_resolves_city_then_returns_events():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/geographies/cities" in request.url.path:
            assert request.headers["Authorization"] == "Bearer test-key"
            return httpx.Response(200, json=CITIES)
        if request.url.path.endswith("/events"):
            seen["geoCityId"] = request.url.params.get("geoCityId")
            return httpx.Response(200, json=EVENTS)
        return httpx.Response(404)

    provider = _provider(handler)
    result = await provider.search(EventQuery(city="Nashville", state="TN"))
    assert result.ok
    assert seen["geoCityId"] == "jambase:123"  # resolved ID was forwarded
    assert result.events[0].title == "Mocked Show"
    assert result.events[0].price.min == 20


async def test_geo_search_skips_city_lookup():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/geographies/cities" not in request.url.path
        assert request.url.params.get("geoLatitude") == "36.16"
        return httpx.Response(200, json=EVENTS)

    provider = _provider(handler)
    result = await provider.search(EventQuery(latitude=36.16, longitude=-86.78))
    assert result.ok and len(result.events) == 1


async def test_upstream_failure_degrades_gracefully():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = _provider(handler)
    result = await provider.search(EventQuery(latitude=36.16, longitude=-86.78))
    assert result.ok is False
    assert result.error and result.events == []
