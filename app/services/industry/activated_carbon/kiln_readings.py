"""30-minute kiln readings for T1, T2, T3, dampers, and boiler pressure.

A reading belongs to a plant-clock window of 30 minutes. The window that is
open now can be saved. A window that has already closed without a reading is
locked until a plant manager approves it. Existing kiln and lot subjects are
not rewritten; each saved reading adds captures on its own reading subject.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

INTERVAL_MINUTES = 30
MAX_LOCKED_SLOTS = 48

READING_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("t1", "T1", "°C"),
    ("t2", "T2", "°C"),
    ("t3", "T3", "°C"),
    ("main_damper", "Main Damper (MD)", "%"),
    ("boiler_damper", "Boiler Damper (BD)", "%"),
    ("induced_draft", "Induced Draft (ID)", "%"),
    ("boiler_pressure", "Boiler Pressure", ""),
)

PERCENT_KEYS = frozenset({"main_damper", "boiler_damper", "induced_draft"})

READING_KEYS: tuple[str, ...] = tuple(row[0] for row in READING_FIELDS)


def floor_slot(moment: datetime) -> datetime:
    """Start of the 30-minute window that contains moment, in that timezone."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    minute = 0 if moment.minute < 30 else 30
    return moment.replace(minute=minute, second=0, microsecond=0)


def slot_end(start: datetime) -> datetime:
    return start + timedelta(minutes=INTERVAL_MINUTES)


def slot_key(start: datetime) -> str:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def slot_label(start: datetime) -> str:
    end = slot_end(start)
    return f"{start.strftime('%d %b %H:%M')} – {end.strftime('%H:%M')}"


def parse_slot(value: Any, tzinfo) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return floor_slot(parsed.astimezone(tzinfo))


def required_readings(values: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    missing: list[str] = []
    labels = {key: label for key, label, _unit in READING_FIELDS}
    for key in READING_KEYS:
        raw = values.get(key)
        if raw is None or raw == "":
            missing.append(labels[key])
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            missing.append(labels[key])
            continue
        if number < 0:
            raise ValueError(f"{labels[key]} cannot be negative.")
        if key in PERCENT_KEYS and number > 100:
            raise ValueError(f"{labels[key]} is a percentage from 0 to 100.")
        cleaned[key] = number
    if missing:
        raise ValueError("Enter " + ", ".join(missing) + ".")
    return cleaned


def saved_slot_keys(history: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in history:
        if not isinstance(row, dict):
            continue
        raw = row.get("slot_start") or row.get("recorded_at")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        keys.add(slot_key(floor_slot(parsed)))
    return keys


def approved_slot_keys(approvals: list[dict]) -> set[str]:
    keys: set[str] = set()
    for row in approvals:
        if not isinstance(row, dict) or row.get("used"):
            continue
        raw = row.get("slot_start")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        keys.add(slot_key(floor_slot(parsed)))
    return keys


def missed_slots(now: datetime, saved: set[str]) -> list[datetime]:
    """Closed windows with no reading after the kiln's first saved reading, up to one day."""
    if not saved:
        return []
    current = floor_slot(now)
    window: list[datetime] = []
    cursor = current - timedelta(minutes=INTERVAL_MINUTES)
    for _ in range(MAX_LOCKED_SLOTS):
        window.append(cursor)
        cursor = cursor - timedelta(minutes=INTERVAL_MINUTES)
    window.reverse()
    started = False
    missed: list[datetime] = []
    for start in window:
        if slot_key(start) in saved:
            started = True
            continue
        if started:
            missed.append(start)
    return missed


def resolve_slot(
    now: datetime,
    saved: set[str],
    approved: set[str],
    requested: datetime | None,
) -> datetime:
    current = floor_slot(now)
    target = current if requested is None else floor_slot(requested.astimezone(now.tzinfo))
    key = slot_key(target)
    if key in saved:
        raise ValueError("This 30-minute reading is already saved.")
    if slot_key(target) == slot_key(current):
        return target
    if target > current:
        raise ValueError("That reading time has not started.")
    if key not in approved:
        raise ValueError(
            "This reading is locked. A plant manager must approve it before it can be entered."
        )
    return target


def assert_slot_needs_approval(now: datetime, saved: set[str], requested: datetime) -> datetime:
    current = floor_slot(now)
    target = floor_slot(requested.astimezone(now.tzinfo))
    if slot_key(target) >= slot_key(current):
        raise ValueError("The current reading is still open. It does not need approval.")
    if slot_key(target) in saved:
        raise ValueError("That reading is already saved.")
    return target
