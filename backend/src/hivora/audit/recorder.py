"""Turns bus events into audit rows (docs section 6: audit listens to the bus)."""

import asyncio
import logging
from contextlib import suppress
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.audit.models import AuditLog
from hivora.core.events import Event, EventBus

logger = logging.getLogger(__name__)

# Topics worth auditing. Secrets never travel on the bus, so payloads are safe.
AUDITED_PREFIXES = (
    "auth.",
    "user.",
    "app.",
    "backup.",
    "task.",
    "hostfw.",
    "zone.",
    "vpn.",
    "job.finished",
    "jobs.cleared",
    "console.",
    "settings.",
    "game.",
    "site.",
)
_FAILED = {"auth.login_failed"}
_BATCH_DELAY_S = 0.5


def to_row(event: Event) -> AuditLog:
    payload: dict[str, Any] = dict(event.payload)
    actor = event.actor
    target = payload.pop("target", None) or payload.get("app") or payload.get("username")
    result = "failed" if event.topic in _FAILED else "ok"
    if event.topic == "job.finished":
        result = str(payload.get("status", "ok"))
    return AuditLog(
        ts=event.ts,
        user_id=actor.user_id if actor else None,
        username=actor.username if actor else payload.get("username"),
        ip=(actor.ip if actor else None) or payload.pop("ip", None),
        action=event.topic,
        target=str(target) if target is not None else None,
        payload=payload,
        result=result,
    )


class AuditRecorder:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self.sessions = sessions
        self.bus = bus
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        sub = self.bus.subscribe("*", maxsize=10_000)
        self._task = asyncio.create_task(self._run(sub), name="audit-recorder")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    # --- the trail (read and emptied by the audit routes) ----------------------
    async def entries(self, before_id: int | None, limit: int) -> list[AuditLog]:
        """Newest first; ``before_id`` pages back through older entries."""
        query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if before_id is not None:
            query = query.where(AuditLog.id < before_id)
        async with self.sessions() as session:
            return list(await session.scalars(query))

    async def clear(self) -> int:
        """Empty the trail, leaving one entry that says who emptied it and when.

        That entry is written here, in the same transaction, not published on the bus:
        it must be the only one left, right away.
        """
        async with self.sessions() as session, session.begin():
            deleted = int(await session.scalar(select(func.count(AuditLog.id))) or 0)
            await session.execute(delete(AuditLog))
            session.add(to_row(Event("audit.cleared", {"deleted": deleted})))
        return deleted

    async def _run(self, sub: Any) -> None:
        async with sub:
            while True:
                batch = [await sub.queue.get()]
                await asyncio.sleep(_BATCH_DELAY_S)  # group bursts into one write
                while not sub.queue.empty():
                    batch.append(sub.queue.get_nowait())
                rows = [to_row(e) for e in batch if e.topic.startswith(AUDITED_PREFIXES)]
                if not rows:
                    continue
                try:
                    async with self.sessions() as session, session.begin():
                        session.add_all(rows)
                except Exception:
                    logger.exception("failed to write audit rows", extra={"count": len(rows)})
