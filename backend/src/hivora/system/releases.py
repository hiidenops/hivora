"""Available versions (M12-7): the GitHub Releases of the source repository, read only.

On by default (D6), off in Settings: then no request at all. At most one request per
12 hours (one per hour after a failure), kept in memory; nothing sent but the
``User-Agent``. Offline: the panel says so quietly, nothing breaks. Remote notes are
shown as plain text (nothing third-party is loaded); the installed version's notes come
from the CHANGELOG.md shipped in the image.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Literal

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hivora import __version__
from hivora.core.clock import Clock
from hivora.core.config import Settings
from hivora.db.models import Setting

Channel = Literal["stable", "pre"]
PREFS = "system.releases"  # {"enabled": bool, "channel": "stable" | "pre"}
DEFAULTS: dict[str, Any] = {"enabled": True, "channel": "stable"}
FRESH = timedelta(hours=12)
RETRY = timedelta(hours=1)  # after a failure
REFRESH = timedelta(minutes=1)  # "check now", at most once a minute
NOTES_MAX = 20_000
TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
GITHUB = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$")

# (status, JSON) of a GET with these headers; raises when the network fails.
Fetch = Callable[[str, dict[str, str]], Awaitable[tuple[int, Any]]]


def parse_version(tag: str) -> tuple[int, int, int, int] | None:
    """Comparable: a release candidate comes before its final version (rc 1 < final)."""
    m = TAG.match(tag.strip())
    if not m:
        return None
    major, minor, patch, rc = m.groups()
    return int(major), int(minor), int(patch), int(rc) if rc else 1_000_000


def pick_latest(releases: list[dict[str, Any]], channel: str) -> dict[str, Any] | None:
    """The highest version of the channel: no drafts, no pre-releases on stable."""
    found = [r for r in releases if not r.get("draft") and parse_version(r.get("tag_name", ""))
             and (channel == "pre" or not r.get("prerelease"))]  # fmt: skip
    return max(found, key=lambda r: parse_version(r["tag_name"]) or (0,), default=None)


def newer(current: str, latest: str) -> bool:
    now, then = parse_version(current), parse_version(latest)
    return bool(now and then and then > now)


def plain_notes(body: str | None) -> str:
    """Release notes as plain text: no HTML at all (shown as text, never rendered)."""
    text = re.sub(r"<[^>]*>", "", body or "")
    return text.strip()[:NOTES_MAX]


def changelog_section(text: str, version: str) -> str | None:
    """The ``## [X.Y.Z]`` section of CHANGELOG.md (Keep a Changelog), without its title."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    return m.group(1).strip() if m and m.group(1).strip() else None


def repo_of(source_url: str) -> str | None:
    """owner/repo of a GitHub source URL; anything else: no check (said so in the panel)."""
    m = GITHUB.match(source_url.strip())
    return m.group(1) if m else None


def update_command(repo: str, tag: str) -> str:
    """The release's own installer: it installs that version, keeping install.env's options."""
    return (
        f'sudo sh -c "$(curl -fsSL https://github.com/{repo}/releases/download/{tag}/install.sh)"'
    )


async def github_fetch(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as http, http.get(url, headers=headers) as r:
        return r.status, (await r.json(content_type=None) if r.status == 200 else None)


class ReleaseChecker:
    """One per Hivora (built by Runtime): its cache lives as long as the server."""

    def __init__(self, *, settings: Settings, sessions: async_sessionmaker[AsyncSession],
                 clock: Clock, fetch: Fetch = github_fetch) -> None:  # fmt: skip
        self.settings = settings
        self.sessions = sessions
        self.clock = clock
        self.fetch = fetch
        self._lock = asyncio.Lock()
        self._releases: list[dict[str, Any]] | None = None
        self._checked_at: datetime | None = None  # last success
        self._tried_at: datetime | None = None  # last attempt
        self._error: str | None = None

    async def prefs(self) -> dict[str, Any]:
        async with self.sessions() as session:
            row = await session.get(Setting, PREFS)
        return {**DEFAULTS, **(row.value if row else {})}

    async def set_prefs(self, enabled: bool, channel: Channel) -> None:
        async with self.sessions() as session, session.begin():
            await session.merge(Setting(key=PREFS, value={"enabled": enabled, "channel": channel}))

    async def view(self, *, refresh: bool = False) -> dict[str, Any]:
        prefs = await self.prefs()
        repo = repo_of(self.settings.source_url)
        out: dict[str, Any] = {**prefs, "available": repo is not None, "current": __version__,
                               "current_notes": self._local_notes(), "latest": None,
                               "newer": False, "command": None, "checked_at": None,
                               "error": None}  # fmt: skip
        if not prefs["enabled"] or repo is None:
            return out  # off, or not on GitHub: no request at all
        releases = await self._get(repo, refresh=refresh)
        out["checked_at"], out["error"] = self._checked_at, self._error
        latest = pick_latest(releases or [], prefs["channel"])
        if latest:
            tag = latest["tag_name"]
            out["latest"] = {"tag": tag, "version": tag.lstrip("v"),
                             "date": latest.get("published_at"), "url": latest.get("html_url"),
                             "notes": plain_notes(latest.get("body")),
                             "prerelease": bool(latest.get("prerelease"))}  # fmt: skip
            out["newer"] = newer(__version__, tag)
            out["command"] = update_command(repo, tag)
        return out

    async def _get(self, repo: str, *, refresh: bool) -> list[dict[str, Any]] | None:
        async with self._lock:
            now = self.clock.now()
            since = now - self._tried_at if self._tried_at else None
            if since is not None:
                wait = REFRESH if refresh else (RETRY if self._error else FRESH)
                if since < wait:
                    return self._releases
            self._tried_at = now
            url = f"https://api.github.com/repos/{repo}/releases?per_page=30"
            headers = {"User-Agent": f"Hivora/{__version__}",
                       "Accept": "application/vnd.github+json"}  # fmt: skip
            try:
                status, body = await self.fetch(url, headers)
            except Exception:
                self._error = "offline"
                return self._releases
            if status == 200 and isinstance(body, list):
                self._releases, self._checked_at, self._error = body, now, None
            else:
                self._error = {403: "rate_limited", 429: "rate_limited",
                               404: "not_found"}.get(status, "unavailable")  # fmt: skip
            return self._releases

    def _local_notes(self) -> str | None:
        try:
            return changelog_section(self.settings.changelog_path.read_text(), __version__)
        except OSError:
            return None
