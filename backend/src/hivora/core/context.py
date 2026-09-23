"""Who is acting: set per HTTP request / job, read by the event bus for auditing."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int | None
    username: str | None = None
    ip: str | None = None


current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)
