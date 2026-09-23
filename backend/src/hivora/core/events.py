"""In-process publish/subscribe bus used to decouple modules (audit, realtime, ...)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    """``topic`` is dot-separated, e.g. ``app.deployed`` or ``docker.container.die``."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


def _matches(pattern: str, topic: str) -> bool:
    """``*`` matches everything, ``app.*`` matches ``app`` and any ``app.<...>`` topic."""
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return topic == prefix or topic.startswith(prefix + ".")
    return pattern == topic


class Subscription:
    def __init__(self, bus: "EventBus", pattern: str, maxsize: int) -> None:
        self._bus = bus
        self.pattern = pattern
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize)
        self.dropped = 0

    def _offer(self, event: Event) -> None:
        # Slow consumers must never block publishers: drop the oldest event.
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(event)

    def close(self) -> None:
        self._bus._subscriptions.discard(self)

    async def __aenter__(self) -> "Subscription":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.close()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        return await self.queue.get()


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    def subscribe(self, pattern: str = "*", maxsize: int = 1000) -> Subscription:
        sub = Subscription(self, pattern, maxsize)
        self._subscriptions.add(sub)
        return sub

    def publish(self, topic: str, **payload: Any) -> Event:
        event = Event(topic, payload)
        for sub in tuple(self._subscriptions):
            if _matches(sub.pattern, topic):
                sub._offer(event)
        return event
