"""The System page's health checks (M12-6): read only, nothing changed, nothing secret.

Each check is a pure function of facts (sizes, dates, bindings, counts) and returns a
`Check`; `SystemStatus` gathers the facts. The costly one, `PRAGMA quick_check`, runs
only when asked (``deep``).
"""

import asyncio
import shutil
import socket
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from cryptography import x509
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora import __version__
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.db.migrate import db_revision, schema_state
from hivora.docker_gateway import DockerGateway
from hivora.jobs.queries import job_health
from hivora.vpn.admin import AdminVpn

Level = Literal["ok", "warn", "error", "unknown"]
ORDER: dict[Level, int] = {"ok": 0, "unknown": 1, "warn": 2, "error": 3}
GB = 1024**3
DISK_WARN = (0.10, 20 * GB)  # warn: under 10 % AND under 20 GB free (big disks stay calm)
DISK_ERROR = (0.03, 500 * 1024**2)  # error: under 3 % OR under 500 MB free
WAL_WARN = 256 * 1024**2
TLS_WARN_DAYS = 30
STUCK = timedelta(hours=1)
SELF_LABEL = {"io.hivora.self": "true"}  # set by the installer and compose.yaml
ALL_ADDRESSES = ("0.0.0.0", "::", "")  # noqa: S104  # what is checked, not bound


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    level: Level
    values: dict[str, Any] = field(default_factory=dict)


def worst(checks: list[Check]) -> Level:
    return max((c.level for c in checks), key=ORDER.__getitem__, default="ok")


def check_version(revision: str | None) -> Check:
    return Check("version", "ok", {"version": __version__, "schema": revision})


def check_database(state: str, size: int, wal: int, quick: str | None) -> Check:
    level: Level = "ok"
    if wal > WAL_WARN:
        level = "warn"
    if state != "current" or (quick is not None and quick != "ok"):
        level = "error"
    return Check("database", level, {"schema": state, "size": size, "wal": wal,
                                     "quick_check": quick})  # fmt: skip


def disk_level(total: int, free: int) -> Level:
    if total <= 0:
        return "unknown"
    ratio = free / total
    if ratio < DISK_ERROR[0] or free < DISK_ERROR[1]:
        return "error"
    if ratio < DISK_WARN[0] and free < DISK_WARN[1]:
        return "warn"
    return "ok"


def check_disk(usage: dict[str, tuple[int, int]]) -> Check:
    """``usage``: name -> (total, free) bytes, for the panel data and the app volumes."""
    levels = [disk_level(total, free) for total, free in usage.values()]
    values = {f"{name}_{k}": v for name, (total, free) in usage.items()
              for k, v in (("total", total), ("free", free))}  # fmt: skip
    return Check("disk", max(levels, key=ORDER.__getitem__, default="unknown"), values)


def check_docker(version: str | None) -> Check:
    return Check("docker", "ok" if version else "error", {"version": version})


def check_jobs(counts: dict[str, int]) -> Check:
    level: Level = "warn" if counts.get("failed") or counts.get("stuck") else "ok"
    return Check("jobs", level, counts)


def check_panel_backup(last: datetime | None) -> Check:
    return Check("panel_backup", "ok" if last else "warn",
                 {"last": last.isoformat() if last else None})  # fmt: skip


def check_exposure(access: str, hosts: list[str] | None) -> Check:
    """``hosts``: where the panel's own container publishes its port (None: not found, e.g.
    run from the sources). Every address outside the public mode: no mandatory TOTP."""
    values: dict[str, Any] = {"access": access, "published": hosts}
    if hosts is None:
        return Check("exposure", "unknown", values)
    everywhere = any(h in ALL_ADDRESSES for h in hosts)
    if access == "public":
        return Check("exposure", "warn", values)
    return Check("exposure", "error" if everywhere else "ok", values)


def check_admin_vpn(health: dict[str, bool]) -> Check:
    ok = all(health.values())
    return Check("admin_vpn", "ok" if ok else "warn", dict(health))


def check_tls(enabled: bool, expires: datetime | None, now: datetime) -> Check:
    if not enabled:
        return Check("tls", "ok", {"enabled": False})
    if expires is None:
        return Check("tls", "unknown", {"enabled": True})
    days = (expires - now).days
    level: Level = "error" if expires <= now else "warn" if days < TLS_WARN_DAYS else "ok"
    return Check("tls", level, {"enabled": True, "expires": expires.isoformat(), "days": days})


def quick_check(db_path: Path) -> str:
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        rows = conn.execute("PRAGMA quick_check").fetchall()
    return "; ".join(str(r[0]) for r in rows)[:500]


class SystemStatus:
    def __init__(self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession],
                 gateway: DockerGateway, admin_vpn: AdminVpn, clock: Clock) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.gateway = gateway
        self.admin_vpn = admin_vpn
        self.clock = clock

    async def checks(self, *, deep: bool = False) -> list[Check]:
        s, now = self.settings, self.clock.now()
        db = s.db_path
        wal = db.with_name(db.name + "-wal")
        quick = await asyncio.to_thread(quick_check, db) if deep else None
        async with self.sessions() as session:
            counts = await job_health(session, now - timedelta(hours=24), now - STUCK)
        out = [
            check_version(db_revision(db)),
            check_database(schema_state(db), _size(db), _size(wal), quick),
            check_disk({"data": _usage(s.data_dir), "volumes": _usage(s.volumes_root)}),
            check_docker(await self._docker()),
            check_jobs(counts),
            check_panel_backup(_newest(s.data_dir / "backups" / "_hivora")),
            check_exposure(s.access, await self._published()),
            check_tls(s.tls, _cert_expiry(s.data_dir / "tls" / "cert.pem"), now),
        ]
        if (vpn := await self.admin_vpn.health()) is not None:
            out.append(check_admin_vpn(vpn))
        return out

    async def _docker(self) -> str | None:
        try:
            async with asyncio.timeout(5):
                return await self.gateway.ping()
        except Exception:
            return None

    async def _published(self) -> list[str] | None:
        try:
            async with asyncio.timeout(5):
                found = await self.gateway.list_containers(SELF_LABEL)
        except Exception:
            return None
        # Its own container: Docker names the host after the container's short id (two
        # Hivoras on one Docker see each other's label); not recognised: every one found.
        me = socket.gethostname()
        found = [c for c in found if c.id.startswith(me)] or found
        if not found:
            return None
        return sorted({p.host_ip or "" for c in found for p in c.ports if p.host_port})


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _usage(path: Path) -> tuple[int, int]:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return 0, 0
    return u.total, u.free


def _newest(folder: Path) -> datetime | None:
    times = [p.stat().st_mtime for p in folder.glob("*.tar.gz")] if folder.is_dir() else []
    return datetime.fromtimestamp(max(times), UTC) if times else None


def _cert_expiry(path: Path) -> datetime | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes()).not_valid_after_utc
    except (OSError, ValueError):
        return None
