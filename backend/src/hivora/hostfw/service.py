"""The host's own firewall (UFW) and fail2ban, through the optional host agent.

Hivora never gets a shell on the host: an admin turns the agent on, then only
the fixed command lines below run there (``nsenter`` into the host's
namespaces), with arguments validated here, never interpolated into a shell.
UFW does not filter ports published by Docker (Docker bypasses it); the UI
says so rather than presenting UFW as a protection for the apps.
"""

import asyncio
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from hivora.core.errors import ConflictError, ValidationError
from hivora.db.models import Setting
from hivora.runtime import Runtime

AGENT = "hivora-host-agent"
AGENT_IMAGE = "alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8"
SETTING = "host_agent"
HOST = ["nsenter", "-t", "1", "-m", "-u", "-n", "-i", "--"]
TIMEOUT_S = 30
JAIL = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
CACHE_S = 20
LABELS = {"io.hivora.self": "true", "io.hivora.agent": "host"}
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
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self._cache: tuple[float, FirewallState] | None = None

    # --- the agent ---------------------------------------------------------------
    async def agent_enabled(self) -> bool:
        async with self.rt.sessions() as session:
            row = await session.get(Setting, SETTING)
        return bool(row and row.value is True)

    async def set_agent(self, on: bool) -> None:
        if on:
            await self.rt.gateway.ensure_agent(AGENT, AGENT_IMAGE, LABELS)
        else:
            await self.rt.gateway.remove_agent(AGENT)
        async with self.rt.sessions() as session, session.begin():
            await session.merge(Setting(key=SETTING, value=on))
        self._cache = None
        self.rt.bus.publish("hostfw.agent_enabled" if on else "hostfw.agent_disabled")

    async def _run(self, argv: list[str], *, check: bool = True) -> tuple[int, str]:
        if not await self.agent_enabled():
            raise AgentOffError("the host agent is off (Settings → host firewall)")
        agent = await self.rt.gateway.ensure_agent(AGENT, AGENT_IMAGE, LABELS)
        async with asyncio.timeout(TIMEOUT_S):
            code, out = await self.rt.gateway.exec_run(agent, [*HOST, *argv])
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
            _, numbered = await self._run(["ufw", "status", "numbered"], check=False)
            st.ufw_rules = parse_ufw_numbered(numbered)
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
        self.rt.bus.publish(event, **details)
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
        if not any(r.number == number for r in st.ufw_rules):
            raise ValidationError("no such rule", field="number")
        argv = ["ufw", "--force", "delete", str(number)]
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
