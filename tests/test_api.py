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
