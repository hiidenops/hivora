"""Host port conflict detection (F-09), before anything is deployed."""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.models import Application, PortBinding, Service
from hivora.state import StateStore
from hivora.templates import PortPlan

MAX_PORT = 65535


@dataclass(frozen=True, slots=True)
class PortConflict:
    port: int
    protocol: str
    used_by: str
    suggestion: int | None


async def used_ports(
    session: AsyncSession, state: StateStore, *, exclude_app: str
) -> dict[tuple[int, str], str]:
    """(port, protocol) -> owner, from running containers and declared intents.

    Declared bindings count even when the app is stopped: starting it later
    must not fail. Host IPs are ignored on purpose (conservative).
    """
    used: dict[tuple[int, str], str] = {}
    for container in state.containers():
        owner = state.key_of(container) or container.name
        if owner == exclude_app:
            continue
        for p in container.ports:
            if p.host_port:
                used[(p.host_port, p.protocol)] = owner
    rows = await session.execute(
        select(PortBinding.host_port, PortBinding.protocol, Application.slug)
        .join(Service, PortBinding.service_id == Service.id)
        .join(Application, Service.app_id == Application.id)
        .where(PortBinding.host_port.is_not(None), Application.slug != exclude_app)
    )
    for port, protocol, slug in rows:
        used.setdefault((port, protocol), slug)
    return used


def find_conflicts(
    plans: Iterable[PortPlan], used: dict[tuple[int, str], str]
) -> list[PortConflict]:
    taken = dict(used)
    conflicts = []
    for plan in plans:
        if plan.host_port is None:
            continue
        key = (plan.host_port, plan.protocol)
        if key in taken:
            conflicts.append(
                PortConflict(
                    plan.host_port,
                    plan.protocol,
                    taken[key],
                    _suggest(plan.host_port, plan.protocol, taken),
                )
            )
        else:
            taken[key] = f"{plan.service} (this app)"
    return conflicts


def _suggest(port: int, protocol: str, taken: dict[tuple[int, str], str]) -> int | None:
    for candidate in range(port + 1, MAX_PORT + 1):
        if (candidate, protocol) not in taken:
            return candidate
    return None
