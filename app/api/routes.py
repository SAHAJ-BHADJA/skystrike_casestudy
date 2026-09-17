"""HTTP API surface. Thin: parse/validate query -> service -> typed response."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.models import EventQuery, EventSearchResponse
from app.services.calendar import build_ics
from app.services.events_service import EventsService

router = APIRouter(prefix="/api", tags=["events"])


def get_service(request: Request) -> EventsService:
    return request.app.state.events_service


def _preset_range(when: str | None, today: date) -> tuple[date | None, date | None]:
    """Map a convenience preset to a concrete date range."""
    if when == "today":
        return today, today
    if when == "week":
        return today, today + timedelta(days=6)
    if when == "weekend":
        wd = today.weekday()  # Mon=0 .. Sun=6
        if wd <= 4:
            sat = today + timedelta(days=5 - wd)
            return sat, sat + timedelta(days=1)
        if wd == 5:  # Saturday
            return today, today + timedelta(days=1)
        return today, today  # Sunday
    return None, None


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "sample_data": request.app.state.events_service._sample_data,  # noqa: SLF001
    }


@router.get("/events/calendar.ics")
async def event_calendar(
    id: str = Query(..., description="Namespaced event id, e.g. 'jambase:16151055'"),
    service: EventsService = Depends(get_service),
) -> Response:
    """Download a single event as an .ics calendar file."""
    event = await service.get_event(id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"No event found for id '{id}'.")
    ics = build_ics(event)
    filename = "".join(c for c in event.title if c.isalnum() or c in " -_")[:50].strip() or "event"
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}.ics"'},
    )


@router.get("/events", response_model=EventSearchResponse)
async def search_events(
    city: str | None = Query(None, description="City name, e.g. 'Nashville'"),
    state: str | None = Query(None, description="2-letter region code, e.g. 'TN'", max_length=3),
    country: str = Query("US", description="ISO-3166 alpha-2 country", max_length=2),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(40.0, gt=0, le=500),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    when: str | None = Query(None, pattern="^(today|weekend|week)$", description="Date preset"),
    genre: str | None = Query(None, description="Genre slug, e.g. 'rock'"),
    keyword: str | None = Query(None, description="Match on event title"),
    free_only: bool = Query(False, description="Only free events"),
    max_price: float | None = Query(None, ge=0, description="Max ticket price"),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    sort: str = Query("date", pattern="^(date|relevance)$"),
    service: EventsService = Depends(get_service),
) -> EventSearchResponse:
    has_geo = lat is not None and lon is not None
    if not has_geo and not city and not state:
        raise HTTPException(
            status_code=422,
            detail="Provide a location: either `city` (+optional `state`) or `lat`+`lon`.",
        )
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="`lat` and `lon` must be provided together.")

    # Explicit dates win; otherwise a preset fills the range.
    if date_from is None and date_to is None and when:
        date_from, date_to = _preset_range(when, date.today())

    query = EventQuery(
        city=city,
        state=state.upper() if state else None,
        country=country.upper(),
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        date_from=date_from,
        date_to=date_to,
        genre=genre,
        keyword=keyword,
        free_only=free_only,
        max_price=max_price,
        page=page,
        per_page=per_page,
        sort=sort,
    )
    return await service.search(query)
