"""TeamSpeak 3 servers deployed from the ``teamspeak`` template: their ServerQuery, from the panel.

Short actions on the running server (ban, kick, password...), like a game's player lists:
direct, each one on the bus (audited). Neither the server password nor an admin key ever
travels on the bus or in a log: the key is shown once, to whoever asked for it.
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.apps.service import AppService
from hivora.core.errors import ConflictError, ValidationError
from hivora.core.events import EventBus
from hivora.docker_gateway import DockerGateway
from hivora.teamspeak import query as q

TEMPLATE = "teamspeak"
PASSWORD_KEY = "query_password"  # noqa: S105 - the template's secret: serveradmin's ServerQuery password
MAX_SLOTS = 32  # the free licence
LOG_LINES = 100  # logview's maximum
# A client's lines in the virtual server's log (virtualserver_log_client=1).
_CONNECTED = re.compile(r"^client connected '(?P<name>.*)'\(id:\d+\) from (?P<ip>.+):\d+$")
_DISCONNECTED = re.compile(
    r"^client disconnected '(?P<name>.*)'\(id:\d+\) reason '(?P<reason>.*)'$"
)
_BANNED = re.compile(r"^ban added reason='(?P<reason>.*)' ip='(?P<ip>[^']*)'")


class NotTeamSpeakError(ConflictError):
    code = "not_teamspeak"


class ServerStoppedError(ConflictError):
    code = "server_not_running"


@dataclass(frozen=True, slots=True)
class Client:
    clid: int
    name: str
    ip: str | None
    country: str | None
    connected_at: int | None  # epoch seconds
    idle_s: int


@dataclass(frozen=True, slots=True)
class Ban:
    id: int
    ip: str | None
    name: str | None
    uid: str | None
    reason: str
    created: int  # epoch seconds
    duration_s: int  # 0: forever
    by: str


@dataclass(frozen=True, slots=True)
class LogEntry:
    ts: str
    event: str  # connected, disconnected, banned
    name: str | None
    ip: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class AdminKey:
    created: int
    description: str


def valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValidationError("invalid IP address", field="ip") from exc


def _text(value: str, field: str, limit: int) -> str:
    if len(value) > limit:
        raise ValidationError(f"{field} too long (max {limit})", field=field)
    return value


def parse_log(lines: list[str]) -> list[LogEntry]:
    """logview lines (``date|LEVEL|Channel|sid|message``) -> the clients' connections and bans."""
    out = []
    for line in lines:
        parts = [p.strip() for p in line.split("|", 4)]
        if len(parts) < 5:
            continue
        ts, msg = parts[0], parts[4]
        if m := _CONNECTED.match(msg):
            out.append(LogEntry(ts, "connected", m["name"], m["ip"], None))
        elif m := _DISCONNECTED.match(msg):
            out.append(LogEntry(ts, "disconnected", m["name"], None, m["reason"]))
        elif m := _BANNED.match(msg):
            out.append(LogEntry(ts, "banned", None, m["ip"] or None, m["reason"]))
    return out


