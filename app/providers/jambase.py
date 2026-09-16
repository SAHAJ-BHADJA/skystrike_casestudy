"""JamBase Concert Data API (v3) adapter.

Owns every JamBase-specific detail: auth header, geography ID resolution, the
`/events` query shape, and the mapping from JamBase's schema.org-style JSON into
our normalized `Event`. Nothing outside this file knows JamBase exists.

Docs: https://data.jambase.com/api/reference
"""
from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.models import (
    Event,
    EventQuery,
    GeoPoint,
    Pagination,
    Performer,
    Price,
    ProviderResult,
    Venue,
)
from app.providers.base import EventProvider
from app.services.cache import TTLCache
from app.services.http_client import ResilientClient, UpstreamError


def _parse_dt(value: object) -> datetime | None:
    """Parse a JamBase local datetime string; tolerate junk and 'Z' suffixes."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def _flatten_region(region: object) -> str | None:
    """`addressRegion` can be a string or a nested object; return a short code/name."""
    if isinstance(region, str):
        return region
    if isinstance(region, dict):
        return region.get("alternateName") or region.get("identifier") or region.get("name")
    return None


SOURCE_KEY = "jambase"


def _venue(loc: dict) -> Venue:
    addr = loc.get("address") or {}
    geo = loc.get("geo") or {}
    point = None
    if geo.get("latitude") is not None and geo.get("longitude") is not None:
        point = GeoPoint(latitude=geo["latitude"], longitude=geo["longitude"])
    return Venue(
        name=loc.get("name"),
        street=addr.get("streetAddress"),
        city=addr.get("addressLocality"),
        region=_flatten_region(addr.get("addressRegion")),
        country=_flatten_region(addr.get("addressCountry")),
        postal_code=addr.get("postalCode"),
        timezone=addr.get("x-timezone"),
        geo=point,
        capacity=loc.get("maximumAttendeeCapacity"),
    )


def _performers(raw: list) -> list[Performer]:
    out: list[Performer] = []
    for p in raw:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        genre = p.get("genre") or []
        out.append(
            Performer(
                name=p["name"],
                genres=[g for g in genre if isinstance(g, str)],
                url=p.get("url"),
                image=p.get("image"),
            )
        )
    return out


def _price(offers: list) -> Price | None:
    mins: list[float] = []
    maxes: list[float] = []
    currency: str | None = None
    for offer in offers:
        spec = (offer or {}).get("priceSpecification") or {}
        currency = currency or spec.get("priceCurrency")
        for key in ("minPrice", "price"):
            if isinstance(spec.get(key), (int, float)):
                mins.append(float(spec[key]))
                break
        for key in ("maxPrice", "price"):
            if isinstance(spec.get(key), (int, float)):
                maxes.append(float(spec[key]))
                break
    if not mins and not maxes:
        return None
    return Price(
        min=min(mins) if mins else None,
        max=max(maxes) if maxes else None,
        currency=currency,
    )


def map_event(raw: dict) -> Event:
    """Map one JamBase Concert/Festival object into a normalized Event.

    Module-level and pure so it can be reused by the sample-data provider and
    exercised directly in unit tests without any network.
    """
    performers = _performers(raw.get("performer") or [])
    genres = sorted({g for p in performers for g in p.genres})
    return Event(
        id=raw.get("identifier") or f"{SOURCE_KEY}:{raw.get('name', 'unknown')}",
        source=SOURCE_KEY,
        title=raw.get("name") or "Untitled event",
        start_local=_parse_dt(raw.get("startDate")),
        end_local=_parse_dt(raw.get("endDate")),
        door_time=_parse_dt(raw.get("doorTime")),
        status=(raw.get("eventStatus") or "").rsplit("/", 1)[-1] or None,
        url=raw.get("url"),
        image=raw.get("image") or raw.get("x-promoImage"),
        is_free=bool(raw.get("isAccessibleForFree")),
        venue=_venue(raw.get("location") or {}),
        performers=performers,
        price=_price(raw.get("offers") or []),
        genres=genres,
    )


def map_pagination(raw: dict | None) -> Pagination:
    raw = raw or {}
    return Pagination(
        page=raw.get("page", 1),
        per_page=raw.get("perPage", 30),
        total_items=raw.get("totalItems"),
        total_pages=raw.get("totalPages"),
    )


class JamBaseProvider(EventProvider):
    key = "jambase"

    def __init__(self, settings: Settings, client: ResilientClient, cache: TTLCache) -> None:
        self._settings = settings
        self._client = client
        self._cache = cache

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.jambase_api_key}",
            "Accept": "application/json",
            "User-Agent": "skystrike-events/0.1 (case-study)",
        }

    def _url(self, path: str) -> str:
        return f"{self._settings.jambase_base_url}{path}"

    async def _resolve_city_id(self, query: EventQuery) -> str | None:
        """Look up a city name -> JamBase city ID, cached for a day."""
        if not query.city:
            return None
        cache_key = f"jambase:cityid:{query.country}:{query.state}:{query.city}".lower()

        async def fetch() -> str | None:
            params: dict[str, object] = {
                "geoCityName": query.city,
                "geoCountryIso2": query.country,
                "cityHasUpcomingEvents": "true",
            }
            if query.state:
                params["geoStateIso"] = f"{query.country}-{query.state}"
            data = await self._client.get_json(
                self._url("/geographies/cities"), headers=self._headers, params=params
            )
            cities = data.get("cities") or []
            return cities[0].get("identifier") if cities else None

        return await self._cache.get_or_set(cache_key, self._settings.geo_cache_ttl_seconds, fetch)

    def _geo_params(self, query: EventQuery, city_id: str | None) -> dict[str, object]:
        if query.has_geo:
            return {
                "geoLatitude": query.latitude,
                "geoLongitude": query.longitude,
                "geoRadiusAmount": query.radius_km,
                "geoRadiusUnits": "km",
            }
        if city_id:
            return {"geoCityId": city_id}
        if query.state:
            return {"geoStateIso": f"{query.country}-{query.state}"}
        return {}

    async def search(self, query: EventQuery) -> ProviderResult:
        try:
            city_id = await self._resolve_city_id(query)
            # A named city we can't resolve means "no such place" -> empty, not error.
            if query.city and not city_id and not query.has_geo and not query.state:
                return ProviderResult(source=self.key, events=[], pagination=Pagination())

            params: dict[str, object] = {
                "page": query.page,
                "perPage": query.per_page,
                **self._geo_params(query, city_id),
            }
            if query.date_from:
                params["eventDateFrom"] = query.date_from.isoformat()
            if query.date_to:
                params["eventDateTo"] = query.date_to.isoformat()
            if query.genre:
                params["genreSlug"] = query.genre
            if query.keyword:
                params["name"] = query.keyword

            cache_key = f"jambase:events:{sorted(params.items())}"

            async def fetch() -> dict:
                return await self._client.get_json(
                    self._url("/events"), headers=self._headers, params=params
                )

            data = await self._cache.get_or_set(cache_key, self._settings.cache_ttl_seconds, fetch)
            events = [map_event(raw) for raw in data.get("events", [])]
            return ProviderResult(
                source=self.key,
                events=events,
                pagination=map_pagination(data.get("pagination")),
            )
        except UpstreamError as exc:
            # Degrade gracefully: report the failure, don't sink the whole search.
            return ProviderResult(source=self.key, ok=False, error=str(exc))
        except Exception as exc:  # defensive: a malformed payload shouldn't 500 the API
            return ProviderResult(source=self.key, ok=False, error=f"unexpected: {exc}")
