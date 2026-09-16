"""Sample-data provider used when no JamBase API key is configured.

It reads a bundled fixture in *raw JamBase shape* and runs it through the exact
same `map_event` normalizer the live provider uses — so the sample path exercises
real mapping code, and a reviewer can run the app with zero setup. Light in-memory
filtering (date / keyword / genre) mimics the upstream query semantics.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import EventQuery, Pagination, ProviderResult
from app.providers.base import EventProvider
from app.providers.jambase import map_event

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jambase_events.json"


@lru_cache
def _load_raw() -> list[dict]:
    with _FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh).get("events", [])


class SampleProvider(EventProvider):
    key = "jambase"  # same key: sample data represents JamBase content

    async def search(self, query: EventQuery) -> ProviderResult:
        events = [map_event(raw) for raw in _load_raw()]

        if query.date_from:
            events = [e for e in events if e.start_local and e.start_local.date() >= query.date_from]
        if query.date_to:
            events = [e for e in events if e.start_local and e.start_local.date() <= query.date_to]
        if query.genre:
            g = query.genre.lower()
            events = [e for e in events if any(g in gg.lower() for gg in e.genres)]
        if query.keyword:
            kw = query.keyword.lower()
            events = [e for e in events if kw in e.title.lower()]

        return ProviderResult(
            source=self.key,
            events=events,
            pagination=Pagination(page=1, per_page=len(events), total_items=len(events), total_pages=1),
        )
