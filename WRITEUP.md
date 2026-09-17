# Writeup — Local Events Discovery

**Time spent:** ~2.5 hours (≈20 min API research, ≈70 min backend, ≈25 min UI,
≈20 min tests + docs, ≈15 min live-API verification + a data-quality fix it caught).
Kept intentionally focused per the brief.

**Verified against live JamBase.** Runs on real v3 data with a key, and on bundled
sample data without one. Live testing immediately paid off — see the reliability note below.

---

## Technology choices

- **FastAPI + Pydantic v2** — required, and a good fit: typed request validation
  and response models come for free, and `/docs` gives reviewers an interactive
  API surface with zero extra work.
- **httpx (async)** — one async client shared across the app; lets provider
  fan-out run concurrently and makes the resilient-client wrapper straightforward.
- **Vanilla HTML/CSS/JS for the UI** — no build step, no `node_modules`, nothing to
  break at review time. The brief prioritizes backend and asks for a clean,
  functional UI, so a framework would have added setup cost without adding value here.
- **In-memory TTL cache** — dependency-free, and the `get/set` interface is a clean
  seam to swap for Redis later.
- **No database** — the app is read-through against a live API; persistence isn't
  needed for the core use case and would have spent the time budget on plumbing.

## Backend / API design

The spine of the design is a **normalized domain model** (`app/models.py`) that is
the *only* event shape the API, ranking, and UI ever see. Providers translate their
wire format into it; nothing downstream knows a provider exists. Concretely:

```
routes → EventsService → [EventProvider, ...] → normalized Event
                             ↑ resilient httpx client + TTL cache (shared)
         ranking.enrich() → decision-support signals → sort
```

- **`EventProvider` interface** (`providers/base.py`) is the extensibility seam.
  `JamBaseProvider` owns all JamBase-specific logic: Bearer auth, resolving a city
  name → `geoCityId` via `/geographies/cities`, building the `/events` query, and
  mapping schema.org-style JSON into `Event` via the pure `map_event` function.
- **Resilience is centralized** (`services/http_client.py`): GETs retry on `429`
  and `5xx` with capped exponential backoff + full jitter, and honor a
  `Retry-After` header. `4xx` fails fast. Providers **degrade gracefully** —
  an upstream error returns `ProviderResult(ok=False, error=...)` instead of
  raising, so one flaky feed never sinks a search. The response reports per-source
  status so the UI can say "X unavailable".
- **Request reduction via caching**: identical event searches are cached briefly
  (TTL), and geography ID lookups for a full day since they barely change — this
  keeps us well under upstream rate limits.
- **Decision support is deterministic** (`services/ranking.py`): distance
  (haversine), days-until, an intimate/mid/large venue descriptor, a short
  "why-go" highlight, and a transparent additive `score` with a `score_factors`
  breakdown so ranking is explainable rather than a black box. It's pure and unit-tested.
- **Thin API layer**: `routes.py` only validates input (e.g. `lat`/`lon` must be
  paired; a location is required) and delegates. Business logic lives in services.

**Reliability note (found via live testing).** JamBase's live feed sends empty
strings (`""`) for absent numeric fields like venue capacity — which the OpenAPI
spec types as a number. The sample data never hit this; the first real query did.
Because normalization is isolated in one place, the fix was a single defensive
coercion (`_to_number`) plus a regression test, with zero ripple elsewhere. This is
exactly why the normalized-model seam and "never trust upstream types" posture matter.

## UI design decisions

The card layout leads with the decisions a user actually makes: **date** and
**price/free** are the most prominent, followed by venue + locality, then
"highlight" chips (This week, intimate venue, N acts, distance) and genre tags.
It's a responsive grid, dark-themed, with loading/empty/error states and a
"sample data" banner so the reviewer always knows what they're looking at. It
does one initial search on load so the page is never empty.

## Tradeoffs made to keep it simple

- In-memory cache and no DB (single-process only — noted below).
- Sample dataset instead of requiring a key to run; the sample path deliberately
  reuses the real normalizer so it isn't throwaway code.
- Ranking weights are hand-picked and readable, not tuned/learned.
- Pagination is passed through from the provider; cross-provider merged pagination
  is simplified to a single page over the merged set.
- Genre/keyword filters on the sample path are applied in-memory to mirror the
  upstream query semantics.

