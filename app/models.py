"""Normalized, provider-agnostic domain models.

These are the *only* event shape the API, ranking layer, and UI ever see. Each
provider is responsible for mapping its own wire format into these types, so
adding or swapping a provider never ripples past its adapter. This seam is the
core of the "support 10 providers" story in the writeup.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    latitude: float
    longitude: float


class Venue(BaseModel):
    name: str | None = None
    street: str | None = None
    city: str | None = None
    region: str | None = None          # state / province
    country: str | None = None
    postal_code: str | None = None
    timezone: str | None = None
    geo: GeoPoint | None = None
    capacity: int | None = None        # drives the "intimate vs. arena" signal

    @property
    def locality(self) -> str | None:
        """Short human location, e.g. 'Brooklyn, NY'."""
        parts = [p for p in (self.city, self.region) if p]
        return ", ".join(parts) or None


class Price(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str | None = None


class Performer(BaseModel):
    name: str
    genres: list[str] = Field(default_factory=list)
    url: str | None = None
    image: str | None = None


class Event(BaseModel):
    """A single upcoming event, normalized across all providers."""

    id: str                             # namespaced, e.g. "jambase:12345"
    source: str                         # provider key, e.g. "jambase"
    title: str
    start_local: datetime | None = None  # venue-local wall time (no offset)
    end_local: datetime | None = None
    door_time: datetime | None = None
    status: str | None = None
    url: str | None = None
    image: str | None = None
    is_free: bool = False

    venue: Venue = Field(default_factory=Venue)
    performers: list[Performer] = Field(default_factory=list)
    price: Price | None = None
    genres: list[str] = Field(default_factory=list)

    # --- Decision-support signals (computed by the ranking layer) ---
    days_until: int | None = None
    distance_km: float | None = None
    highlight: str | None = None        # one-line "why go" blurb
    score: float = 0.0
    score_factors: dict[str, float] = Field(default_factory=dict)  # traceable


class EventQuery(BaseModel):
    """Normalized search request handed to providers."""

    # Location: either a named city, or a lat/lon + radius.
    city: str | None = None
    state: str | None = None            # US/CA/AU 2-letter region code
    country: str = "US"                 # ISO-3166 alpha-2
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 40.0

    date_from: date | None = None
    date_to: date | None = None
    genre: str | None = None
    keyword: str | None = None          # matches event title

    page: int = 1
    per_page: int = 30
    sort: str = "date"                  # "date" | "relevance"

    @property
    def has_geo(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def location_label(self) -> str:
        if self.has_geo:
            return f"{self.latitude:.3f}, {self.longitude:.3f}"
        parts = [p for p in (self.city, self.state) if p]
        return ", ".join(parts) or "your area"


class Pagination(BaseModel):
    page: int = 1
    per_page: int = 30
    total_items: int | None = None
    total_pages: int | None = None


class ProviderResult(BaseModel):
    """What a single provider returns for one search."""

    source: str
    events: list[Event] = Field(default_factory=list)
    pagination: Pagination | None = None
    ok: bool = True
    error: str | None = None            # populated when a provider degrades


class EventSearchResponse(BaseModel):
    """Top-level API payload."""

    query_location: str
    events: list[Event]
    pagination: Pagination
    sources: list[ProviderResult]       # per-provider status (transparency)
    sample_data: bool = False           # true when served from bundled fixture
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
