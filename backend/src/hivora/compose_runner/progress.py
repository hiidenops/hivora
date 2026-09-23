"""Parsing of ``docker compose --progress json`` lines (emitted on stderr)."""

import json
from dataclasses import dataclass
from enum import StrEnum


class ProgressStatus(StrEnum):
    WORKING = "working"
    DONE = "done"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One progress update.

    ``resource`` is e.g. ``Image traefik/whoami:v1.10``, ``Network x_default``
    or ``Container x-web-1``; layer updates carry the image as ``parent``.
    """

    resource: str
    status: ProgressStatus
    text: str
    parent: str | None = None
    details: str | None = None
    current: int | None = None
    total: int | None = None
    percent: int | None = None


def parse_progress_line(line: str) -> ProgressEvent | None:
    """Return None for blank lines; non-JSON lines become INFO events."""
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return ProgressEvent(resource="", status=ProgressStatus.INFO, text=line)
    if not isinstance(raw, dict):
        return ProgressEvent(resource="", status=ProgressStatus.INFO, text=line)
    if raw.get("error") is True:
        return ProgressEvent(resource="", status=ProgressStatus.ERROR, text=str(raw.get("message")))
    try:
        status = ProgressStatus(str(raw.get("status", "")).lower())
    except ValueError:
        status = ProgressStatus.INFO
    return ProgressEvent(
        resource=str(raw.get("id", "")),
        status=status,
        text=str(raw.get("text", "")),
        parent=raw.get("parent_id"),
        details=raw.get("details") or None,
        current=raw.get("current"),
        total=raw.get("total"),
        percent=raw.get("percent"),
    )
