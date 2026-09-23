"""Keeps the StateStore in sync with Docker and publishes changes on the bus.

Events published:
- ``state.container.changed`` {id, app, state, health}
- ``state.container.removed`` {id, app}
- ``state.app.changed`` {app, status, previous}
- ``state.synced`` after each full resynchronization
"""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from hivora.core.events import EventBus
from hivora.docker_gateway import (
    ContainerInfo,
    ContainerNotFoundError,
    DockerEvent,
    DockerGateway,
)
from hivora.state.status import AppStatus
from hivora.state.store import StateStore, app_key, app_key_from_labels

logger = logging.getLogger(__name__)

# Container actions that can change what we display; others (exec_*, attach,
# top, resize...) are ignored to avoid needless inspections.
_RELEVANT = frozenset(
    {
        "create",
        "start",
        "restart",
        "stop",
        "die",
        "kill",
        "oom",
        "pause",
        "unpause",
        "rename",
        "update",
        "destroy",
        "health_status",
    }
)


def _action_name(action: str) -> str:
    # "health_status: healthy" -> "health_status"
    return action.split(":", 1)[0].strip()


class StateService:
    def __init__(
        self,
        gateway: DockerGateway,
        bus: EventBus,
        store: StateStore | None = None,
        *,
        reconnect_delays: tuple[float, ...] = (0.5, 1, 2, 5, 10),
    ) -> None:
        self.gateway = gateway
        self.bus = bus
        self.store = store or StateStore()
        self._delays = reconnect_delays
        self._task: asyncio.Task[None] | None = None
        self._synced = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="state-service")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def wait_synced(self) -> None:
        await self._synced.wait()

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                await self._follow()
                attempt = 0  # stream ended cleanly: reconnect immediately
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = self._delays[min(attempt, len(self._delays) - 1)]
                logger.warning(
                    "docker events stream failed, retrying",
                    exc_info=True,
                    extra={"retry_in": delay},
                )
                attempt += 1
                await asyncio.sleep(delay)

    async def _follow(self) -> None:
        # Ask Docker to replay events from just before the listing, so nothing
        # happening during it is lost. Replayed events are idempotent.
        since = datetime.now(UTC) - timedelta(seconds=1)
        await self._resync()
        events = self.gateway.events(since=since)
        try:
            async for event in events:
                await self._handle(event)
        finally:
            await events.aclose()

    async def _resync(self) -> None:
        before = {k: a.status for k, a in self.store.apps().items()}
        self.store.replace_all(await self.gateway.list_containers())
        after = self.store.apps()
        for key in before.keys() | after.keys():
            self._publish_app_if_changed(key, before.get(key, AppStatus.MISSING))
        self._synced.set()
        self.bus.publish("state.synced", containers=len(self.store.containers()))

    async def _handle(self, event: DockerEvent) -> None:
        if event.type != "container":
            return
        action = _action_name(event.action)
        if action not in _RELEVANT:
            return
        # Labels are immutable for a container's lifetime: its app never changes.
        known = self.store.get(event.actor_id)
        key = app_key(known) if known else app_key_from_labels(event.attributes)
        before = self.store.app(key).status if key else None

        # `docker stop` emits kill -> die -> stop; a crash only emits die.
        # Marking on kill avoids a transient "error" between die and stop.
        if action in ("kill", "stop"):
            self.store.mark_stop_requested(event.actor_id)
        elif action in ("start", "restart"):
            self.store.clear_stop_requested(event.actor_id)

        if action == "destroy":
            self.store.remove(event.actor_id)
            self.bus.publish("state.container.removed", id=event.actor_id, app=key)
        else:
            try:
                container = await self.gateway.get_container(event.actor_id)
            except ContainerNotFoundError:
                self.store.remove(event.actor_id)
                self.bus.publish("state.container.removed", id=event.actor_id, app=key)
            else:
                self._upsert(container)

        if key and before is not None:
            self._publish_app_if_changed(key, before)

    def _upsert(self, container: ContainerInfo) -> None:
        self.store.upsert(container)
        self.bus.publish(
            "state.container.changed",
            id=container.id,
            app=app_key(container),
            state=container.state.value,
            health=container.health.value,
        )

    def _publish_app_if_changed(self, key: str, previous: AppStatus) -> None:
        current = self.store.app(key).status
        if current != previous:
            self.bus.publish(
                "state.app.changed", app=key, status=current.value, previous=previous.value
            )
