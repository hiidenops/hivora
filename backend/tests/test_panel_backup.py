import os
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command

from hivora.core.config import Settings
from hivora.db.migrate import SchemaTooNewError, alembic_config, schema_state
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.runtime import Runtime
from hivora.system.panel_backup import backup_panel


def sql(db: Path, statement: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(db)) as conn, conn:
        return conn.execute(statement).fetchall()


def panel(tmp_path: Path, revision: str = "head") -> Path:
    """A data folder whose database is migrated up to ``revision``, with a master key."""
    data = tmp_path / "data"
    data.mkdir()
    command.upgrade(alembic_config(data / "hivora.db"), revision)
    sql(data / "hivora.db", "INSERT INTO setting (key, value) VALUES ('language', '\"fr\"')")
    (data / "secret.key").write_bytes(b"k" * 32)
    (data / "secret.key").chmod(0o600)
    return data


def archives(data: Path) -> list[Path]:
    return sorted((data / "backups" / "_hivora").glob("panel-*.tar.gz"))


def build(data: Path) -> Runtime:
    settings = Settings(data_dir=data, volumes_root=data.parent / "srv",
                        catalog_dir=Path(__file__).parents[2] / "templates")  # fmt: skip
    return Runtime.build(settings, gateway=FakeDockerGateway())


def test_schema_state_tells_fresh_current_behind_and_newer(tmp_path: Path) -> None:
    assert schema_state(tmp_path / "none.db") == "fresh"
    empty = tmp_path / "empty.db"
    sql(empty, "CREATE TABLE t (x)")  # a file, never migrated
    assert schema_state(empty) == "fresh"
    data = panel(tmp_path)
    db = data / "hivora.db"
    assert schema_state(db) == "current"
    command.downgrade(alembic_config(db), "0020")
    assert schema_state(db) == "behind"
    sql(db, "UPDATE alembic_version SET version_num = '9999'")
    assert schema_state(db) == "newer"


def test_a_newer_database_is_refused_at_startup_and_left_untouched(tmp_path: Path) -> None:
    data = panel(tmp_path)
    sql(data / "hivora.db", "UPDATE alembic_version SET version_num = '9999'")
    before = (data / "hivora.db").read_bytes()
    with pytest.raises(SchemaTooNewError, match=r"newer version of Hivora.*9999"):
        build(data)
    assert (data / "hivora.db").read_bytes() == before
    assert archives(data) == []


def test_the_archive_holds_the_database_the_key_and_the_launch_options(tmp_path: Path) -> None:
    data = panel(tmp_path)
    alone = backup_panel(data)  # no install.env yet
    with tarfile.open(alone) as tar:
        assert sorted(tar.getnames()) == ["hivora.db", "secret.key"]
    (data / "install.env").write_text("HIVORA_ACCESS=vpn+lan\n")
    path = backup_panel(data)
    assert path.parent == data / "backups" / "_hivora" and "-r0021" in path.name
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    out = tmp_path / "out"
    with tarfile.open(path) as tar:
        assert sorted(tar.getnames()) == ["hivora.db", "install.env", "secret.key"]
        tar.extractall(out, filter="data")
    assert sql(out / "hivora.db", "SELECT key FROM setting") == [("language",)]
    assert (out / "secret.key").read_bytes() == b"k" * 32
    assert not list(path.parent.glob("tmp*"))  # the database copy is gone
    with pytest.raises(FileNotFoundError):
        backup_panel(tmp_path / "nothing")


def test_only_the_five_newest_archives_are_kept(tmp_path: Path) -> None:
    data = panel(tmp_path)
    start = datetime(2026, 10, 15, tzinfo=UTC)
    made = [backup_panel(data, start + timedelta(hours=i)) for i in range(7)]
    assert archives(data) == made[2:]


def test_a_pending_migration_backs_the_panel_up_first(tmp_path: Path) -> None:
    data = panel(tmp_path, "0020")
    build(data)
    (archive,) = archives(data)
    assert "-r0020" in archive.name  # the database as it was, before 0021
    assert schema_state(data / "hivora.db") == "current"
    build(data)  # up to date: nothing more
    assert archives(data) == [archive]


def test_a_fresh_install_makes_no_backup(tmp_path: Path) -> None:
    data = tmp_path / "data"
    build(data)
    assert schema_state(data / "hivora.db") == "current" and archives(data) == []


def test_backup_self_prints_the_archive(tmp_path: Path) -> None:
    data = panel(tmp_path)
    env = {**os.environ, "HIVORA_DATA_DIR": str(data)}
    done = subprocess.run([sys.executable, "-m", "hivora", "backup-self"], env=env,
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert Path(done.stdout.strip()) == archives(data)[0]
    wrong = subprocess.run([sys.executable, "-m", "hivora", "backup"], env=env,
                           capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert wrong.returncode == 1 and "usage" in wrong.stderr
