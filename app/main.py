"""FastAPI application entrypoint.

Wires shared resources (HTTP client, cache, events service) with a lifespan so
they're created once and cleaned up on shutdown, mounts the JSON API, and serves
the static UI. Run with: `uvicorn app.main:app --reload`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router as api_router
from app.config import get_settings
from app.services.cache import TTLCache
from app.services.events_service import build_events_service
from app.services.http_client import ResilientClient

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = ResilientClient(
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
    )
    cache = TTLCache()

    app.state.settings = settings
    app.state.http_client = client
    app.state.cache = cache
    app.state.events_service = build_events_service(settings, client, cache)

    try:
        yield
    finally:
        await client.aclose()


app = FastAPI(
    title="Local Events Discovery",
    version=__version__,
    summary="Find upcoming events near you, powered by the JamBase Concert Data API.",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


# Static assets (JS/CSS). Mounted last so it doesn't shadow API routes.
app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")