## What I'd change / add with more time

- Real geospatial pagination and a "load more" / infinite scroll.
- Redis cache + a background pre-warm for popular locations (cuts p95 latency and
  upstream calls further).
- Richer product signals: "selling fast" via price-movement tracking, personalized
  ranking, save/RSVP, map view, calendar export.
- Observability: structured logging, per-provider latency/error metrics, and a
  circuit breaker to stop hammering a feed that's down.
- A typed frontend (or HTMX) and component tests if the UI grew.

## How I used AI during development

I used an AI coding assistant (Claude) throughout, and drove it deliberately:

- **API discovery**: had it read the JamBase v3 OpenAPI spec and extract the exact
  `/events` params and the `Concert`/`MusicVenue`/`Offer` schemas, so normalization
  was written against the real contract instead of guesses.
- **Scaffolding**: generated the boilerplate (models, routes, config, test setup)
  from an architecture I specified — provider interface, shared resilient client,
  deterministic ranking core.
- **Tests**: drafted the `httpx.MockTransport`-based tests for the retry policy and
  the live provider path, which I reviewed for meaningful assertions.

The division of labor: I owned the architecture and the "what matters" product
calls; AI accelerated the typing and the mechanical parts, under review.

## One thing AI got wrong that I corrected

The assistant's first cut of the JamBase provider passed the **city name straight
to `/events`** (e.g. `?city=Nashville`). That silently returns nothing — JamBase's
`/events` filters by `geoCityId`, not a name. I corrected it to a **two-step
resolution**: look up the city via `/geographies/cities` to get its `jambase:*`
ID, cache that ID for a day, then query events by ID (and skip the lookup entirely
when the user supplies lat/lon). I also refactored an early version that
**duplicated the normalizer** inside the sample provider into a single pure
`map_event` shared by both paths.

## Biggest technical limitation

The **cache and state are in-process**. Multiple workers/replicas each keep their
own cache, so hit-rate drops and rate-limit protection weakens exactly when you
scale out horizontally. It's fine for this single-process app but is the first
thing I'd replace (with Redis behind the existing `TTLCache` interface) before a
real deployment. Secondarily, there's no persistence, so cross-request analytics
(e.g. price trends) aren't possible yet.

## Evolving to 10 providers instead of JamBase

The architecture is already built for this — the provider interface is the whole
point. To onboard Ticketmaster, SeatGeek, Eventbrite, etc.:

1. **Write one adapter per provider** implementing `EventProvider`: translate the
   normalized `EventQuery` → that API's params, call it through the shared resilient
   client, and map its response to `Event`. No other layer changes.
2. **Register it** in `build_events_service`; the service already fans out
   **concurrently** and isolates failures per provider.
3. **De-duplication becomes the real work at 10 providers.** The same show appears
   on multiple feeds, so ID-based dedupe isn't enough. I'd add a fuzzy match on
   `(normalized venue + date + headliner)` and **merge** duplicates into one card
   that carries multiple ticket offers (so we can show the cheapest) — this is also
   where the most user value is (price comparison across sources).
4. **Cross-provider concerns** to formalize: a shared rate-limit/quota budget and
   circuit breaker per provider (already have retry/backoff); per-provider config
   (keys, base URLs, enable flags) driven by settings; and a normalized genre/venue
   mapping so filters and dedupe work across differing taxonomies.
5. **Scale the data path**: move from live read-through to a **bulk-ingest +
   delta-sync** model (JamBase exposes `dateModifiedFrom` for exactly this),
   writing normalized events into a store the API reads from — decoupling user
   latency from provider availability and slashing request volume.

Because everything downstream depends only on the normalized `Event`, going from 1
to 10 providers is additive, not a rewrite.

## Self-grades (A–F)

| Area | Grade | Rationale |
|---|---|---|
| **Code quality** | **A−** | Clean layering, typed models, pure/tested core, graceful degradation. Docstrings explain the *why*. Minus: no linter/CI config or type-checker in the repo given the time box. |
| **Work product** | **A−** | Runs with zero setup, real live-API integration, thoughtful product signals, 23 passing tests, and honest docs. Minus: UI is deliberately minimal. |
| **Extensibility** | **A** | The provider seam + normalized model + centralized resilience are exactly what the 10-provider question asks for; adding a feed is one adapter + one line. |
