import io
import os
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from helpers import API, admin, code, wait_job

from hivora.backups.models import BackupSchedule
from hivora.backups.service import InvalidBackupError, archive, extract
from hivora.core.schedule import next_run

PARIS = ZoneInfo("Europe/Paris")


def test_next_run_in_local_time() -> None:
    at = datetime(2026, 9, 28, 1, 30, tzinfo=UTC)  # 03:30 in Paris (UTC+2), a Monday
    daily = BackupSchedule(frequency="daily", hour=4, minute=0)
    assert next_run(daily, at, PARIS) == datetime(2026, 9, 28, 2, 0, tzinfo=UTC)
    later = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)  # exactly 04:00: the next day
    assert next_run(daily, later, PARIS) == datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
    weekly = BackupSchedule(frequency="weekly", hour=4, minute=0, weekday=6)  # Sunday
    assert next_run(weekly, at, PARIS) == datetime(2026, 10, 4, 2, 0, tzinfo=UTC)
    hourly = BackupSchedule(frequency="hours", every_hours=6)
    assert next_run(hourly, at, PARIS) == datetime(2026, 9, 28, 7, 30, tzinfo=UTC)
    # Winter time: 04:00 in Paris is 03:00 UTC.
    winter = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    assert next_run(daily, winter, PARIS) == datetime(2026, 11, 3, 3, 0, tzinfo=UTC)


def test_archive_round_trip_keeps_owners_and_refuses_strangers(tmp_path: Path) -> None:
    base = tmp_path / "srv" / "cube"
    data = base / "data"
    (data / "world").mkdir(parents=True)
    (data / "world" / "level.dat").write_bytes(b"v1")
    if os.getuid() == 0:
        os.chown(data / "world" / "level.dat", 1000, 1000)
    dest = tmp_path / "backups" / "cube.tar.gz"
    assert archive({"data": data}, dest) > 0

    (data / "world" / "level.dat").write_bytes(b"v2")
    (data / "new.txt").write_text("created after the backup")
    assert extract(dest, base, {"data": data}) == ["data"]
    assert (data / "world" / "level.dat").read_bytes() == b"v1"
    assert not (data / "new.txt").exists()
    if os.getuid() == 0:
        assert (data / "world" / "level.dat").stat().st_uid == 1000

    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        body = b"x"
        info = tarfile.TarInfo("data/../../escape.txt")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    with pytest.raises(tarfile.OutsideDestinationError):
        extract(evil, base, {"data": data})
    with pytest.raises(InvalidBackupError):
        extract(dest, base, {"other": data})


def test_backup_restore_schedule_and_retention(client: Any) -> None:
    admin(client)
    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8090}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    rt = client.app.state.runtime
    data = rt.settings.volumes_root / "coffre" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "db.sqlite3").write_text("first")

    overview = client.get(f"{API}/apps/{app_id}/backups").json()
    assert overview["volumes"] == ["data"] and overview["backups"] == []
    assert overview["schedule"]["enabled"] is False
    job = client.post(f"{API}/apps/{app_id}/backups").json()
    assert job["kind"] == "backup" and wait_job(client, job["id"])["status"] == "succeeded"
    [first] = client.get(f"{API}/apps/{app_id}/backups").json()["backups"]
    assert first["status"] == "ok" and first["size"] > 0 and not first["scheduled"]
    download = client.get(f"{API}/apps/{app_id}/backups/{first['id']}/download")
    assert download.status_code == 200 and download.content[:2] == b"\x1f\x8b"  # gzip

    (data / "db.sqlite3").write_text("changed")
    job = client.post(f"{API}/apps/{app_id}/backups/{first['id']}/restore").json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert (data / "db.sqlite3").read_text() == "first"

    schedule = {"enabled": True, "frequency": "daily", "hour": 4, "minute": 0, "keep": 1}
    assert client.put(f"{API}/apps/{app_id}/backups/schedule", json=schedule).status_code == 200
    assert client.get(f"{API}/apps/{app_id}/backups").json()["next_run_at"] is not None
    for _ in range(2):  # two scheduled runs; retention keeps the newest one
        with sqlite3.connect(rt.settings.db_path) as db:
            db.execute("UPDATE backup_schedule SET next_run_at = '2000-01-01 00:00:00.000000'")
        client.portal.call(rt.backups.tick)
        pending = [j for j in client.get(f"{API}/jobs").json() if j["kind"] == "backup"]
        wait_job(client, pending[0]["id"])
    rows = client.get(f"{API}/apps/{app_id}/backups").json()["backups"]
    assert [b["scheduled"] for b in rows].count(True) == 1 and len(rows) == 2

    assert client.delete(f"{API}/apps/{app_id}/backups/{first['id']}").status_code == 204
    gone = client.get(f"{API}/apps/{app_id}/backups/{first['id']}/download")
    assert gone.status_code == 404 and code(gone) == "backup_not_found"


def test_backups_overview_lists_newest_first_and_404s_unknown_apps(client: Any) -> None:
    """GET /apps/{id}/backups, pinned before its SQL moves into BackupService."""
    from datetime import timedelta

    from hivora.backups.models import Backup

    admin(client)
    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8091}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]
    rt = client.app.state.runtime

    # No schedule yet: the defaults, no next run, the server's time zone.
    empty = client.get(f"{API}/apps/{app_id}/backups").json()
    assert empty == {"schedule": {"enabled": False, "frequency": "daily", "hour": 4,
                                  "minute": 0, "weekday": 0, "every_hours": 6, "keep": 7,
                                  "stop": True},
                     "next_run_at": None, "timezone": rt.settings.timezone,
                     "volumes": ["data"], "backups": []}  # fmt: skip

    # Rows inserted out of time order: the list follows created_at, newest first.
    base = datetime(2026, 9, 1, 12, tzinfo=UTC)

    async def insert() -> None:
        async with rt.sessions() as session, session.begin():
            for hours, scheduled, status in ((3, True, "ok"), (1, False, "failed"),
                                             (2, False, "ok")):  # fmt: skip
                session.add(Backup(app_id=app_id, created_at=base + timedelta(hours=hours),
                                   scheduled=scheduled, status=status, size=hours * 10,
                                   path=f"/backups/coffre/b{hours}.tar.gz"))  # fmt: skip

    client.portal.call(insert)
    rows = client.get(f"{API}/apps/{app_id}/backups").json()["backups"]
    assert [b["name"] for b in rows] == ["b3.tar.gz", "b2.tar.gz", "b1.tar.gz"]
    assert [b["id"] for b in rows] != sorted(b["id"] for b in rows)  # not the id order
    assert [(b["scheduled"], b["status"], b["size"]) for b in rows] == [
        (True, "ok", 30), (False, "ok", 20), (False, "failed", 10),
    ]  # fmt: skip

    missing = client.get(f"{API}/apps/999999/backups")
    assert missing.status_code == 404 and code(missing) == "app_not_found"
