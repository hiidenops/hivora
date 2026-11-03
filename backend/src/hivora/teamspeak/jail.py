"""A fail2ban jail per TeamSpeak server (exception validated on 03/11/2026).

The intent lives in SQLite (setting ``teamspeak_jails``: slug -> maxretry, findtime,
bantime); the host gets a fixed filter and a jail file generated from it, written through
the host agent as an argument of a fixed script (never shell code), in their own files:
saving the host's other jails (hostfw.service.save_jails) never touches them. The jail
reads the server's log in its data volume and bans in DOCKER-USER, the chain the published
ports go through (fail2ban's default INPUT does not see them). A reload that fails puts the
previous file back.
"""

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.errors import ConflictError, ValidationError
from hivora.core.events import EventBus
from hivora.db.models import Setting
from hivora.hostfw.service import DURATION, HostFirewall, parse_jail

logger = logging.getLogger(__name__)

SETTING = "teamspeak_jails"
FILTER_FILE = "/etc/fail2ban/filter.d/hivora-teamspeak.conf"
JAIL_FILE = "/etc/fail2ban/jail.d/hivora-teamspeak.local"
WRITE = 'printf "%s" "$1" > '
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# The lines seen on a real 3.13 server (the instance log, logappend=1: one file per server).
# ponytail: the ServerQuery's failed logins only, the lines seen on a real 3.13 server (its
# instance log); a client's wrong server password to add once its log line is known.
FAILREGEX = (
    r"^\|\w+\s*\|Query\s*\|\s*\|query from \d+ <ADDR>:\d+ "
    r'attempted to login with account ".*" and failed!$'
)
FILTER = f"""# Written by Hivora: failed logins on a TeamSpeak 3 server, from its own log.
[Definition]
failregex = {FAILREGEX}
ignoreregex =
datepattern = {{^LN-BEG}}%%Y-%%m-%%d %%H:%%M:%%S(?:\\.%%f)?
"""
DEFAULTS = {"maxretry": 5, "findtime": "10m", "bantime": "1h"}


class LogMissingError(ConflictError):
    code = "teamspeak_log_missing"


def jail_name(slug: str) -> str:
    return f"hivora-teamspeak-{slug}"


def log_paths(volumes_root: Path, slug: str) -> list[Path]:
    logs = volumes_root / slug / "data" / "logs"
    return [logs / "ts3server_0.log", logs / "ts3server_1.log"]


def check(values: dict[str, Any]) -> dict[str, Any]:
    out = {**DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULTS and v is not None}}
    if not 1 <= int(out["maxretry"]) <= 1000:
        raise ValidationError("maxretry out of range", field="maxretry")
    for key in ("findtime", "bantime"):
        if not DURATION.match(str(out[key])):
            raise ValidationError(f"invalid {key}", field=key)
    return {
        "maxretry": int(out["maxretry"]),
        "findtime": str(out["findtime"]),
        "bantime": str(out["bantime"]),
    }


def jail_config(jails: dict[str, dict[str, Any]], volumes_root: Path) -> str:
    lines = ["# Written by Hivora: one jail per TeamSpeak server (Hivora's app page).", ""]
    for slug, raw in sorted(jails.items()):
        if not SLUG.match(slug):
            raise ValidationError("invalid app name", field="app")
        v = check(raw)
        paths = "\n          ".join(str(p) for p in log_paths(volumes_root, slug))
        lines += [
            f"[{jail_name(slug)}]",
            "enabled = true",
            "filter = hivora-teamspeak",
            f"logpath = {paths}",
            "backend = polling",
            f"maxretry = {v['maxretry']}",
            f"findtime = {v['findtime']}",
            f"bantime = {v['bantime']}",
            f"action = iptables-allports[name=hv-ts-{slug[:16]}, chain=DOCKER-USER, protocol=all]",
            "",
        ]
    return "\n".join(lines)


