"""The server's public address: an admin-set IP/domain, else auto-detected.

Detection asks a single well-known service from the backend (never the
browser), validates the answer as an IP and refreshes it every 6 hours.
"""

import asyncio
import ipaddress
import logging
import re
from contextlib import suppress

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora import __version__
from hivora.core.errors import ValidationError
from hivora.db.models import Setting

logger = logging.getLogger(__name__)

DETECT_URL = "https://api.ipify.org"
REFRESH_S = 6 * 3600
SETTING_KEY = "public_address"
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def validate_address(value: str) -> str:
    """An IP or a domain name, nothing else (it ends up in addresses shown to users)."""
    value = value.strip().lower()
    with suppress(ValueError):
        return str(ipaddress.ip_address(value))
    if _HOSTNAME.match(value):
        return value
    raise ValidationError("not an IP address or domain name", field="address")


class PublicAddress:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], fallback: str | None,
                 url: str = DETECT_URL) -> None:  # fmt: skip
        self.sessions = sessions
        self.fallback = fallback  # HIVORA_HOST_PUBLIC_IP, if set
        self.url = url
        self.manual: str | None = None
        self.detected: str | None = None
        self._task: asyncio.Task[None] | None = None

    def current(self) -> str | None:
        return self.manual or self.fallback or self.detected

    async def start(self) -> None:
        async with self.sessions() as session:
            row = await session.get(Setting, SETTING_KEY)
        self.manual = row.value if row and isinstance(row.value, str) else None
        if self.fallback is None:  # an address imposed by the environment needs no lookup
            self._task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def set_manual(self, value: str | None) -> None:
        value = validate_address(value) if value else None
        async with self.sessions() as session, session.begin():
            row = await session.get(Setting, SETTING_KEY)
            if value is None and row is not None:
                await session.delete(row)
            elif value is not None:
                await session.merge(Setting(key=SETTING_KEY, value=value))
        self.manual = value

    async def detect(self) -> str | None:
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": f"Hivora/{__version__}"},
                ) as http,
                http.get(self.url) as r,
            ):
                r.raise_for_status()
                text = (await r.text()).strip()
            self.detected = str(ipaddress.ip_address(text))
        except Exception as exc:
            logger.warning("public IP detection failed", extra={"error": str(exc)})
        return self.detected

    async def _refresh_loop(self) -> None:
        while True:
            await self.detect()
            await asyncio.sleep(REFRESH_S)
