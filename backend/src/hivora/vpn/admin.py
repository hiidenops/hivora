"""The admin VPN (M12-5): the panel reached over WireGuard in the ``vpn`` access modes.

On each start in ``vpn`` or ``vpn+lan`` (``Settings.access``), the server brings what it
needs into line, creating only what is missing: the Administration zone's apps share a
network, a WireGuard app runs in that zone (a deploy job), it has an ``admin`` client that
reaches that zone only, and ``<data>/admin.conf`` (0600) holds that client's
configuration. The ``vpn.admin`` setting remembers what was made (app, client, date): the
admin VPN is initialized once, never twice. In those modes the app cannot be removed nor
the client deleted or disabled: going back to ``--access lan`` lifts that.

``python -m hivora rescue-admin`` asks (``vpn.admin_rescue``) for new keys at the next
start: a lost or leaked ``admin.conf`` stops working. ``python -m hivora admin-vpn`` shows
the file and its QR code in a terminal.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.core import DeployRequest, get_app
from hivora.apps.service import AppService
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.core.errors import ConflictError, NotFoundError
from hivora.core.events import EventBus
from hivora.db.models import Setting
from hivora.jobs import JobQueue, JobStatus
from hivora.vpn.models import VpnPeer
from hivora.vpn.service import VpnTools
from hivora.zones.models import NetworkMode
from hivora.zones.service import get_zone

logger = logging.getLogger(__name__)

VPN_MODES = ("vpn", "vpn+lan")
ADMIN_ZONE = "administration"
# Fixed addressing (D5), shared with the installer (M12-5b): the Administration zone's
# network, the part Docker hands out to containers, the panel's own address in it.
ADMIN_ZONE_SUBNET = "10.254.254.0/24"
ADMIN_ZONE_RANGE = "10.254.254.0/25"
PANEL_IP = "10.254.254.254"
ADMIN_VPN_SUBNET = "10.254.253.0/24"  # not 10.8.0.0/24: a user's own VPN keeps it
APP_NAME = "Admin VPN"
CLIENT = "admin"
CLIENT_ACCESS = {"internet": False, "lan": False, "zones": [ADMIN_ZONE]}
STATE = "vpn.admin"  # {"app_id", "client_id", "initialized_at"}
RESCUE = "vpn.admin_rescue"
FINISHED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED)


class AdminVpnProtectedError(ConflictError):
    code = "admin_vpn_protected"


async def read_state(session: AsyncSession) -> dict[str, Any] | None:
    row = await session.get(Setting, STATE)
    return dict(row.value) if row else None


async def request_rescue(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        await session.merge(Setting(key=RESCUE, value=True))


def terminal_qr(text: str) -> str:
    """The QR code of ``text`` drawn with block characters (a terminal, a phone's camera)."""
    import io

    import segno  # lazy: only for this command

    out = io.StringIO()
    segno.make(text, error="l").terminal(out=out, compact=True, border=2)
    return out.getvalue()


class AdminVpn:
    def __init__(
        self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession], apps: AppService,
        vpn: VpnTools, jobs: JobQueue, public_address: Callable[[], str | None], clock: Clock,
    ) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.apps = apps
        self.vpn = vpn
        self.jobs = jobs
        self.public_address = public_address
        self.clock = clock
        self.poll_s = 1.0  # waiting for the deploy job
        self.wait_s = 900.0  # an image pull on a slow line

    @property
    def active(self) -> bool:
        return self.settings.access in VPN_MODES

    @property
    def conf_path(self) -> Path:
        return self.settings.data_dir / "admin.conf"

    async def protected(self) -> dict[str, Any] | None:
        """What is protected now: the state in the vpn modes, else nothing."""
        if not self.active:
            return None
        async with self.sessions() as session:
            return await read_state(session)

    async def check_app_removal(self, app_id: int) -> None:
        state = await self.protected()
        if state and state.get("app_id") == app_id:
            raise AdminVpnProtectedError(
                "the admin VPN cannot be removed (the panel is reached through it)"
            )

    async def check_client_change(self, app_id: int, cid: int, *, delete: bool = False,
                                  changes: dict[str, Any] | None = None) -> None:  # fmt: skip
        """The admin client cannot be deleted, disabled, nor given an expiry."""
        changes = changes or {}
        state = await self.protected()
        if not state or (state.get("app_id"), state.get("client_id")) != (app_id, cid):
            return
        if delete or changes.get("enabled") is False or changes.get("expires_at") is not None:
            raise AdminVpnProtectedError("the admin VPN client cannot be deleted or disabled")

    async def ensure(self) -> None:
        """Bring the admin VPN into line (on start; never fails the server)."""
        if not self.active:
            return
        try:
            await self._ensure()
        except Exception:
            logger.exception("admin VPN not set up")

    async def _ensure(self) -> None:
        async with self.sessions() as session, session.begin():
            zone = await get_zone(session, ADMIN_ZONE)
            changed = zone.network_mode is not NetworkMode.SHARED
            zone.network_mode = NetworkMode.SHARED  # its apps share hivora-zone-administration
            zone_id = zone.id
            state = await read_state(session) or {}
            rescue = await session.get(Setting, RESCUE) is not None
        if changed:
            await self.apps.revisions.redeploy_zone(zone_id)
            logger.info("Administration zone: apps now share a network")
        app_id = await self._app(state)
        if app_id is None:
            return
        async with self.sessions() as session:  # a new app saved {"app_id"} only (ids reused)
            state = await read_state(session) or {}
        client_id = await self._client(app_id, state.get("client_id"), rescue=rescue)
        if client_id != state.get("client_id") or not state.get("initialized_at"):
            state = {"app_id": app_id, "client_id": client_id,
                     "initialized_at": self.clock.now().isoformat()}  # fmt: skip
            await self._save(state)
            logger.info("admin VPN initialized", extra={"app_id": app_id})
        await self.write_conf()
        if rescue:
            async with self.sessions() as session, session.begin():
                if row := await session.get(Setting, RESCUE):
                    await session.delete(row)

    async def _save(self, state: dict[str, Any]) -> None:
        async with self.sessions() as session, session.begin():
            await session.merge(Setting(key=STATE, value=state))

    async def _app(self, state: dict[str, Any]) -> int | None:
        """The admin VPN app: the one remembered, or a new one (deploy job, awaited)."""
        if app_id := state.get("app_id"):
            try:
                async with self.sessions() as session:
                    await get_app(session, app_id)
                return int(app_id)
            except NotFoundError:
                logger.warning("admin VPN app gone: deploying it again")
        host = self.settings.admin_vpn_host or self.public_address() or self.settings.host_lan_ip
        if not host:
            logger.error("admin VPN not deployed: no address for clients (HIVORA_ADMIN_VPN_HOST)")
            return None
        inputs = {"host": host, "vpn_port": self.settings.admin_vpn_port,
                  "vpn_subnet": ADMIN_VPN_SUBNET, "vpn_zones": ADMIN_ZONE}  # fmt: skip
        app, job = await self.apps.deployer.deploy(
            DeployRequest(template="wireguard", name=APP_NAME, inputs=inputs, zone=ADMIN_ZONE)
        )
        await self._save({"app_id": app.id})  # deployed once, even if the wait below fails
        status = await self._wait(job.id)
        if status is not JobStatus.SUCCEEDED:  # its config is written anyway: on start it is up
            logger.error("admin VPN deploy did not succeed", extra={"status": str(status)})
        return app.id

    async def _wait(self, job_id: int) -> JobStatus | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_s
        while loop.time() < deadline:
            status = (await self.jobs.get(job_id)).status
            if status in FINISHED:
                return status
            await asyncio.sleep(self.poll_s)
        return None

    async def _client(self, app_id: int, client_id: int | None, *, rescue: bool) -> int:
        async with self.sessions() as session:
            peer = await session.get(VpnPeer, client_id) if client_id else None
        if peer is None or peer.app_id != app_id or peer.server:
            return await self.vpn.create(app_id, CLIENT, None, None, access=CLIENT_ACCESS,
                                         routing="access")  # fmt: skip
        if rescue:  # new keys: the old admin.conf stops working; back on, never expiring
            await self.vpn.renew(app_id, peer.id)
            await self.vpn.update(app_id, peer.id, enabled=True, expires_at=None)
            logger.warning("admin VPN client given new keys (rescue-admin)")
        return peer.id

    async def write_conf(self) -> None:
        """``admin.conf`` as the database has it (0600, replaced only when it differs)."""
        async with self.sessions() as session:
            state = await read_state(session)
        if not state or not state.get("client_id"):
            return
        text = await self.vpn.configuration(state["app_id"], state["client_id"], quiet=True)
        path = self.conf_path
        try:
            if path.read_text() == text:
                return
        except OSError:
            pass
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # a private key inside
        with os.fdopen(fd, "w") as f:
            f.write(text)
        tmp.replace(path)


async def follow_admin_client(admin: AdminVpn, bus: EventBus) -> None:
    """New keys or settings for a VPN client: ``admin.conf`` follows."""
    async with bus.subscribe("vpn.*") as sub:
        async for event in sub:
            if admin.active and event.topic in ("vpn.client_renewed", "vpn.client_updated"):
                try:
                    await admin.write_conf()
                except Exception:
                    logger.exception("admin.conf not rewritten")
