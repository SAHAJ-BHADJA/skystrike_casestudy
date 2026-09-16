# Local Events Discovery

Find upcoming events near you and decide which one is worth going to. A Python
**FastAPI** backend pulls live data from the **JamBase Concert Data API**, normalizes
it, and layers on decision-support signals (price, timing, venue size, distance);
a lightweight vanilla-JS UI presents them as a clean, scannable feed.

> **Case study for Skystrike.** Built to demonstrate backend design, reliability,
> and extensibility. See [`WRITEUP.md`](WRITEUP.md) for the design writeup, AI-usage
> notes, limitations, the 10-provider evolution plan, and self-grades.

---

## Quick start (zero setup)

The app ships with a bundled sample dataset, so it runs with **no API key**.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000**. You'll see a "sample data" banner until you add a key.

### Live data (JamBase)

Grab a free 14-day trial key at
<https://data.jambase.com/api/docs/getting-started>, then:

```bash
cp .env.example .env      # Windows: copy .env.example .env
# edit .env and set JAMBASE_API_KEY=...
uvicorn app.main:app --reload
```

The app now queries JamBase live; the banner disappears.

---

## Using it

- Search by **city** (+ optional state), or hit the API directly with **lat/lon + radius**.
- Filter by **date range** and **genre**; sort by **soonest** or **best match**.
- Each card surfaces the facts you actually decide on: price/free, how soon it is,
  venue size (intimate → arena), distance, and lineup depth.

## API

Interactive docs at **http://localhost:8000/docs** (FastAPI/OpenAPI).

| Endpoint | Description |
|---|---|
| `GET /api/events` | Search events. Location via `city`(+`state`) **or** `lat`+`lon`(+`radius_km`). Also: `date_from`, `date_to`, `genre`, `keyword`, `page`, `per_page`, `sort=date\|relevance`. |
| `GET /api/health` | Liveness + whether sample data is in use. |

```bash
curl "http://localhost:8000/api/events?city=Nashville&state=TN&sort=relevance"
curl "http://localhost:8000/api/events?lat=36.16&lon=-86.78&radius_km=25"
```

## Tests

```bash
pytest -q
```

23 tests cover normalization, the retry/backoff policy (mocked transport), the
ranking layer, the live provider path, and the HTTP API.

## Project layout

```
app/
  main.py               # FastAPI app + lifespan (shared client/cache/service)
  config.py             # settings (env / .env), safe defaults
  models.py             # normalized, provider-agnostic domain models
  api/routes.py         # thin HTTP layer
  providers/
    base.py             # EventProvider interface — the extensibility seam
    jambase.py          # JamBase v3 adapter + normalizer (pure map_event)
    sample.py           # zero-setup fallback (reuses the JamBase normalizer)
  services/
    http_client.py      # resilient httpx client: retry + backoff + jitter, 429-aware
    cache.py            # async TTL cache (request reduction)
    ranking.py          # deterministic decision-support signals + scoring
    events_service.py   # concurrent fan-out, merge, dedupe, enrich, sort
  fixtures/             # sample data in raw JamBase shape
web/                    # index.html + app.js + styles.css (no build step)
tests/
```

## Time spent

~2 hours. See [`WRITEUP.md`](WRITEUP.md) for the full breakdown.