def _int(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(row.get(key) or default)
    except ValueError:
        return default


class TeamSpeak:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        apps: AppService,
        gateway: DockerGateway,
        bus: EventBus,
    ) -> None:
        self.sessions = sessions
        self.apps = apps
        self.gateway = gateway
        self.bus = bus

    async def slug(self, app_id: int) -> str:
        async with self.sessions() as session:
            app, entry, _ = await self.apps.main_container(session, app_id)
        if entry is None or entry.template.metadata.slug != TEMPLATE:
            raise NotTeamSpeakError("not a TeamSpeak server", slug=app.slug)
        return app.slug

    async def _run(self, app_id: int, *commands: str) -> list[q.Answer]:
        async with self.sessions() as session:
            app, entry, container = await self.apps.main_container(session, app_id)
            if entry is None or entry.template.metadata.slug != TEMPLATE:
                raise NotTeamSpeakError("not a TeamSpeak server", slug=app.slug)
            if container is None:
                raise ServerStoppedError("the server must be running", slug=app.slug)
            password = (await self.apps.decrypt_secrets(session, app_id)).get(PASSWORD_KEY, "")
        return await q.run(self.gateway, container.id, password, list(commands))

    async def _one(self, app_id: int, *commands: str) -> list[dict[str, str]]:
        return (await self._run(app_id, *commands))[0].rows

    # --- reading --------------------------------------------------------------------
    async def info(self, app_id: int) -> dict[str, Any]:
        s = (await self._one(app_id, "serverinfo"))[0]
        return {
            "name": s.get("virtualserver_name", ""),
            "welcome": s.get("virtualserver_welcomemessage", ""),
            "max_clients": _int(s, "virtualserver_maxclients"),
            "online": _int(s, "virtualserver_clientsonline")
            - _int(s, "virtualserver_queryclientsonline"),
            "version": s.get("virtualserver_version", ""),
            "uptime_s": _int(s, "virtualserver_uptime"),
            "password": s.get("virtualserver_flag_password") == "1",
            "log_clients": s.get("virtualserver_log_client") == "1",
        }

    async def clients(self, app_id: int) -> list[Client]:
        rows = await self._one(app_id, q.command("clientlist", "-ip", "-times", "-country"))
        return [
            Client(
                clid=_int(r, "clid"),
                name=r.get("client_nickname", ""),
                ip=r.get("connection_client_ip") or None,
                country=r.get("client_country") or None,
                connected_at=_int(r, "client_lastconnected") or None,
                idle_s=_int(r, "client_idle_time") // 1000,
            )
            for r in rows
            if r.get("client_type") == "0"  # 1: ServerQuery (Hivora itself)
        ]

    async def bans(self, app_id: int) -> list[Ban]:
        rows = await self._one(app_id, "banlist")
        return [
            Ban(
                id=_int(r, "banid"),
                ip=r.get("ip") or None,
                name=r.get("lastnickname") or r.get("name") or None,
                uid=r.get("uid") or None,
                reason=r.get("reason", ""),
                created=_int(r, "created"),
                duration_s=_int(r, "duration"),
                by=r.get("invokername", ""),
            )
            for r in rows
            if r.get("banid")
        ]

    async def history(self, app_id: int) -> list[LogEntry]:
        rows = await self._one(app_id, q.command("logview", lines=LOG_LINES, reverse=1))
        return parse_log([r["l"] for r in rows if "l" in r])

    async def admin_keys(self, app_id: int) -> list[AdminKey]:
        """The admin keys not used yet (their value is never shown again)."""
        rows = await self._one(app_id, "privilegekeylist")
        return [
            AdminKey(_int(r, "token_created"), r.get("token_description", ""))
            for r in rows
            if r.get("token")
        ]

    # --- changes (each one audited) -------------------------------------------------
    async def kick(self, app_id: int, clid: int, reason: str) -> None:
        slug = await self.slug(app_id)
        await self._run(
            app_id,
            q.command(
                "clientkick", clid=clid, reasonid=5, reasonmsg=_text(reason, "reason", 80) or None
            ),
        )
        self.bus.publish("teamspeak.kicked", app=slug, clid=clid)

    async def ban(
        self, app_id: int, *, ip: str | None, clid: int | None, minutes: int, reason: str
    ) -> None:
        """A connected client (its address and identity), or an address; 0 minutes: forever."""
        if not 0 <= minutes <= 525_600:
            raise ValidationError("duration out of range", field="minutes")
        slug = await self.slug(app_id)
        common = {"time": minutes * 60, "banreason": _text(reason, "reason", 80) or None}
        if clid is not None:
            await self._run(app_id, q.command("banclient", clid=clid, **common))
            self.bus.publish("teamspeak.banned", app=slug, clid=clid, minutes=minutes)
        elif ip:
            address = valid_ip(ip)
            await self._run(app_id, q.command("banadd", ip=address, **common))
            self.bus.publish("teamspeak.banned", app=slug, target=address, minutes=minutes)
        else:
            raise ValidationError("an address or a client", field="ip")

    async def unban(self, app_id: int, ban_id: int) -> None:
        slug = await self.slug(app_id)
        await self._run(app_id, q.command("bandel", banid=ban_id))
        self.bus.publish("teamspeak.unbanned", app=slug, ban=ban_id)

    async def message(self, app_id: int, text: str) -> None:
        if not text.strip():
            raise ValidationError("empty message", field="text")
        slug = await self.slug(app_id)
        await self._run(app_id, q.command("gm", msg=_text(text, "text", 1024)))
        self.bus.publish("teamspeak.message_sent", app=slug)

    async def set_password(self, app_id: int, password: str | None) -> None:
        """None or empty: no password. The value is never published."""
        slug = await self.slug(app_id)
        await self._run(
            app_id,
            q.command("serveredit", virtualserver_password=_text(password or "", "password", 64)),
        )
        self.bus.publish("teamspeak.password_changed", app=slug, set=bool(password))

    async def edit(
        self, app_id: int, *, name: str, welcome: str, max_clients: int, log_clients: bool
    ) -> None:
        if not name.strip():
            raise ValidationError("empty name", field="name")
        if not 1 <= max_clients <= MAX_SLOTS:
            raise ValidationError(f"between 1 and {MAX_SLOTS} slots", field="max_clients")
        slug = await self.slug(app_id)
        await self._run(
            app_id,
            q.command(
                "serveredit",
                virtualserver_name=_text(name, "name", 80),
                virtualserver_welcomemessage=_text(welcome, "welcome", 1024),
                virtualserver_maxclients=max_clients,
                virtualserver_log_client=int(log_clients),
            ),
        )
        self.bus.publish(
            "teamspeak.settings_changed", app=slug, max_clients=max_clients, log_clients=log_clients
        )

    async def renew_admin_key(self, app_id: int) -> str:
        """Delete the admin keys not used yet, create one: returned once, never stored."""
        slug = await self.slug(app_id)
        groups, keys = await self._run(app_id, "servergrouplist", "privilegekeylist")
        admin = next(
            (g for g in groups.rows if g.get("type") == "1" and g.get("name") == "Server Admin"),
            None,
        )
        if admin is None:
            raise ConflictError("this server has no « Server Admin » group")
        stale = [
            q.command("privilegekeydelete", token=k["token"]) for k in keys.rows if k.get("token")
        ]
        *_, created = await self._run(
            app_id,
            *stale,
            q.command(
                "privilegekeyadd",
                tokentype=0,
                tokenid1=admin["sgid"],
                tokenid2=0,
                tokendescription="Hivora",
            ),
        )
        self.bus.publish("teamspeak.admin_key_renewed", app=slug, replaced=len(stale))
        return created.rows[0]["token"]
