"""A public panel (HIVORA_ACCESS=public): every account needs TOTP before anything else."""

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pyotp
import pytest
from fastapi.testclient import TestClient
from helpers import API, STRONG, admin, code, login, other_user
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

import hivora.realtime.ws as ws_module
from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime

FAKE = [sys.executable, str(Path(__file__).parent / "fake_compose.py")]


def settings_for(tmp_path: Path, access: str) -> Settings:
    return Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                    catalog_dir=Path(__file__).parents[2] / "templates", access=access,  # type: ignore[arg-type]
                    dev_insecure_cookies=True, puid=os.getuid(), pgid=os.getgid())  # fmt: skip


@contextmanager
def panel(tmp_path: Path, access: str = "public") -> Iterator[TestClient]:
    runtime = Runtime.build(settings_for(tmp_path, access), gateway=FakeDockerGateway(),
                            compose_cmd=FAKE)  # fmt: skip
    with TestClient(create_app(runtime=runtime)) as c:
        yield c


def enroll(c: TestClient) -> tuple[str, list[str]]:
    """TOTP set up for the signed-in account: (secret, recovery codes)."""
    secret = c.post(f"{API}/auth/totp/enroll").json()["secret"]
    r = c.post(f"{API}/auth/totp/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    codes: list[str] = r.json()["recovery_codes"]
    return secret, codes


def blocked(r: Any) -> bool:
    return bool(r.status_code == 403 and code(r) == "totp_setup_required")


def test_access_defaults_to_lan_and_rejects_unknown_values(tmp_path: Path) -> None:
    assert Settings().access == "lan"
    with pytest.raises(ValidationError):
        settings_for(tmp_path, "internet")
    with panel(tmp_path, "lan") as c:  # as before: no TOTP needed
        admin(c)
        assert c.get(f"{API}/apps").status_code == 200


def test_a_public_panel_lets_only_the_setup_through_until_totp(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        login(c, "admin", "admin")
        r = c.get(f"{API}/apps")
        assert r.status_code == 403 and code(r) == "password_change_required"  # first
        assert (
            c.post(f"{API}/auth/password", json={"current": "admin", "new": STRONG}).status_code
            == 204
        )
        for path in ("/apps", "/auth/sessions", "/zones", "/users", "/jobs", "/topology"):
            assert blocked(c.get(f"{API}{path}")), path
        assert blocked(c.post(f"{API}/zones", json={"name": "Jeux"}))
        assert c.get(f"{API}/system/health").status_code == 200
        assert c.get(f"{API}/auth/me").json()["totp_enabled"] is False
        enroll(c)  # same session: no new login
        assert c.get(f"{API}/apps").status_code == 200
        assert c.get(f"{API}/auth/me").json()["totp_enabled"] is True
        assert c.post(f"{API}/auth/logout").status_code == 204


def test_every_role_needs_totp_and_comes_before_the_role_check(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        enroll(c)
        r = c.post(f"{API}/users", json={"username": "victor", "password": "victor-pass-1",
                                         "role": "viewer"})  # fmt: skip
        assert r.status_code == 201, r.text
        with other_user(c) as viewer:
            login(viewer, "victor", "victor-pass-1")
            viewer.post(f"{API}/auth/password",
                        json={"current": "victor-pass-1", "new": "victor-pass-2"})  # fmt: skip
            assert blocked(viewer.get(f"{API}/apps"))
            assert blocked(viewer.get(f"{API}/users"))  # not insufficient_role: TOTP first
            enroll(viewer)
            assert viewer.get(f"{API}/apps").status_code == 200
            assert code(viewer.get(f"{API}/users")) == "insufficient_role"


def test_totp_cannot_be_turned_off_on_a_public_panel(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        enroll(c)
        r = c.post(f"{API}/auth/totp/disable", json={"password": STRONG})
        assert r.status_code == 409 and code(r) == "totp_mandatory"
        assert c.get(f"{API}/auth/me").json()["totp_enabled"] is True
    with panel(tmp_path / "lan", "lan") as c:  # a LAN panel: as before
        admin(c)
        enroll(c)
        assert c.post(f"{API}/auth/totp/disable", json={"password": STRONG}).status_code == 204


def test_the_websocket_waits_for_totp(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        with pytest.raises(WebSocketDisconnect) as closed:  # refused at once, not later
            c.websocket_connect("/ws").__enter__()
        assert closed.value.code == 4403
        enroll(c)
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"op": "subscribe", "channel": "nope"})  # accepted: it answers
            assert ws.receive_json()


def test_an_open_websocket_closes_once_totp_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws_module, "REVALIDATE_EVERY_S", 0.2)
    with panel(tmp_path) as c:
        admin(c)
        enroll(c)
        with c.websocket_connect("/ws") as ws:
            with closing(sqlite3.connect(tmp_path / "data" / "hivora.db")) as db, db:
                db.execute("UPDATE user SET totp_enabled = 0")  # TOTP gone, session kept
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    ws.receive_json()
        assert closed.value.code == 4403


def test_a_session_from_a_lan_panel_is_held_once_the_panel_turns_public(tmp_path: Path) -> None:
    with panel(tmp_path, "lan") as c:
        admin(c)
        cookies, csrf = dict(c.cookies), c.headers["X-CSRF-Token"]
        assert c.get(f"{API}/apps").status_code == 200
    with panel(tmp_path, "public") as c:  # install.sh --access public: same data
        c.cookies.update(cookies)
        c.headers["X-CSRF-Token"] = csrf
        assert c.get(f"{API}/auth/me").status_code == 200  # still signed in
        assert blocked(c.get(f"{API}/apps"))
        enroll(c)
        assert c.get(f"{API}/apps").status_code == 200


def test_an_admin_reset_ends_the_sessions_and_asks_for_totp_again(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        enroll(c)
        c.post(f"{API}/users", json={"username": "olive", "password": "olive-pass-1",
                                     "role": "operator"})  # fmt: skip
        users = {u["username"]: u["id"] for u in c.get(f"{API}/users").json()}
        with other_user(c) as olive:
            login(olive, "olive", "olive-pass-1")
            olive.post(
                f"{API}/auth/password", json={"current": "olive-pass-1", "new": "olive-pass-2"}
            )
            secret, _ = enroll(olive)
            cookies, csrf = dict(olive.cookies), olive.headers["X-CSRF-Token"]
        assert c.post(f"{API}/users/{users['olive']}/totp/reset").status_code == 204
        with other_user(c) as olive:
            olive.cookies.update(cookies)
            olive.headers["X-CSRF-Token"] = csrf
            assert olive.get(f"{API}/auth/me").status_code == 401  # its sessions ended
            login(olive, "olive", "olive-pass-2")  # no TOTP any more: a password is enough
            assert blocked(olive.get(f"{API}/apps"))  # ...to set it up again
            c.app.state.runtime.auth.totp._used.clear()  # type: ignore[attr-defined]  # next 30 s step
            assert enroll(olive)[0] != secret  # a new secret
            assert olive.get(f"{API}/apps").status_code == 200


def test_a_recovery_code_signs_in_on_a_public_panel(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        _, codes = enroll(c)
        with other_user(c) as again:
            r = again.post(f"{API}/auth/login", json={"username": "admin", "password": STRONG})
            assert r.status_code == 401 and code(r) == "totp_required"
            login(again, "admin", STRONG, totp_code=codes[0])
            assert again.get(f"{API}/apps").status_code == 200


def test_reset_totp_on_the_machine(tmp_path: Path) -> None:
    with panel(tmp_path) as c:
        admin(c)
        enroll(c)
        cookies, csrf = dict(c.cookies), c.headers["X-CSRF-Token"]
    env = {**os.environ, "HIVORA_DATA_DIR": str(tmp_path / "data")}
    run = [sys.executable, "-m", "hivora", "reset-totp"]
    done = subprocess.run(run, env=env, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["TOTP=reset", "TOTP_USER=admin"]
    with panel(tmp_path) as c:
        c.cookies.update(cookies)
        c.headers["X-CSRF-Token"] = csrf
        assert c.get(f"{API}/auth/me").status_code == 401  # sessions ended
        login(c, "admin", STRONG)  # the password alone, then set TOTP up again
        assert blocked(c.get(f"{API}/apps"))
    unknown = subprocess.run([*run, "nobody"], env=env, capture_output=True, text=True,  # noqa: S603
                             timeout=60, check=False)  # fmt: skip
    assert unknown.returncode == 1 and "error:" in unknown.stderr
