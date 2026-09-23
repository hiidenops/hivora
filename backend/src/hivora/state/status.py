"""Aggregated status of an application from the state of its containers."""

from collections.abc import Collection, Iterable
from enum import StrEnum

from hivora.docker_gateway import ContainerInfo, ContainerState, Health


class AppStatus(StrEnum):
    HEALTHY = "healthy"  # everything expected to run is running (and healthy)
    STARTING = "starting"  # running, health checks not settled yet
    DEGRADED = "degraded"  # some services fine, others failing or stopped
    STOPPED = "stopped"  # nothing running, no failure
    ERROR = "error"  # nothing working and at least one failure
    MISSING = "missing"  # no container at all


def _is_failed(c: ContainerInfo, stop_requested: Collection[str]) -> bool:
    if c.state in (ContainerState.RESTARTING, ContainerState.DEAD):
        return True
    if c.state is ContainerState.EXITED:
        # Exit codes after `docker stop` are app-specific (0, 2, 143...): a
        # requested stop is never a failure.
        return c.exit_code not in (0, None) and c.id not in stop_requested
    return c.state is ContainerState.RUNNING and c.health is Health.UNHEALTHY


def aggregate_status(
    containers: Iterable[ContainerInfo], stop_requested: Collection[str] = frozenset()
) -> AppStatus:
    """``stop_requested``: ids of containers stopped through the API (not crashed)."""
    items = list(containers)
    if not items:
        return AppStatus.MISSING
    failed = [c for c in items if _is_failed(c, stop_requested)]
    running = [c for c in items if c.state is ContainerState.RUNNING and c not in failed]
    # Created or paused: expected to run but not running. Containers that
    # exited cleanly are one-shot jobs (migrations, init) and are ignored.
    pending = [c for c in items if c.state in (ContainerState.CREATED, ContainerState.PAUSED)]
    if not running:
        return AppStatus.ERROR if failed else AppStatus.STOPPED
    if failed or pending:
        return AppStatus.DEGRADED
    if any(c.health is Health.STARTING for c in running):
        return AppStatus.STARTING
    return AppStatus.HEALTHY
