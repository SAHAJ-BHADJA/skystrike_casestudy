"""Event search orchestration.

Fans out a single normalized query to every registered provider *concurrently*,
merges and de-duplicates the results, enriches them with decision-support signals,
and sorts them. This is where the multi-provider story lives: adding a provider is
a one-line registration change, and one slow/failing feed can't block the others.
"""
from __future__ import annotations

import asyncio

from app.config import Settings
from app.models import (
    Event,
    EventQuery,
    EventSearchResponse,
    Pagination,
    ProviderResult,
)
from app.providers.base import EventProvider
from app.services import ranking


class EventsService:
    def __init__(self, providers: list[EventProvider], *, sample_data: bool) -> None:
        self._providers = providers
        self._sample_data = sample_data

    async def search(self, query: EventQuery) -> EventSearchResponse:
        # Concurrent fan-out; each provider already degrades to ok=False on error.
        results: list[ProviderResult] = await asyncio.gather(
            *(p.search(query) for p in self._providers)
        )

        merged = self._dedupe(ev for r in results if r.ok for ev in r.events)
        ranking.enrich(merged, query)
        ordered = ranking.sort_events(merged, query.sort)

        return EventSearchResponse(
            query_location=query.location_label,
            events=ordered,
            pagination=self._merge_pagination(results, len(ordered)),
            sources=results,
            sample_data=self._sample_data,
        )

    @staticmethod
    def _dedupe(events) -> list[Event]:
        """Collapse the same event surfaced by multiple providers, keyed by id."""
        seen: dict[str, Event] = {}
        for ev in events:
            seen.setdefault(ev.id, ev)
        return list(seen.values())

    @staticmethod
    def _merge_pagination(results: list[ProviderResult], count: int) -> Pagination:
        # With a single healthy source, surface its real pagination; otherwise
        # report a synthetic single page over the merged set.
        healthy = [r for r in results if r.ok and r.pagination]
        if len(healthy) == 1:
            return healthy[0].pagination  # type: ignore[return-value]
        return Pagination(page=1, per_page=count, total_items=count, total_pages=1)


def build_events_service(
    settings: Settings, client, cache
) -> EventsService:
    """Compose the service. Swap/extend the provider list here to add feeds."""
    from app.providers.jambase import JamBaseProvider
    from app.providers.sample import SampleProvider

    if settings.jambase_enabled:
        providers: list[EventProvider] = [JamBaseProvider(settings, client, cache)]
        return EventsService(providers, sample_data=False)

    # No key configured -> zero-setup sample data.
    return EventsService([SampleProvider()], sample_data=True)
