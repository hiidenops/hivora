"""Login throttling: after 5 failures, an exponentially growing delay (per key)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from hivora.core.clock import Clock
from hivora.core.errors import HivoraError

FREE_ATTEMPTS = 5
MAX_DELAY = timedelta(minutes=15)


class TooManyAttemptsError(HivoraError):
    code = "too_many_attempts"


@dataclass(slots=True)
class _Entry:
    failures: int = 0
    locked_until: datetime | None = None


class LoginRateLimiter:
    """In-memory: a single process serves Hivora, and a restart forgiving is fine."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: dict[str, _Entry] = {}

    def check(self, *keys: str) -> None:
        now = self._clock.now()
        waits = [
            (e.locked_until - now).total_seconds()
            for k in keys
            if (e := self._entries.get(k)) and e.locked_until and e.locked_until > now
        ]
        if waits:
            raise TooManyAttemptsError("too many failed attempts", retry_after=int(max(waits)) + 1)

    def failure(self, *keys: str) -> None:
        for key in keys:
            entry = self._entries.setdefault(key, _Entry())
            entry.failures += 1
            if entry.failures >= FREE_ATTEMPTS:
                delay = timedelta(seconds=2 ** (entry.failures - FREE_ATTEMPTS))
                entry.locked_until = self._clock.now() + min(delay, MAX_DELAY)

    def success(self, *keys: str) -> None:
        for key in keys:
            self._entries.pop(key, None)
