"""Available versions (M12-7): GitHub Releases, read only, cached, off = no request."""

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import API, admin, code, login, other_user

from hivora import __version__
from hivora.core.clock import FrozenClock
from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.system.releases import (
    changelog_section,
    newer,
    parse_version,
    pick_latest,
    plain_notes,
    repo_of,
    update_command,
)

REPO = "https://github.com/hiidenops/hivora"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def release(tag: str, *, pre: bool = False, draft: bool = False, body: str = "") -> dict[str, Any]:
    return {"tag_name": tag, "prerelease": pre, "draft": draft, "body": body,
            "published_at": "2026-10-20T10:00:00Z",
            "html_url": f"{REPO}/releases/tag/{tag}"}  # fmt: skip


class FakeGitHub:
    """Records every request; answers as told (a status and releases, or a network error)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.answer: tuple[int, Any] | Exception = (200, [release("v0.1.0")])

    async def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, Any]:
        self.calls.append((url, headers))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_versions_compare_as_numbers_and_rc_come_first() -> None:
    assert parse_version("v0.10.0") > parse_version("v0.9.0")  # type: ignore[operator]
    assert parse_version("v0.2.0-rc.1") < parse_version("v0.2.0")  # type: ignore[operator]
    assert parse_version("v0.2.0-rc.2") > parse_version("v0.2.0-rc.1")  # type: ignore[operator]
    assert parse_version("latest") is None and parse_version("v1.2") is None
    assert newer("0.1.0", "v0.2.0") and not newer("0.2.0", "v0.2.0")
    assert not newer("0.3.0", "v0.2.0")  # a development build ahead of the releases
    assert not newer("0.1.0", "nightly")


def test_the_channel_decides_which_release_is_latest() -> None:
    releases = [release("v0.1.0"), release("v0.2.0-rc.1", pre=True),
                release("v0.3.0", draft=True), release("nightly")]  # fmt: skip
    assert pick_latest(releases, "stable")["tag_name"] == "v0.1.0"  # type: ignore[index]
    assert pick_latest(releases, "pre")["tag_name"] == "v0.2.0-rc.1"  # type: ignore[index]
    assert pick_latest([release("v0.3.0", draft=True)], "pre") is None
    assert pick_latest([], "stable") is None


def test_notes_command_repo_and_changelog() -> None:
    notes = plain_notes('Fix <img src="https://x.example/p.png"> <script>alert(1)</script>ok')
    assert "<" not in notes and "img" not in notes and notes.endswith("ok")
    assert len(plain_notes("a" * 30_000)) == 20_000
    assert repo_of(REPO) == "hiidenops/hivora" and repo_of(f"{REPO}.git/") == "hiidenops/hivora"
    assert repo_of("https://codeberg.org/someone/hivora") is None
    assert update_command("hiidenops/hivora", "v0.2.0") == (
        "curl -fsSL https://github.com/hiidenops/hivora/releases/download/v0.2.0/install.sh"
        " | sudo sh"
    )
    text = "# Journal\n\n## [Non publié]\n\n- a\n\n## [0.1.0]\n\n### Ajouté\n\n- b\n"
    assert changelog_section(text, "0.1.0") == "### Ajouté\n\n- b"
    assert changelog_section(text, "0.2.0") is None


@contextmanager
def panel(tmp_path: Path, github: FakeGitHub, **settings: Any) -> Iterator[TestClient]:
    s = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                 catalog_dir=Path(__file__).parents[2] / "templates", dev_insecure_cookies=True,
                 puid=os.getuid(), pgid=os.getgid(),
                 changelog_path=Path(__file__).parents[2] / "CHANGELOG.md", **settings)  # fmt: skip
    clock = FrozenClock(NOW)
    runtime = Runtime.build(s, gateway=FakeDockerGateway(), clock=clock)
    runtime.releases.fetch = github
    with TestClient(create_app(runtime=runtime)) as c:
        yield c


def clock_of(c: TestClient) -> FrozenClock:
    clock: FrozenClock = c.app.state.runtime.releases.clock  # type: ignore[attr-defined]
    return clock


def test_one_request_per_12_hours_and_only_the_user_agent(tmp_path: Path) -> None:
    github = FakeGitHub()
    with panel(tmp_path, github) as c:
        admin(c)
        r = c.get(f"{API}/system/releases").json()
        assert r["enabled"] and r["channel"] == "stable" and r["available"]
        assert r["current"] == __version__ and r["latest"]["version"] == "0.1.0"
        assert r["newer"] is (__version__ != "0.1.0")
        assert r["command"].endswith("/releases/download/v0.1.0/install.sh | sudo sh")
        url, headers = github.calls[0]
        assert url == "https://api.github.com/repos/hiidenops/hivora/releases?per_page=30"
        assert headers == {"User-Agent": f"Hivora/{__version__}",
                           "Accept": "application/vnd.github+json"}  # fmt: skip
        c.get(f"{API}/system/releases")
        clock_of(c).advance(timedelta(hours=11))
        c.get(f"{API}/system/releases")
        assert len(github.calls) == 1  # cached
        clock_of(c).advance(timedelta(hours=2))
        c.get(f"{API}/system/releases")
        assert len(github.calls) == 2  # 13 hours later


def test_offline_is_quiet_and_retried_after_an_hour(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.answer = OSError("no route to host")
    with panel(tmp_path, github) as c:
        admin(c)
        r = c.get(f"{API}/system/releases")
        assert r.status_code == 200 and r.json()["error"] == "offline"
        assert r.json()["latest"] is None
        clock_of(c).advance(timedelta(minutes=30))
        c.get(f"{API}/system/releases")
        assert len(github.calls) == 1
        github.answer = (403, None)  # GitHub's rate limit
        clock_of(c).advance(timedelta(minutes=31))
        assert c.get(f"{API}/system/releases").json()["error"] == "rate_limited"
        github.answer = (200, [release("v0.1.0")])
        clock_of(c).advance(timedelta(minutes=61))
        r = c.get(f"{API}/system/releases").json()
        assert r["error"] is None and r["latest"]["tag"] == "v0.1.0" and r["checked_at"]


def test_check_now_at_most_once_a_minute(tmp_path: Path) -> None:
    github = FakeGitHub()
    with panel(tmp_path, github) as c:
        admin(c)
        c.get(f"{API}/system/releases")
        c.get(f"{API}/system/releases", params={"refresh": "true"})
        assert len(github.calls) == 1  # the same minute
        clock_of(c).advance(timedelta(seconds=61))
        c.get(f"{API}/system/releases", params={"refresh": "true"})
        assert len(github.calls) == 2


def test_off_means_no_request_at_all(tmp_path: Path) -> None:
    github = FakeGitHub()
    with panel(tmp_path, github) as c:
        admin(c)
        r = c.put(f"{API}/system/releases/settings", json={"enabled": False, "channel": "pre"})
        assert r.status_code == 204
        clock_of(c).advance(timedelta(hours=11))  # (12 h idle: the session would end)
        body = c.get(f"{API}/system/releases", params={"refresh": "true"}).json()
        assert body["enabled"] is False and body["channel"] == "pre" and body["latest"] is None
        assert github.calls == []
        bad = c.put(f"{API}/system/releases/settings", json={"enabled": True, "channel": "beta"})
        assert bad.status_code == 422


def test_the_pre_channel_shows_release_candidates(tmp_path: Path) -> None:
    github = FakeGitHub()
    rc = release("v0.2.0-rc.1", pre=True, body="**rc** <b>notes</b>")
    github.answer = (200, [release("v0.1.0", body="stable"), rc])
    with panel(tmp_path, github) as c:
        admin(c)
        assert c.get(f"{API}/system/releases").json()["latest"]["tag"] == "v0.1.0"
        c.put(f"{API}/system/releases/settings", json={"enabled": True, "channel": "pre"})
        latest = c.get(f"{API}/system/releases").json()["latest"]
        assert latest["tag"] == "v0.2.0-rc.1" and latest["prerelease"]
        assert latest["notes"] == "**rc** notes"  # text: markdown as is, no HTML


def test_a_source_outside_github_is_not_checked(tmp_path: Path) -> None:
    github = FakeGitHub()
    with panel(tmp_path, github, source_url="https://codeberg.org/someone/hivora") as c:
        admin(c)
        body = c.get(f"{API}/system/releases").json()
        assert body["available"] is False and body["latest"] is None and github.calls == []


def test_the_installed_versions_notes_and_admins_only(tmp_path: Path) -> None:
    github = FakeGitHub()
    with panel(tmp_path, github) as c:
        admin(c)
        body = c.get(f"{API}/system/releases").json()
        changelog = (Path(__file__).parents[2] / "CHANGELOG.md").read_text()
        assert body["current_notes"] == changelog_section(changelog, __version__)
        for role in ("viewer", "operator"):
            c.post(f"{API}/users", json={"username": role, "password": f"{role}-pass-1",
                                         "role": role})  # fmt: skip
            with other_user(c) as other:
                login(other, role, f"{role}-pass-1")
                other.post(f"{API}/auth/password",
                           json={"current": f"{role}-pass-1", "new": f"{role}-pass-2"})  # fmt: skip
                for r in (other.get(f"{API}/system/releases"),
                          other.put(f"{API}/system/releases/settings",
                                    json={"enabled": False, "channel": "stable"})):  # fmt: skip
                    assert r.status_code == 403 and code(r) == "insufficient_role", role


def test_changing_the_settings_is_audited(tmp_path: Path) -> None:
    import time

    with panel(tmp_path, FakeGitHub()) as c:
        admin(c)
        c.put(f"{API}/system/releases/settings", json={"enabled": False, "channel": "stable"})
        deadline = time.monotonic() + 5  # the audit is written in batches (0.5 s)
        while "settings.releases_updated" not in c.get(f"{API}/audit").text:
            assert time.monotonic() < deadline
            time.sleep(0.05)


def test_concurrent_reads_make_one_request_and_all_see_it(sessions: Any) -> None:
    from hivora.system.releases import ReleaseChecker

    class SlowGitHub(FakeGitHub):
        async def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, Any]:
            await asyncio.sleep(0.05)  # the others arrive while GitHub answers
            return await super().__call__(url, headers)

    github = SlowGitHub()
    checker = ReleaseChecker(settings=Settings(), sessions=sessions, clock=FrozenClock(NOW),
                             fetch=github)  # fmt: skip

    async def three() -> list[dict[str, Any]]:
        return list(await asyncio.gather(checker.view(), checker.view(), checker.view()))

    views = asyncio.run(three())
    assert len(github.calls) == 1
    assert [v["latest"]["tag"] if v["latest"] else None for v in views] == ["v0.1.0"] * 3


@pytest.mark.parametrize("status", [404, 500])
def test_other_answers(tmp_path: Path, status: int) -> None:
    github = FakeGitHub()
    github.answer = (status, None)
    with panel(tmp_path, github) as c:
        admin(c)
        error = c.get(f"{API}/system/releases").json()["error"]
        assert error == ("not_found" if status == 404 else "unavailable")
