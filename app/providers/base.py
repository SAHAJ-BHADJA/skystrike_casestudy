"""The provider seam.

Every event source implements `EventProvider`. The service layer only ever talks
to this interface, so onboarding a 2nd..Nth provider (Ticketmaster, SeatGeek,
Eventbrite, ...) means writing one adapter that:

  1. translates a normalized `EventQuery` into that API's params,
  2. calls the API (via the shared resilient client), and
  3. maps the response into normalized `Event` objects.

No other layer changes. The adapter owns *all* vendor-specific knowledge.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import EventQuery, ProviderResult


class EventProvider(ABC):
    #: Stable short key used to namespace event IDs and report per-source status.
    key: str = "base"

    @abstractmethod
    async def search(self, query: EventQuery) -> ProviderResult:
        """Return normalized events for `query`.

        Implementations should degrade gracefully: on an upstream failure,
        return a `ProviderResult(ok=False, error=...)` rather than raising, so a
        single flaky feed never sinks an aggregated multi-provider search.
        """
        raise NotImplementedError
