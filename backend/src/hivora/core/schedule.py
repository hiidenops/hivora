"""Simple schedules (every day / week at a local time, every N hours), shared by
backups and scheduled tasks."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Schedule(Protocol):
    frequency: str  # daily, weekly, hours
    hour: int
    minute: int
    weekday: int  # weekly: 0 = Monday
    every_hours: int


def local_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def next_run(s: Schedule, after: datetime, tz: ZoneInfo) -> datetime:
    """The first run strictly after ``after`` (UTC), for a schedule in local time ``tz``."""
    if s.frequency == "hours":
        return (after + timedelta(hours=max(1, s.every_hours))).replace(second=0, microsecond=0)
    local = after.astimezone(tz)
    at = local.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
    if s.frequency == "weekly":
        at += timedelta(days=(s.weekday - at.weekday()) % 7)
        step = timedelta(days=7)
    else:
        step = timedelta(days=1)
    while at <= local:
        at += step
    return at.astimezone(UTC)
