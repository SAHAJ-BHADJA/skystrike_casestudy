"""Decision-support signals are pure functions — easy and worthwhile to test."""
from datetime import date, datetime

from app.models import Event, EventQuery, GeoPoint, Price, Venue
from app.services import ranking


def _event(**kw) -> Event:
    base = dict(id="jambase:1", source="jambase", title="Show")
    base.update(kw)
    return Event(**base)


def test_haversine_known_distance():
    # Nashville -> Memphis is ~320 km; allow generous tolerance.
    d = ranking.haversine_km(36.16, -86.78, 35.15, -90.05)
    assert 300 < d < 340


def test_enrich_sets_days_until_and_distance():
    q = EventQuery(latitude=36.16, longitude=-86.78, radius_km=50)
    ev = _event(
        start_local=datetime(2026, 1, 11, 20, 0),
        venue=Venue(name="V", geo=GeoPoint(latitude=36.20, longitude=-86.80)),
    )
    ranking.enrich([ev], q, today=date(2026, 1, 1))
    assert ev.days_until == 10
    assert ev.distance_km is not None and ev.distance_km < 10


def test_free_event_highlight_and_score():
    q = EventQuery(city="Nashville")
    ev = _event(is_free=True, start_local=datetime(2026, 1, 2, 19, 0),
                venue=Venue(capacity=120))
    ranking.enrich([ev], q, today=date(2026, 1, 1))
    assert "Free entry" in ev.highlight
    assert "intimate venue" in ev.highlight
    assert ev.score_factors.get("free") == 0.3


def test_sort_relevance_orders_by_score():
    q = EventQuery(city="Nashville")
    soon = _event(id="a", start_local=datetime(2026, 1, 2), image="x", price=Price(min=10))
    later = _event(id="b", start_local=datetime(2026, 3, 1))
    events = ranking.enrich([later, soon], q, today=date(2026, 1, 1))
    ordered = ranking.sort_events(events, "relevance")
    assert ordered[0].id == "a"


def test_sort_date_puts_undated_last():
    q = EventQuery(city="Nashville")
    a = _event(id="a", start_local=datetime(2026, 2, 1))
    b = _event(id="b", start_local=None)
    c = _event(id="c", start_local=datetime(2026, 1, 1))
    ordered = ranking.sort_events([a, b, c], "date")
    assert [e.id for e in ordered] == ["c", "a", "b"]
