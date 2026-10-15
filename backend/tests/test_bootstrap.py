import io
import logging
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import API, STRONG

from hivora.auth.initial import ALPHABET, random_password
from hivora.auth.passwords import check_password_policy
from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime
from hivora.system.bootstrap import bootstrap, reset_admin_password


def settings_in(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                    catalog_dir=Path(__file__).parents[2] / "templates",
                    dev_insecure_cookies=True)  # fmt: skip


@contextmanager
def panel(settings: Settings) -> Iterator[TestClient]:
    """The server on this data folder (it creates admin/admin if nobody exists yet)."""
    runtime = Runtime.build(settings, gateway=FakeDockerGateway())
    with TestClient(create_app(runtime=runtime)) as c:
        yield c


def logs_in(c: TestClient, password: str, username: str = "admin") -> int:
    r = c.post(f"{API}/auth/login", json={"username": username, "password": password})
    if r.status_code == 200:
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r.status_code


def first_start(c: TestClient) -> bool:
    value: bool = c.get(f"{API}/system/health").json()["first_start"]
    return value


def hash_of(settings: Settings, username: str = "admin") -> str:
    with closing(sqlite3.connect(settings.db_path)) as conn:
        row = conn.execute("SELECT password_hash FROM user WHERE username = ?", (username,))
        return str(row.fetchone()[0])


def test_a_new_panel_gets_admin_with_a_random_password_to_change(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    out = bootstrap(settings)
    assert out["ADMIN"] == "created" and out["ADMIN_USER"] == "admin"
    with panel(settings) as c:
        assert not first_start(c)  # no "admin / admin" hint on the login page
        assert logs_in(c, "admin") == 401
        assert logs_in(c, out["ADMIN_PASSWORD"]) == 200
        assert c.get(f"{API}/apps").status_code == 403  # password change first
        r = c.post(f"{API}/auth/password",
                   json={"current": out["ADMIN_PASSWORD"], "new": STRONG})  # fmt: skip
        assert r.status_code == 204 and c.get(f"{API}/apps").status_code == 200


def test_bootstrap_again_keeps_the_account(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    bootstrap(settings)
    before = hash_of(settings)
    assert bootstrap(settings) == {"ADMIN": "kept"}  # no password shown
    assert hash_of(settings) == before


def test_admin_admin_never_changed_is_secured(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    with panel(settings) as c:  # started by hand (compose.yaml): admin/admin
        assert first_start(c)
    out = bootstrap(settings)
    assert out["ADMIN"] == "secured"
    with panel(settings) as c:
        assert not first_start(c)
        assert logs_in(c, "admin") == 401
        assert logs_in(c, out["ADMIN_PASSWORD"]) == 200


def test_an_account_already_set_up_is_left_alone(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    with panel(settings) as c:
        assert logs_in(c, "admin") == 200
        c.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG})
    assert bootstrap(settings) == {"ADMIN": "kept"}
    with panel(settings) as c:
        assert logs_in(c, STRONG) == 200
        r = c.post(f"{API}/users", json={"username": "alice", "password": "alice-pass-123",
                                         "role": "viewer"})  # fmt: skip
        assert r.status_code == 201, r.text
    assert bootstrap(settings) == {"ADMIN": "kept"}


def test_the_password_never_reaches_the_logs_nor_the_database(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    stream = io.StringIO()  # every log record, whatever pytest's logging plugin does
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    level, root.level = root.level, logging.DEBUG
    try:
        created = bootstrap(settings)["ADMIN_PASSWORD"]
        reset = reset_admin_password(settings)["ADMIN_PASSWORD"]
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    text = stream.getvalue()
    assert "initial account created: admin (password shown by the installer)" in text
    for secret in (created, reset):
        assert secret not in text
        for path in settings.data_dir.glob("hivora.db*"):
            assert secret.encode() not in path.read_bytes()


def test_random_passwords_are_long_unambiguous_and_accepted() -> None:
    group = f"[{ALPHABET}]{{5}}"
    seen = set()
    for _ in range(200):
        password = random_password()
        assert re.fullmatch(f"{group}(-{group}){{3}}", password)
        check_password_policy(password, "admin")
        seen.add(password)
    assert len(seen) == 200
    assert not set("0o1li") & set(ALPHABET)


def test_reset_admin_password_gives_a_new_one_to_change(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    with panel(settings) as c:
        assert logs_in(c, "admin") == 200
        c.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG})
    out = reset_admin_password(settings)
    assert out["ADMIN"] == "reset" and out["ADMIN_USER"] == "admin"
    with panel(settings) as c:
        assert not first_start(c)
        assert logs_in(c, STRONG) == 401
        assert logs_in(c, out["ADMIN_PASSWORD"]) == 200
        assert c.get(f"{API}/apps").status_code == 403  # to change first


def run(settings: Settings, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HIVORA_DATA_DIR": str(settings.data_dir)}
    return subprocess.run([sys.executable, "-m", "hivora", *args], env=env,  # noqa: S603
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


def lines(done: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


def test_the_commands_print_key_value_lines(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    created = run(settings, "bootstrap")
    assert created.returncode == 0, created.stderr
    assert lines(created)["ADMIN"] == "created" and lines(created)["ADMIN_PASSWORD"]
    assert lines(run(settings, "bootstrap")) == {"ADMIN": "kept"}
    reset = run(settings, "reset-admin-password")
    assert reset.returncode == 0 and lines(reset)["ADMIN"] == "reset"
    assert lines(reset)["ADMIN_PASSWORD"] != lines(created)["ADMIN_PASSWORD"]
    unknown = run(settings, "reset-admin-password", "nobody")
    assert unknown.returncode == 1 and "error:" in unknown.stderr and unknown.stdout == ""


def test_bootstrap_refuses_a_newer_database(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    bootstrap(settings)
    with closing(sqlite3.connect(settings.db_path)) as conn, conn:
        conn.execute("UPDATE alembic_version SET version_num = '9999'")
    done = run(settings, "bootstrap")
    assert done.returncode == 1 and "newer version of Hivora" in done.stderr
    assert done.stdout == ""
