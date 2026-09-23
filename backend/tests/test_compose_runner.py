import asyncio
import sys
from pathlib import Path

import pytest

from hivora.compose_runner import (
    AppBusyError,
    ComposeError,
    ComposeRunner,
    ProgressEvent,
    ProgressStatus,
)
from hivora.compose_runner.progress import parse_progress_line
from hivora.compose_runner.redact import MASK, Redactor
from hivora.core.errors import ValidationError

FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


def runner(tmp_path: Path, mode: str = "ok") -> ComposeRunner:
    r = ComposeRunner(tmp_path / "apps", compose_cmd=FAKE, env={"FAKE_COMPOSE_MODE": mode})
    r.write("demo", "services: {}\n")
    return r


def test_parse_progress_line() -> None:
    e = parse_progress_line(
        '{"id":"abc","parent_id":"Image x","status":"Working",'
        '"text":"Downloading","current":1,"total":4,"percent":25}'
    )
    assert e == ProgressEvent(
        "abc",
        ProgressStatus.WORKING,
        "Downloading",
        parent="Image x",
        current=1,
        total=4,
        percent=25,
    )
    assert parse_progress_line("   ") is None
    assert parse_progress_line("plain").status is ProgressStatus.INFO  # type: ignore[union-attr]
    err = parse_progress_line('{"error":true,"message":"boom"}')
    assert err is not None and err.status is ProgressStatus.ERROR and err.text == "boom"


def test_redactor_masks_longest_first_and_ignores_tiny_values() -> None:
    redact = Redactor(["abcd", "abcdef", "x"])
    assert redact("abcdef abcd x") == f"{MASK} {MASK} x"


def test_write_is_atomic_and_slug_validated(tmp_path: Path) -> None:
    r = ComposeRunner(tmp_path)
    path = r.write("demo", "a: 1\n")
    r.write("demo", "a: 2\n")
    assert path.read_text() == "a: 2\n"
    assert [p.name for p in path.parent.iterdir()] == ["compose.yaml"]
    for bad in ("../etc", "Demo", "", "a/b"):
        with pytest.raises(ValidationError):
            r.write(bad, "")


async def test_config_passes_project_and_file(tmp_path: Path) -> None:
    config = await runner(tmp_path).config("demo")
    assert config["name"] == "demo"
    argv = config["argv"]
    assert argv[:4] == ["--progress", "json", "--project-name", "demo"]
    assert argv[-3:] == ["config", "--format", "json"]


async def test_up_streams_progress(tmp_path: Path) -> None:
    seen: list[ProgressEvent] = []

    async def collect(event: ProgressEvent) -> None:
        seen.append(event)

    result = await runner(tmp_path).up("demo", on_progress=collect)
    assert result.returncode == 0
    assert [e.text for e in seen][:3] == ["Pulling", "Downloading", "Started"]
    assert seen[1].percent == 50
    assert seen[-1].status is ProgressStatus.INFO


async def test_failure_raises_with_last_error(tmp_path: Path) -> None:
    with pytest.raises(ComposeError, match="pull access denied"):
        await runner(tmp_path, "fail").up("demo")


async def test_secrets_never_leave_the_runner(tmp_path: Path) -> None:
    result = await runner(tmp_path, "secret").up("demo", redact=["s3cr3t-value"])
    texts = " ".join(e.text for e in result.events)
    assert "s3cr3t-value" not in texts and MASK in texts


async def test_lock_rejects_concurrent_operation(tmp_path: Path) -> None:
    r = ComposeRunner(tmp_path)
    async with r.lock("demo"):
        assert r.is_locked("demo")
        with pytest.raises(AppBusyError):
            async with r.lock("demo"):
                pass
        async with r.lock("other"):  # other apps are independent
            pass
    assert not r.is_locked("demo")
    await asyncio.sleep(0)
