import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hivora.core.clock import FrozenClock
from hivora.core.config import Settings
from hivora.core.events import EventBus
from hivora.core.logging import JsonFormatter


def test_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().db_path == Path("/opt/hivora/data/hivora.db")
    monkeypatch.setenv("HIVORA_DATA_DIR", "/tmp/x")
    s = Settings()
    assert s.secret_key_path == Path("/tmp/x/secret.key")
    assert s.apps_dir == Path("/tmp/x/apps")


async def test_bus_routes_by_pattern() -> None:
    bus = EventBus()
    apps = bus.subscribe("app.*")
    everything = bus.subscribe()
    bus.publish("app.deployed", app="minecraft")
    bus.publish("docker.container.die", id="abc")

    assert apps.queue.qsize() == 1
    assert (await apps.queue.get()).payload == {"app": "minecraft"}
    assert everything.queue.qsize() == 2


async def test_bus_drops_oldest_for_slow_subscriber() -> None:
    bus = EventBus()
    sub = bus.subscribe(maxsize=2)
    for i in range(3):
        bus.publish("t", i=i)
    assert sub.dropped == 1
    assert [(await sub.queue.get()).payload["i"] for _ in range(2)] == [1, 2]


async def test_bus_subscription_context_unsubscribes() -> None:
    bus = EventBus()

    async def consume() -> str:
        async with bus.subscribe() as sub:
            async for event in sub:
                return event.topic
        return ""

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    bus.publish("hello")
    assert await task == "hello"
    assert not bus._subscriptions


def test_json_formatter_includes_extra() -> None:
    record = logging.makeLogRecord(
        {
            "msg": "deployed %s",
            "args": ("x",),
            "levelname": "INFO",
            "name": "hivora.apps",
            "app": "x",
        }
    )
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "deployed x"
    assert out["app"] == "x"


def test_frozen_clock() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(t0)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == t0 + timedelta(minutes=5)


def test_self_signed_certificate_created_once(tmp_path: Path) -> None:
    from cryptography import x509

    from hivora.__main__ import self_signed

    cert, key = self_signed(tmp_path / "tls", ["localhost", "192.168.1.10", ""])
    assert key.stat().st_mode & 0o077 == 0
    parsed = x509.load_pem_x509_certificate(cert.read_bytes())
    san = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert [str(ip) for ip in san.get_values_for_type(x509.IPAddress)] == ["192.168.1.10"]
    before = cert.read_bytes()
    self_signed(tmp_path / "tls", ["other"])  # kept: the user may have put their own
    assert cert.read_bytes() == before