class TeamSpeakJails:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        fw: HostFirewall,
        bus: EventBus,
        volumes_root: Path,
    ) -> None:
        self.sessions = sessions
        self.fw = fw
        self.bus = bus
        self.volumes_root = volumes_root

    async def wanted(self) -> dict[str, dict[str, Any]]:
        async with self.sessions() as session:
            row = await session.get(Setting, SETTING)
        return dict(row.value) if row and isinstance(row.value, dict) else {}

    async def _save(self, jails: dict[str, dict[str, Any]]) -> None:
        async with self.sessions() as session, session.begin():
            row = await session.get(Setting, SETTING)
            if row is None:
                session.add(Setting(key=SETTING, value=jails))
            else:
                row.value = jails

    async def state(self, slug: str) -> dict[str, Any]:
        """The jail's settings (None: off), and while it runs, who it bans."""
        agent = await self.fw.agent_enabled()
        values = (await self.wanted()).get(slug)
        banned: list[str] = []
        failed = 0
        if agent and values is not None:
            code, text = await self.fw._run(
                ["fail2ban-client", "status", jail_name(slug)], check=False
            )
            if code == 0:
                jail = parse_jail(jail_name(slug), text)
                banned, failed = jail.banned, jail.failed
        return {
            "agent": agent,
            "enabled": values is not None,
            "settings": check(values or {}),
            "banned": banned,
            "failed": failed,
            "jail": jail_name(slug),
        }

    async def set(self, slug: str, values: dict[str, Any] | None) -> None:
        """Turn the jail on with ``values`` (None: off), then reload fail2ban."""
        jails = await self.wanted()
        if values is None:
            jails.pop(slug, None)
        else:
            if not log_paths(self.volumes_root, slug)[0].exists():
                raise LogMissingError("start the server once first: its log does not exist yet")
            jails[slug] = check(values)
        await self._apply(jails)
        await self._save(jails)
        self.bus.publish(
            "hostfw.teamspeak_jail",
            app=slug,
            target=jail_name(slug),
            enabled=values is not None,
            **(jails.get(slug) or {}),
        )

    async def forget(self, slug: str) -> None:
        """The app is gone: its jail too (its log may be gone, fail2ban would refuse it)."""
        jails = await self.wanted()
        if slug in jails and await self.fw.agent_enabled():
            jails.pop(slug)
            await self._apply(jails)
            await self._save(jails)

    async def _apply(self, jails: dict[str, dict[str, Any]]) -> None:
        content = jail_config(jails, self.volumes_root)
        _, before = await self.fw._run(["sh", "-c", f"cat {JAIL_FILE} 2>/dev/null || true"])
        await self.fw._run(["sh", "-c", WRITE + FILTER_FILE, "hivora", FILTER])
        await self.fw._run(["sh", "-c", WRITE + JAIL_FILE, "hivora", content])
        code, out = await self.fw._run(["fail2ban-client", "reload"], check=False)
        if code != 0:  # put the previous file back: the host's other jails keep running
            await self.fw._run(["sh", "-c", WRITE + JAIL_FILE, "hivora", before])
            await self.fw._run(["fail2ban-client", "reload"], check=False)
            raise ConflictError("fail2ban refused the jail", output=out.strip()[-300:])

    async def matches(self, slug: str) -> int | None:
        """How many lines of the server's log the filter recognises (fail2ban-regex)."""
        if not log_paths(self.volumes_root, slug)[0].exists():
            return None
        code, out = await self.fw._run(
            ["fail2ban-regex", str(log_paths(self.volumes_root, slug)[0]), FILTER_FILE], check=False
        )
        m = re.search(r"Lines:.*?(\d+) matched", out)
        return int(m.group(1)) if code == 0 and m else None

    async def unban(self, slug: str, ip: str) -> str:
        return await self.fw.jail_ip(jail_name(slug), ip, ban=False)


async def forget_removed(jails: TeamSpeakJails) -> None:
    """Runs with Hivora: a removed app's jail goes too."""
    async with jails.bus.subscribe("app.removed") as sub:
        async for event in sub:
            try:
                await jails.forget(str(event.payload.get("app", "")))
            except Exception:
                logger.exception(
                    "TeamSpeak jail not removed", extra={"app": event.payload.get("app")}
                )
