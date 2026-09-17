"""Normalization is the riskiest mapping in the app, so it's tested directly."""
from app.providers.jambase import map_event

RAW = {
    "identifier": "jambase:99",
    "name": "Test Show",
    "eventStatus": "https://schema.org/EventScheduled",
    "startDate": "2026-10-01T20:00:00",
    "doorTime": "2026-10-01T19:00:00",
    "url": "https://example.com/show",
    "image": "https://example.com/img.jpg",
    "isAccessibleForFree": False,
    "location": {
        "name": "The Venue",
        "maximumAttendeeCapacity": 450,
        "address": {
            "streetAddress": "1 Main St",
            "addressLocality": "Nashville",
            "addressRegion": "TN",
            "postalCode": "37201",
            "addressCountry": "US",
            "x-timezone": "America/Chicago",
        },
        "geo": {"latitude": 36.16, "longitude": -86.78},
    },
    "performer": [
        {"name": "Band A", "genre": ["rock", "folk"]},
        {"name": "Band B", "genre": ["folk"]},
        {"not_a_name": True},  # malformed entries must be skipped
    ],
    "offers": [
        {"priceSpecification": {"minPrice": 25, "maxPrice": 60, "priceCurrency": "USD"}},
    ],
}


def test_map_event_core_fields():
    ev = map_event(RAW)
    assert ev.id == "jambase:99"
    assert ev.source == "jambase"
    assert ev.title == "Test Show"
    assert ev.status == "EventScheduled"
    assert ev.start_local.isoformat() == "2026-10-01T20:00:00"


def test_map_event_venue_and_price():
    ev = map_event(RAW)
    assert ev.venue.name == "The Venue"
    assert ev.venue.locality == "Nashville, TN"
    assert ev.venue.capacity == 450
    assert ev.venue.geo.latitude == 36.16
    assert ev.price.min == 25 and ev.price.max == 60 and ev.price.currency == "USD"


def test_map_event_performers_and_genres():
    ev = map_event(RAW)
    assert [p.name for p in ev.performers] == ["Band A", "Band B"]  # malformed dropped
    assert ev.genres == ["folk", "rock"]  # deduped + sorted


def test_map_event_handles_missing_fields():
    ev = map_event({"identifier": "jambase:1", "name": "Bare"})
    assert ev.title == "Bare"
    assert ev.price is None
    assert ev.performers == []
    assert ev.start_local is None


def test_price_from_single_price_field():
    ev = map_event({"name": "x", "offers": [{"priceSpecification": {"price": 30, "priceCurrency": "USD"}}]})
    assert ev.price.min == 30 and ev.price.max == 30


def test_empty_string_numerics_are_tolerated():
    # Live JamBase sends "" for absent capacity/geo/price — must not blow up.
    ev = map_event(
        {
            "name": "Edge",
            "location": {
                "name": "V",
                "maximumAttendeeCapacity": "",
                "geo": {"latitude": "", "longitude": ""},
            },
            "offers": [{"priceSpecification": {"minPrice": "", "priceCurrency": ""}}],
        }
    )
    assert ev.venue.capacity is None
    assert ev.venue.geo is None
    assert ev.price is None


def test_numeric_strings_are_parsed():
    ev = map_event(
        {"name": "x", "offers": [{"priceSpecification": {"minPrice": "25", "maxPrice": "60"}}]}
    )
    assert ev.price.min == 25 and ev.price.max == 60
