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
        merged = self._apply_filters(merged, query)
        ranking.enrich(merged, query)
        ordered = ranking.sort_events(merged, query.sort)

        return EventSearchResponse(
            query_location=query.location_label,
            events=ordered,
            pagination=self._merge_pagination(results, len(ordered)),
            sources=results,
            sample_data=self._sample_data,
        )

    async def get_event(self, event_id: str) -> Event | None:
        """Look up one event across providers (first match wins)."""
        for provider in self._providers:
            found = await provider.get_event(event_id)
            if found is not None:
                return found
        return None

    @staticmethod
    def _apply_filters(events: list[Event], query: EventQuery) -> list[Event]:
        """Decision filters JamBase can't express upstream, applied uniformly.

        Keeping these here (not per-provider) means they behave identically no
        matter how many feeds contribute events.
        """
        out = events
        if query.free_only:
            out = [e for e in out if e.is_free]
        if query.max_price is not None:
            out = [
                e for e in out
                if e.is_free or (e.price and e.price.min is not None and e.price.min <= query.max_price)
            ]
        return out

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
