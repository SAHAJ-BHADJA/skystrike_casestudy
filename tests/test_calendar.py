"""The .ics builder is a pure function with fiddly escaping rules — test it."""
from datetime import datetime

from app.models import Event, Performer, Price, Venue
from app.services.calendar import build_ics


def _event(**kw) -> Event:
    base = dict(id="jambase:1", source="jambase", title="Show")
    base.update(kw)
    return Event(**base)


def test_ics_has_required_structure():
    ev = _event(
        title="Robert Plant",
        start_local=datetime(2026, 10, 1, 20, 0),
        end_local=datetime(2026, 10, 1, 22, 30),
        venue=Venue(name="Ryman", street="116 Rep. John Lewis Way N", city="Nashville", region="TN"),
        url="https://example.com/show",
    )
    ics = build_ics(ev)
    assert ics.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics and "END:VEVENT" in ics
    assert "SUMMARY:Robert Plant" in ics
    assert "DTSTART:20261001T200000" in ics
    assert "DTEND:20261001T223000" in ics
    assert "Ryman" in ics
    assert "\r\n" in ics  # CRLF line endings per RFC 5545


def test_ics_defaults_two_hour_block_when_no_end():
    ev = _event(start_local=datetime(2026, 10, 1, 20, 0))
    ics = build_ics(ev)
    assert "DTSTART:20261001T200000" in ics
    assert "DTEND:20261001T220000" in ics


def test_ics_escapes_special_characters():
    ev = _event(title="Rock, Sweat; & Beers", start_local=datetime(2026, 10, 1, 20, 0))
    ics = build_ics(ev)
    assert "SUMMARY:Rock\\, Sweat\\; & Beers" in ics


def test_ics_includes_lineup_and_price_in_description():
    ev = _event(
        start_local=datetime(2026, 10, 1, 20, 0),
        performers=[Performer(name="A"), Performer(name="B")],
        price=Price(min=25, currency="USD"),
    )
    ics = build_ics(ev)
    assert "Lineup: A\\, B" in ics
    assert "From USD 25" in ics
