"""The host's own firewall (UFW) and fail2ban, through the optional host agent.

Hivora never gets a shell on the host: an admin turns the agent on, then only
the fixed command lines below run there (``nsenter`` into the host's
namespaces), with arguments validated here, never interpolated into a shell.
UFW does not filter ports published by Docker (Docker bypasses it); the UI
says so rather than presenting UFW as a protection for the apps.
"""

import asyncio
import ipaddress
import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora.core.errors import ConflictError, ValidationError
from hivora.core.events import EventBus
from hivora.db.models import Setting
from hivora.docker_gateway import DockerGateway
from hivora.state import StateStore

AGENT = "hivora-host-agent"
AGENT_IMAGE = "alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8"
SETTING = "host_agent"
HOST = ["nsenter", "-t", "1", "-m", "-u", "-n", "-i", "--"]
TIMEOUT_S = 30
JAIL = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
CACHE_S = 20
LABELS = {"io.hivora.self": "true", "io.hivora.agent": "host"}
ACTIONS = ("allow", "deny", "reject", "limit")
RULE = re.compile(r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)(?: (IN|OUT|FWD))?\s+(.+)$")


class AgentOffError(ConflictError):
    code = "host_agent_off"


class HostCommandError(ConflictError):
    code = "host_command_failed"


@dataclass
class UfwRule:
    number: int
    to: str
    action: str
    source: str
    spec: tuple[str, ...] = ()  # inactive UFW: the rule itself, deleted by its text


@dataclass
class Jail:
    name: str
    banned: list[str]
    total_banned: int
    failed: int


@dataclass
class FirewallState:
    agent: bool
    ufw_installed: bool = False
    ufw_active: bool = False
    ufw_defaults: str = ""
    ufw_rules: list[UfwRule] = field(default_factory=list)
    fail2ban_installed: bool = False
    fail2ban_running: bool = False
    jails: list[Jail] = field(default_factory=list)


def parse_ufw_numbered(text: str) -> list[UfwRule]:
    """``ufw status numbered``: "[ 1] 22/tcp   ALLOW IN    Anywhere"."""
    rules = []
    for line in text.splitlines():
        m = RULE.match(line.strip())
        if m:
            action = m.group(3) + (f" {m.group(4)}" if m.group(4) else "")
            rules.append(UfwRule(int(m.group(1)), m.group(2).strip(), action, m.group(5).strip()))
    return rules


SPEC_TOKEN = re.compile(r"^[\w./:,-]+$")


def parse_ufw_added(text: str) -> list[UfwRule]:
    """``ufw show added`` (rules kept while UFW is off): "ufw allow from 10.0.0.0/8 to any
    port 80 proto tcp". Numbered here for display only: deleted by their text."""
    rules: list[UfwRule] = []
    for line in text.splitlines():
        spec = tuple(line.split()[1:])
        if not line.startswith("ufw ") or not spec or spec[0] not in ACTIONS:
            continue
        if not all(SPEC_TOKEN.match(t) for t in spec):
            continue
        after = dict(itertools.pairwise(spec))  # "port" -> "80", "from" -> ...
        to = after.get("port") or next((t for t in spec[1:] if t not in ("in", "out")), "")
        if (proto := after.get("proto")) and "/" not in to:
            to += f"/{proto}"
        source = after.get("from", "any")
        rules.append(UfwRule(len(rules) + 1, to, spec[0].upper(),
                             "Anywhere" if source == "any" else source, spec))  # fmt: skip
    return rules


def parse_jail(name: str, text: str) -> Jail:
    def number(label: str) -> int:
        m = re.search(rf"{label}:\s*(\d+)", text)
        return int(m.group(1)) if m else 0

    m = re.search(r"Banned IP list:\s*(.*)", text)
    banned = m.group(1).split() if m else []
    return Jail(name, banned, number("Total banned"), number("Currently failed"))


def valid_source(value: str) -> str:
    if value in ("", "any"):
        return "any"
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError:
        raise ValidationError("not an IP address or network", field="source") from None


def valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ValidationError("not an IP address", field="ip") from None


