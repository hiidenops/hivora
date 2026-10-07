"""Whether a port is free for a host's site, and which one to suggest when it is not.

The planner sees the other apps' ports; this adds what it cannot see as such: another site
of the same nginx (a database rule) and the ports of the nginx's advanced settings. A
suggestion is a port really free: not used by another app, nor by this nginx (its web
port, its sites' ports as they were before the change, its advanced settings' ports).
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hivora.apps.core import PortConflictError, latest_revision
from hivora.apps.ports import used_ports
from hivora.sites import core, nginx
from hivora.sites.models import Site
from hivora.state import StateStore
from hivora.templates.overrides import Overrides


class PortCheck:
    def __init__(self, state: StateStore) -> None:
        self.state = state

    async def free(self, session: AsyncSession, app_id: int, port: int) -> None:
        """Refused (409 port_conflict, with a suggestion) if another site of this nginx or
        its advanced settings use the port."""
        if other := await session.scalar(select(Site.slug).where(Site.app_id == app_id,
                                                                 Site.port == port)):  # fmt: skip
            used_by = f"site {other}"
        elif port in await self._own_ports(session, app_id):
            used_by = "advanced settings"
        else:
            return
        conflict = {"port": port, "protocol": "tcp", "used_by": used_by, "suggestion": None}
        raise await self.conflict(session, app_id, [conflict], [])

    async def conflict(
        self, session: AsyncSession, app_id: int, conflicts: list[dict[str, Any]],
        also: Iterable[int],
    ) -> PortConflictError:  # fmt: skip
        """The conflicts, each with a port really free as its suggestion. ``also``: the
        sites' ports before the change (the moved site's current port included)."""
        app = await core.get_site(session, app_id)
        used = await used_ports(session, self.state, exclude_app=app.slug)
        taken = {p for p, protocol in used if protocol == "tcp"} | set(also)
        taken |= set(await core.added_ports(session, app_id))
        taken |= await self._own_ports(session, app_id)
        if (web := (await core.current_inputs(session, app_id)).get("web_port")) is not None:
            taken.add(int(web))
        taken.add(nginx.MAIN_PORT)  # the main site's port inside the container
        for c in conflicts:
            c["suggestion"] = next((p for p in range(c["port"] + 1, 65536) if p not in taken),
                                   None)  # fmt: skip
        return PortConflictError("host ports already in use", conflicts=conflicts)

    async def _own_ports(self, session: AsyncSession, app_id: int) -> set[int]:
        """The ports of this nginx's advanced settings (inside and outside)."""
        latest = await latest_revision(session, app_id)
        own = Overrides.model_validate(latest.overrides or {}).of(core.SERVICE) if latest else None
        return {q for p in own.ports for q in (p.container, p.host) if q} if own else set()
