"""Small datetime helpers used by the workflow engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Naive UTC ``datetime`` (matches the existing TIMESTAMP columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_minutes(dt: datetime, minutes: float) -> datetime:
    return dt + timedelta(minutes=float(minutes))