class HostFirewall:
    def __init__(
        self, *, sessions: async_sessionmaker[AsyncSession], gateway: DockerGateway,
        bus: EventBus, store: StateStore,
    ) -> None:  # fmt: skip
        self.sessions = sessions
        self.gateway = gateway
        self.bus = bus
        self.store = store  # the published ports, next to what listens on the host
        self._cache: tuple[float, FirewallState] | None = None
        self.seen: dict[str, float] = {}  # connected address -> first seen (hostfw.connections)

    # --- the agent ---------------------------------------------------------------
    async def agent_enabled(self) -> bool:
        async with self.sessions() as session:
            row = await session.get(Setting, SETTING)
        return bool(row and row.value is True)

    async def set_agent(self, on: bool) -> None:
        if on:
            await self.gateway.ensure_agent(AGENT, AGENT_IMAGE, LABELS)
        else:
            await self.gateway.remove_agent(AGENT)
        async with self.sessions() as session, session.begin():
            await session.merge(Setting(key=SETTING, value=on))
        self._cache = None
        self.bus.publish("hostfw.agent_enabled" if on else "hostfw.agent_disabled")

    async def _run(self, argv: list[str], *, check: bool = True,
                   limit_s: float = TIMEOUT_S) -> tuple[int, str]:  # fmt: skip
        if not await self.agent_enabled():
            raise AgentOffError("the host agent is off (Settings → host firewall)")
        agent = await self.gateway.ensure_agent(AGENT, AGENT_IMAGE, LABELS)
        async with asyncio.timeout(limit_s):
            code, out = await self.gateway.exec_run(agent, [*HOST, *argv])
        if check and code != 0:
            raise HostCommandError(f"{argv[0]} failed", output=out[-500:])
        return code, out

    # --- reading -----------------------------------------------------------------
    async def state(self, *, fresh: bool = False) -> FirewallState:
        now = asyncio.get_running_loop().time()
        if not fresh and self._cache and now - self._cache[0] < CACHE_S:
            return self._cache[1]
        if not await self.agent_enabled():
            return FirewallState(agent=False)
        st = FirewallState(agent=True)
        code, out = await self._run(["ufw", "status", "verbose"], check=False)
        st.ufw_installed = code != 127 and "not found" not in out.lower()
        if st.ufw_installed:
            st.ufw_active = "Status: active" in out
            m = re.search(r"Default:\s*(.+)", out)
            st.ufw_defaults = m.group(1).strip() if m else ""
            if st.ufw_active:
                _, numbered = await self._run(["ufw", "status", "numbered"], check=False)
                st.ufw_rules = parse_ufw_numbered(numbered)
            else:  # "status numbered" lists nothing while off: show the rules kept
                _, added = await self._run(["ufw", "show", "added"], check=False)
                st.ufw_rules = parse_ufw_added(added)
        code, out = await self._run(["fail2ban-client", "status"], check=False)
        st.fail2ban_installed = code != 127 and "not found" not in out.lower()
        st.fail2ban_running = code == 0 and "Jail list" in out
        if st.fail2ban_running:
            m = re.search(r"Jail list:\s*(.*)", out)
            names = [j.strip() for j in (m.group(1) if m else "").split(",") if j.strip()]
            for name in names:
                if JAIL.match(name):
                    _, text = await self._run(["fail2ban-client", "status", name], check=False)
                    st.jails.append(parse_jail(name, text))
        self._cache = (now, st)
        return st

    # --- changes (fixed command lines, validated arguments) ------------------------
    async def _change(self, event: str, argv: list[str], **details: Any) -> str:
        _, out = await self._run(argv)
        self._cache = None
        self.bus.publish(event, **details)
        return out.strip()[-500:]

    async def ufw_rule(self, action: Literal["allow", "deny", "limit"], port: int,
                       protocol: Literal["tcp", "udp", "any"], source: str) -> str:  # fmt: skip
        if not 1 <= port <= 65535:
            raise ValidationError("invalid port", field="port")
        src = valid_source(source)
        argv = ["ufw", action]
        if protocol != "any":
            argv += ["proto", protocol]
        argv += ["from", src, "to", "any", "port", str(port)]
        target = f"{action} {port}/{protocol}"
        return await self._change("hostfw.ufw_rule_added", argv, target=target, source=src)

    async def ufw_delete(self, number: int) -> str:
        st = await self.state(fresh=True)
        rule = next((r for r in st.ufw_rules if r.number == number), None)
        if rule is None:
            raise ValidationError("no such rule", field="number")
        # Inactive: numbers are ours, not UFW's (it counts IPv6 copies), so delete by text.
        argv = ["ufw", "--force", "delete", *(rule.spec or [str(number)])]
        return await self._change("hostfw.ufw_rule_deleted", argv, target=str(number))

    async def ufw_enable(self, on: bool, *, keep_ssh: bool = True) -> str:
        """Turning UFW on with SSH allowed first (unless told otherwise): no lock-out."""
        if on and keep_ssh:
            st = await self.state(fresh=True)
            if not any(r.to.startswith(("22", "OpenSSH")) for r in st.ufw_rules):
                await self._run(["ufw", "limit", "proto", "tcp", "from", "any", "to", "any",
                                 "port", "22"])  # fmt: skip
        argv = ["ufw", "--force", "enable"] if on else ["ufw", "disable"]
        return await self._change("hostfw.ufw_enabled" if on else "hostfw.ufw_disabled", argv)

    async def jail_ip(self, jail: str, ip: str, *, ban: bool) -> str:
        st = await self.state(fresh=True)
        if not any(j.name == jail for j in st.jails):
            raise ValidationError("no such jail", field="jail")
        address = valid_ip(ip)
        verb = "banip" if ban else "unbanip"
        return await self._change("hostfw.banned" if ban else "hostfw.unbanned",
                                  ["fail2ban-client", "set", jail, verb, address],
                                  target=address, jail=jail)  # fmt: skip


