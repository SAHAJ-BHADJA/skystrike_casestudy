"""Deterministic decision-support: signals that help a user pick an event.

Everything here is pure and testable — no I/O, no randomness, no LLM. Each event
gets a relevance `score` plus a `score_factors` breakdown so the ranking is fully
explainable (you can see *why* an event ranked where it did). A short `highlight`
blurb is generated from the same signals.

An LLM-written blurb / personalized re-rank is a natural future layer, but it sits
*on top of* this deterministic core rather than replacing it — the core stays the
source of truth and always works offline.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime

from app.models import Event, EventQuery

_EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometers."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _days_until(start: datetime | None, today: date) -> int | None:
    if start is None:
        return None
    return (start.date() - today).days


def _capacity_descriptor(capacity: int | None) -> str | None:
    if not capacity:
        return None
    if capacity <= 500:
        return "intimate venue"
    if capacity <= 3000:
        return "mid-size venue"
    return "large venue"


def build_highlight(event: Event) -> str:
    """A compact, honest one-liner surfacing the most decision-relevant facts."""
    bits: list[str] = []

    if event.is_free:
        bits.append("Free entry")
    elif event.price and event.price.min is not None:
        cur = "$" if (event.price.currency in (None, "USD")) else f"{event.price.currency} "
        bits.append(f"From {cur}{event.price.min:.0f}")

    if event.days_until is not None:
        if event.days_until <= 0:
            bits.append("Happening today")
        elif event.days_until == 1:
            bits.append("Tomorrow")
        elif event.days_until <= 7:
            bits.append("This week")

    cap = _capacity_descriptor(event.venue.capacity)
    if cap:
        bits.append(cap)

    if event.distance_km is not None:
        bits.append(f"{event.distance_km:.0f} km away")

    if len(event.performers) > 1:
        bits.append(f"{len(event.performers)} acts")

    return " · ".join(bits) if bits else "Upcoming show"


def _score(event: Event, query: EventQuery) -> dict[str, float]:
    """Transparent additive scoring. Higher is more prominent.

    Weights are intentionally modest and readable rather than tuned — the point
    is an explainable default, not a black box.
    """
    f: dict[str, float] = {}

    # Sooner events are generally more actionable, with diminishing effect.
    if event.days_until is not None and event.days_until >= 0:
        f["soon"] = round(max(0.0, 1.0 - event.days_until / 90.0), 3)

    # Closer is better when the user gave us a location to measure from.
    if event.distance_km is not None:
        f["nearby"] = round(max(0.0, 1.0 - event.distance_km / max(query.radius_km, 1)), 3)

    # Reward listings a user can actually act on / evaluate.
    if event.price is not None or event.is_free:
        f["has_price"] = 0.3
    if event.image:
        f["has_image"] = 0.2
    if event.performers:
        f["has_lineup"] = 0.2
    if event.is_free:
        f["free"] = 0.3

    return f


def enrich(events: list[Event], query: EventQuery, *, today: date | None = None) -> list[Event]:
    """Populate decision-support signals on each event, in place, and return it."""
    today = today or datetime.now(UTC).date()

    for ev in events:
        ev.days_until = _days_until(ev.start_local, today)

        if query.has_geo and ev.venue.geo:
            ev.distance_km = round(
                haversine_km(
                    query.latitude, query.longitude,  # type: ignore[arg-type]
                    ev.venue.geo.latitude, ev.venue.geo.longitude,
                ),
                1,
            )

        ev.score_factors = _score(ev, query)
        ev.score = round(sum(ev.score_factors.values()), 3)
        ev.highlight = build_highlight(ev)

    return events


def sort_events(events: list[Event], sort: str) -> list[Event]:
    """Order events for display. Default is chronological; 'relevance' uses score."""
    if sort == "relevance":
        return sorted(events, key=lambda e: (-e.score, e.start_local or datetime.max))
    # date: soonest first, undated last
    return sorted(events, key=lambda e: (e.start_local is None, e.start_local or datetime.max))
