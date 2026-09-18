"""Pure helpers for the leasing concierge (no DB / LLM imports)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, time, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

PROPERTY_NAME = "The Standard Residences"
PROPERTY_ADDRESS = "1001 Julia St, New Orleans, LA 70113"
PROPERTY_LAT = 29.9437
PROPERTY_LON = -90.0749
PROPERTY_TZ = ZoneInfo("America/Chicago")
PROPERTY_PHONE = "(504) 555-0199"
OFFICE_HOURS = "Mon–Sat 10:00 AM – 6:00 PM CT · After-hours concierge 24/7"

WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

FAIR_HOUSING_REFUSAL = (
    "I cannot provide commentary or opinions "
    "on neighborhood safety, crime statistics, or local demographics. "
    "I can, however, provide verified floor plans, unit specs, pricing, and schedule tours."
)

FAIR_HOUSING_PATTERNS = [
    r"\b(crime rate|crime stats?|crime statistic|how safe is|is (it|the area|the neighborhood|this area|this neighborhood) safe|dangerous (area|neighborhood)|ghetto|sketchy (area|neighborhood))\b",
    r"\b(racial makeup|ethnic makeup|demographics? of|what race|percent(age)? (black|white|hispanic|asian)|mostly (black|white|hispanic|asian))\b",
    r"\b(near(by)? (a |the )?(church|mosque|synagogue|temple)|religious makeup)\b",
    r"\b(adults only|no kids allowed|too many (kids|children)|bachelor pad)\b",
]

STUDIO_PHOTOS = [
    "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800",
    "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=800",
]
ONE_BED_PHOTOS = [
    "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800",
    "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=800",
]
TWO_BED_PHOTOS = [
    "https://images.unsplash.com/photo-1502005229762-ae1b46000c5e?w=800",
    "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800",
]
THREE_BED_PHOTOS = [
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800",
    "https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3?w=800",
]


def photos_for_bedrooms(bedrooms: int) -> list[str]:
    if bedrooms <= 0:
        return list(STUDIO_PHOTOS)
    if bedrooms == 1:
        return list(ONE_BED_PHOTOS)
    if bedrooms == 2:
        return list(TWO_BED_PHOTOS)
    return list(THREE_BED_PHOTOS)


def concession_for_days_vacant(days: int) -> Optional[str]:
    if days >= 60:
        return "Special Promotion: $750 off 1st month's rent + Waived $100 Admin Fee!"
    if days >= 45:
        return "Move-in Special: $500 off 1st month's rent!"
    return None


def staggered_vacant_since(index: int, now: Optional[datetime] = None) -> datetime:
    """Spread demo units across 0 / 18 / 32 / 48 / 62 / 80 days vacant."""
    offsets = [8, 18, 32, 48, 62, 80]
    moment = now or datetime.now(timezone.utc)
    return moment - timedelta(days=offsets[index % len(offsets)])


def parse_booking_datetime(value: str, now: Optional[datetime] = None) -> datetime:
    """Parse an explicit time; reject ambiguous dates, zones and DST transitions."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Tour date/time is required.")
    text = value.strip()
    if not re.search(r"\d{1,2}:\d{2}|\d{1,2}\s*[ap]\.?m", text, re.I):
        raise ValueError("Please specify a time, such as 'tomorrow at 2 PM'.")

    def localize(moment, zone):
        if moment.tzinfo is not None:
            return moment.astimezone(timezone.utc)
        local = moment.replace(tzinfo=zone)
        if local.utcoffset() != local.replace(fold=1).utcoffset():
            raise ValueError("This local time is ambiguous or nonexistent due to daylight saving time. Specify an ISO timestamp with an offset.")
        return local.astimezone(timezone.utc)

    try:
        iso = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        iso = None
    if iso is not None:
        return localize(iso, PROPERTY_TZ)

    zones = {"utc": timezone.utc, "gmt": timezone.utc,
             "central": PROPERTY_TZ, "ct": PROPERTY_TZ,
             "pacific": ZoneInfo("America/Los_Angeles"), "pt": ZoneInfo("America/Los_Angeles"),
             "eastern": ZoneInfo("America/New_York"), "et": ZoneInfo("America/New_York"),
             "mountain": ZoneInfo("America/Denver"), "mt": ZoneInfo("America/Denver")}
    zone = PROPERTY_TZ
    match = re.search(r"\s+(UTC|GMT|Central|CT|Pacific|PT|Eastern|ET|Mountain|MT)(?:\s+time)?$", text, re.I)
    if match:
        zone = zones[match.group(1).lower()]
        text = text[:match.start()].strip()
    moment = (now or datetime.now(timezone.utc)).astimezone(zone)
    relative = re.fullmatch(
        r"(day after tomorrow|tomorrow|today|(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun))"
        r"\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", text, re.I)
    if relative:
        day, hour, minute, ampm = relative.groups()
        hour, minute = int(hour), int(minute or 0)
        if ampm:
            if not 1 <= hour <= 12:
                raise ValueError("Use an hour between 1 and 12 with AM or PM.")
            hour = hour % 12 + (12 if ampm.lower().startswith("p") else 0)
        elif relative.group(3) is None:
            raise ValueError("Specify AM/PM or use a 24-hour time such as 14:00.")
        day = day.lower()
        offsets = {"today": 0, "tomorrow": 1, "day after tomorrow": 2}
        if day in offsets:
            delta = offsets[day]
        else:
            wd = WEEKDAYS[day.removeprefix("next ")]
            delta = (wd - moment.weekday()) % 7
            if day.startswith("next "):
                delta = 7 - moment.weekday() + wd
        target = moment.date() + timedelta(days=delta)
        return localize(datetime.combine(target, time(hour, minute)), zone)

    # Explicit dates only here; never infer a date from a time-only request.
    if not re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d", text, re.I):
        raise ValueError("Please provide an explicit date and time, and a supported timezone or ISO offset.")
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", date_parser.UnknownTimezoneWarning)
            parsed = date_parser.parse(text, fuzzy=False, default=moment.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
        return localize(parsed, zone)
    except (ValueError, OverflowError, date_parser.UnknownTimezoneWarning) as exc:
        raise ValueError("Use a valid date/time with a supported timezone or ISO offset.") from exc


def validate_tour_time(candidate: datetime, now: Optional[datetime] = None) -> None:
    """One rule shared by suggestions, bookings and data reconciliation."""
    moment = now or datetime.now(timezone.utc)
    local = candidate.astimezone(PROPERTY_TZ)
    if candidate < moment + timedelta(hours=2):
        raise ValueError("Tours require at least two hours' notice.")
    if local.weekday() == 6 or not time(10) <= local.time().replace(tzinfo=None) <= time(17, 15):
        raise ValueError("Tours start Monday-Saturday, 10 AM to 5:15 PM Central.")
    if local.minute % 15 or local.second or local.microsecond:
        raise ValueError("Tour start times must be on a 15-minute boundary.")


def has_tour_collision(
    candidate: datetime,
    existing: Iterable[datetime],
    buffer_minutes: int = 45,
) -> Optional[datetime]:
    buffer = timedelta(minutes=buffer_minutes)
    cand = candidate.astimezone(timezone.utc)
    for raw in existing:
        other = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        other = other.astimezone(timezone.utc)
        if abs(other - cand) < buffer:
            return other
    return None


def iter_tour_slot_starts(now: Optional[datetime] = None, days_ahead: int = 14):
    now_local = (now or datetime.now(timezone.utc)).astimezone(PROPERTY_TZ)
    for day_offset in range(0, days_ahead):
        day = now_local.date() + timedelta(days=day_offset)
        if day.weekday() == 6:
            continue
        slot = datetime.combine(day, time(10, 0), tzinfo=PROPERTY_TZ)
        last = datetime.combine(day, time(17, 15), tzinfo=PROPERTY_TZ)
        while slot <= last:
            try:
                validate_tour_time(slot, now=now)
            except ValueError:
                pass
            else:
                yield slot
            slot += timedelta(minutes=15)


def next_open_tour_slots(
    existing: Iterable[datetime],
    count: int = 8,
    now: Optional[datetime] = None,
) -> list[datetime]:
    if count <= 0:
        return []
    existing_list = list(existing)
    open_slots = []
    for slot in iter_tour_slot_starts(now=now):
        if has_tour_collision(slot, existing_list) is None:
            open_slots.append(slot.astimezone(timezone.utc))
            if len(open_slots) >= count:
                break
    return open_slots


def format_slot_local(dt: datetime) -> str:
    return dt.astimezone(PROPERTY_TZ).strftime("%A, %b %d at %I:%M %p CT")


def build_tour_ics(
    unit_number: str,
    prospect_name: str,
    prospect_email: str,
    start_utc: datetime,
    tour_type: str,
    tour_id: str,
) -> str:
    start = start_utc.astimezone(timezone.utc)
    end = start + timedelta(minutes=45)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = f"{tour_id or uuid.uuid4()}@standardresidences.local"

    def fmt(moment: datetime) -> str:
        return moment.strftime("%Y%m%dT%H%M%SZ")

    def escape_text(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")

    summary = f"Tour Unit {unit_number} — {PROPERTY_NAME}"
    description = (
        f"{tour_type.replace('_', ' ').title()} tour for {prospect_name}. "
        f"Bring a photo ID. Visitor parking in the courtyard."
    )
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//The Standard Residences//Leasing Concierge//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{fmt(start)}",
            f"DTEND:{fmt(end)}",
            f"SUMMARY:{escape_text(summary)}",
            f"LOCATION:{escape_text(PROPERTY_ADDRESS)}",
            f"DESCRIPTION:{escape_text(description)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def fair_housing_refusal(text: str) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None
    clean = text.lower()
    for pattern in FAIR_HOUSING_PATTERNS:
        if re.search(pattern, clean):
            return FAIR_HOUSING_REFUSAL
    return None


def osm_embed_url() -> str:
    lat, lon = PROPERTY_LAT, PROPERTY_LON
    delta = 0.006
    bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
    return (
        "https://www.openstreetmap.org/export/embed.html"
        f"?bbox={bbox}&layer=mapnik&marker={lat}%2C{lon}"
    )