# --- listening ports, routes, fail2ban jail settings (lot I) ----------------------------

SS_LINE = re.compile(
    r"^(tcp|udp)\s+\S+\s+\d+\s+\d+\s+(\S+):(\d+)\s+\S+(?:\s+users:\(\(\"([^\"]+)\")?"
)
JAIL_FILE = "/etc/fail2ban/jail.d/hivora.local"
DURATION = re.compile(r"^-?\d{1,9}[smhdw]?$")  # fail2ban: 600, 10m, 1h, 1d, -1 (forever)


@dataclass
class Listening:
    protocol: str
    address: str
    port: int
    process: str


def parse_ss(text: str) -> list[Listening]:
    """``ss -H -tulpn``: what listens on the host (one entry per protocol/port/address)."""
    seen: dict[tuple[str, str, int], Listening] = {}
    for line in text.splitlines():
        m = SS_LINE.match(line.strip())
        if m:
            proto, addr, port, proc = (
                m.group(1),
                m.group(2).strip("[]"),
                int(m.group(3)),
                m.group(4),
            )
            seen.setdefault((proto, addr, port), Listening(proto, addr, port, proc or ""))
    return sorted(seen.values(), key=lambda x: (x.port, x.protocol, x.address))


def jail_config(jails: dict[str, dict[str, Any]]) -> str:
    """The whole jail.d/hivora.local, generated from validated values only."""
    lines = ["# Written by Hivora: fail2ban settings changed from the panel.", ""]
    for name, s in sorted(jails.items()):
        if not JAIL.match(name):
            raise ValidationError("invalid jail name", field="jail")
        lines.append(f"[{name}]")
        lines.append(f"enabled = {'true' if s.get('enabled', True) else 'false'}")
        if s.get("maxretry") is not None:
            if not 1 <= int(s["maxretry"]) <= 1000:
                raise ValidationError("maxretry out of range", field="maxretry")
            lines.append(f"maxretry = {int(s['maxretry'])}")
        for key in ("bantime", "findtime"):
            if s.get(key) is not None:
                if not DURATION.match(str(s[key])):
                    raise ValidationError(f"invalid {key}", field=key)
                lines.append(f"{key} = {s[key]}")
        lines.append("")
    return "\n".join(lines)


async def listening(fw: "HostFirewall") -> list[dict[str, Any]]:
    """Open ports on the host, with what opens them (a Docker app, a host process) and
    whether UFW would filter them (it does not for ports Docker publishes)."""
    _, out = await fw._run(["ss", "-H", "-tulpn"], check=False)
    state = await fw.state()
    published: dict[tuple[int, str], str] = {}
    for c in fw.store.containers():
        for p in c.ports:
            if p.host_port:
                published[(p.host_port, p.protocol)] = c.labels.get("io.hivora.app") or c.name
    rules = [r for r in state.ufw_rules if "ALLOW" in r.action or "LIMIT" in r.action]
    out_rows = []
    for item in parse_ss(out):
        docker = published.get((item.port, item.protocol))
        allowed = any(r.to.split("/")[0] == str(item.port) or r.to.startswith(f"{item.port}/")
                      for r in rules)  # fmt: skip
        if item.address == "::1" or item.address.startswith("127."):
            ufw = "local"
        elif docker:
            ufw = "bypassed"  # Docker's own rules come first
        elif not state.ufw_active:
            ufw = "off"
        else:
            ufw = "allowed" if allowed else "blocked"
        out_rows.append({**item.__dict__, "app": docker, "ufw": ufw})
    return out_rows


async def routes(fw: "HostFirewall") -> list[dict[str, Any]]:
    _, out = await fw._run(["ip", "-j", "route"], check=False)
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return []
    keys = ("dst", "gateway", "dev", "protocol", "scope", "prefsrc", "metric")
    return [{k: r.get(k) for k in keys} for r in rows if isinstance(r, dict)]


async def jail_settings(fw: "HostFirewall") -> dict[str, dict[str, str]]:
    state = await fw.state()
    out: dict[str, dict[str, str]] = {}
    for jail in state.jails:
        values = {}
        for key in ("maxretry", "bantime", "findtime"):
            code, text = await fw._run(["fail2ban-client", "get", jail.name, key], check=False)
            values[key] = text.strip() if code == 0 else ""
        out[jail.name] = values
    return out


async def save_jails(fw: "HostFirewall", jails: dict[str, dict[str, Any]]) -> str:
    """Write jail.d/hivora.local (content passed as an argument, never as shell code),
    then reload fail2ban."""
    content = jail_config(jails)
    await fw._run(["sh", "-c", 'printf "%s" "$1" > ' + JAIL_FILE, "hivora", content])
    out = await fw._change("hostfw.jails_saved", ["fail2ban-client", "reload"],
                           target=", ".join(sorted(jails)))  # fmt: skip
    return out
