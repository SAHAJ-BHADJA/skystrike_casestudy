"""End-to-end API tests against the zero-setup sample-data path.

These tests pin the service to the sample provider so they're hermetic — they
pass identically whether or not a real JAMBASE_API_KEY is set in the environment.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.sample import SampleProvider
from app.services.events_service import EventsService


@pytest.fixture
def client():
    # `with` runs the lifespan, which builds app.state.events_service.
    with TestClient(app) as c:
        # Force sample mode regardless of local .env, for deterministic assertions.
        app.state.events_service = EventsService([SampleProvider()], sample_data=True)
        yield c


def test_health_reports_sample_mode(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search_returns_sample_events(client):
    r = client.get("/api/events", params={"city": "Nashville", "state": "TN"})
    assert r.status_code == 200
    body = r.json()
    assert body["sample_data"] is True
    assert len(body["events"]) > 0
    ev = body["events"][0]
    # Enrichment ran: decision-support fields are present.
    assert "highlight" in ev and "score" in ev


def test_requires_a_location(client):
    r = client.get("/api/events")
    assert r.status_code == 422


def test_lat_lon_must_be_paired(client):
    r = client.get("/api/events", params={"lat": 36.16})
    assert r.status_code == 422


def test_genre_filter_narrows_results(client):
    all_events = client.get("/api/events", params={"city": "Nashville"}).json()["events"]
    edm = client.get("/api/events", params={"city": "Nashville", "genre": "edm"}).json()["events"]
    assert 0 < len(edm) < len(all_events)


def test_relevance_sort_is_accepted(client):
    r = client.get("/api/events", params={"city": "Nashville", "sort": "relevance"})
    assert r.status_code == 200


def test_free_only_filter(client):
    events = client.get("/api/events", params={"city": "Nashville", "free_only": "true"}).json()["events"]
    assert events and all(e["is_free"] for e in events)


def test_max_price_filter(client):
    events = client.get("/api/events", params={"city": "Nashville", "max_price": 35}).json()["events"]
    for e in events:
        assert e["is_free"] or (e["price"] and e["price"]["min"] <= 35)


def test_calendar_ics_download(client):
    # Fixture contains this id.
    r = client.get("/api/events/calendar.ics", params={"id": "jambase:11500001"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("BEGIN:VCALENDAR")


def test_calendar_ics_missing_event_404(client):
    r = client.get("/api/events/calendar.ics", params={"id": "jambase:doesnotexist"})
    assert r.status_code == 404


def test_when_preset_accepted(client):
    r = client.get("/api/events", params={"city": "Nashville", "when": "weekend"})
    assert r.status_code == 200
