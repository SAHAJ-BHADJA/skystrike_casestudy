"""Build an RFC 5545 iCalendar (.ics) file for a single event.

Pure and dependency-free so it's trivially testable. Times are emitted as
*floating* local time (no `Z`, no offset) because JamBase reports venue-local wall
time without an offset — floating time is exactly the right iCalendar semantics for
"8pm at the venue, whatever timezone that is", and every calendar app honors it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Event


def _escape(text: str) -> str:
    """Escape per RFC 5545 §3.3.11 (backslash, comma, semicolon, newline)."""
    return (
        text.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold long lines to 75 octets with a leading space on continuations."""
    out, current = [], line
    limit = 74
    while len(current) > limit:
        out.append(current[:limit])
        current = " " + current[limit:]
    out.append(current)
    return "\r\n".join(out)


def _dt(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def build_ics(event: Event, *, now: datetime | None = None) -> str:
    """Return the full VCALENDAR text for one event."""
    now = now or datetime.now(UTC)
    start = event.start_local
    # Default a 2-hour block when the feed gives no end time.
    end = event.end_local or (start + timedelta(hours=2) if start else None)

    location = ", ".join(
        p for p in (event.venue.name, event.venue.street, event.venue.locality) if p
    )
    desc_bits = []
    if event.performers:
        desc_bits.append("Lineup: " + ", ".join(p.name for p in event.performers))
    if event.price and event.price.min is not None:
        desc_bits.append(f"From {event.price.currency or 'USD'} {event.price.min:.0f}")
    if event.url:
        desc_bits.append(event.url)
    description = "\n".join(desc_bits)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//skystrike-events//local-events//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{event.id}@skystrike-events",
        f"DTSTAMP:{_dt(now)}Z",
        f"SUMMARY:{_escape(event.title)}",
    ]
    if start:
        lines.append(f"DTSTART:{_dt(start)}")
    if end:
        lines.append(f"DTEND:{_dt(end)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if event.url:
        lines.append(f"URL:{event.url}")
    lines += ["END:VEVENT", "END:VCALENDAR"]

    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
