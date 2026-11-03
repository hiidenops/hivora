"""TeamSpeak 3: its ServerQuery spoken in the container (exec + stdin), and its fail2ban jail."""

import time
from pathlib import Path
from typing import Any

import pytest
from fake_teamspeak import FakeTeamSpeak
from fastapi.testclient import TestClient
from helpers import API, admin, code, spy_events, wait_job

from hivora.docker_gateway import ContainerInfo, ContainerState
from hivora.hostfw.service import HOST
from hivora.teamspeak import jail as j
from hivora.teamspeak import query as q
from hivora.teamspeak.service import parse_log


def test_escaping_keeps_every_value_in_its_own_command() -> None:
    hostile = "a b|c\nquit\\/"
    line = q.command("gm", msg=hostile)
    assert line == "gm msg=a\\sb\\pc\\nquit\\\\\\/"
    assert "\n" not in line and " " not in line.removeprefix("gm ")
    assert q.unescape(line.removeprefix("gm msg=")) == hostile
    assert q.command("banadd", "-x", ip="1.2.3.4", banreason=None) == "banadd ip=1.2.3.4 -x"


def test_answers_of_a_real_session() -> None:
    out = (
        'TS3\n\rWelcome to the TeamSpeak 3 ServerQuery interface, type "help".\n\r'
        "error id=0 msg=ok\n\rerror id=0 msg=ok\n\r"
        "clid=1 client_nickname=serveradmin client_type=1|clid=5 client_nickname=A\\sB "
        "client_type=0 client_country\n\rerror id=0 msg=ok\n\r"
        "error id=1281 msg=database\\sempty\\sresult\\sset\n\rerror id=0 msg=ok\n\r"
    )
    got = q.answers(out)
    assert [a.id for a in got] == [0, 0, 0, 1281, 0]
    assert got[2].rows[1] == {
        "clid": "5",
        "client_nickname": "A B",
        "client_type": "0",
        "client_country": "",
    }
    assert got[3].rows == []


def test_connections_read_from_the_server_log() -> None:
    ban = (
        "2026-11-03 12:51:17.0|INFO |VirtualServer |1  |ban added "
        "reason='spam' ip='203.0.113.9' bantime=3600 by client 'x'(id:1)"
    )
    log = [*FakeTeamSpeak().log, ban]
    got = parse_log(log)
    assert [(e.event, e.name, e.ip) for e in got] == [
        ("connected", "Alice Liddell", "198.51.100.4"),
        ("disconnected", "Bob", None),
        ("banned", None, "203.0.113.9"),
    ]  # the query client (Hivora itself) is left out


def test_filter_matches_the_lines_of_a_real_server(tmp_path: Path) -> None:
    import re

    line = (
        "|INFO    |Query         |   |query from 3 127.0.0.1:40419 attempted to login with "
        'account "serveradmin" and failed!'
    )
    pattern = j.FAILREGEX.replace("<ADDR>", r"(?P<ip>\S+)")
    assert (m := re.match(pattern, line)) and m["ip"] == "127.0.0.1"
    assert not re.match(pattern, "|INFO    |Query         |   |query client connected 'x'")


def test_jail_file_generated_from_validated_values() -> None:
    text = j.jail_config({"ts": {"maxretry": 3, "bantime": "1d"}}, Path("/srv/hivora"))
    assert "[hivora-teamspeak-ts]" in text
    assert "logpath = /srv/hivora/ts/data/logs/ts3server_0.log" in text
    assert "chain=DOCKER-USER" in text and "maxretry = 3" in text and "findtime = 10m" in text
    with pytest.raises(Exception, match="invalid app name"):
        j.jail_config({"x]\n[sshd": {}}, Path("/srv/hivora"))
    with pytest.raises(Exception, match="invalid bantime"):
        j.check({"bantime": "1h; rm"})


def _deploy(client: TestClient) -> tuple[int, Any, FakeTeamSpeak]:
    admin(client)
    body = {"template": "teamspeak", "name": "voice", "inputs": {"eula": True}}
    deployed = client.post(f"{API}/apps", json=body).json()
    wait_job(client, deployed["job"]["id"])
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    gw = runtime.gateway
    ts = FakeTeamSpeak()
    ts.install(gw)
    gw.put(
        ContainerInfo(
            id="ts1",
            name="voice-server-1",
            image="teamspeak",
            state=ContainerState.RUNNING,
            labels={"io.hivora.app": "voice", "com.docker.compose.service": "server"},
        ),
        "start",
    )
    deadline = time.monotonic() + 3
    while runtime.state.store.app("voice").status.value != "healthy":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    return deployed["app"]["id"], runtime, ts


def test_the_query_password_is_generated_and_travels_on_stdin(client: TestClient) -> None:
    app_id, runtime, ts = _deploy(client)
    env = (Path(runtime.settings.apps_dir) / "voice" / ".env").read_text()
    password = env.split("HV_SECRET_QUERY_PASSWORD='")[1].split("'")[0]
    assert len(password) == 24
    ts.password = password
    assert client.get(f"{API}/apps/{app_id}/teamspeak").json()["name"] == "TeamSpeak ]I[ Server"
    sent = runtime.gateway.exec_calls[-1]
    assert password not in " ".join(sent)  # in Docker's events: the command line only
    assert ts.received[0] == f"login client_login_name=serveradmin client_login_password={password}"


def test_server_managed_from_the_panel(client: TestClient) -> None:
    app_id, _, ts = _deploy(client)
    events, undo = spy_events(client)
    base = f"{API}/apps/{app_id}/teamspeak"
    assert client.get(f"{API}/apps/{app_id}/game/players").json() == {
        "running": True,
        "online": 1,
        "max": 32,
        "names": ["Alice Liddell"],
    }
    listed = client.get(f"{API}/apps").json()
    assert next(a for a in listed if a["id"] == app_id)["players"] is True
    assert client.get(f"{base}/clients").json() == [
        {
            "clid": 5,
            "name": "Alice Liddell",
            "ip": "198.51.100.4",
            "country": "FR",
            "connected_at": 1793709000,
            "idle_s": 4,
        }
    ]
    assert [e["event"] for e in client.get(f"{base}/history").json()] == [
        "connected",
        "disconnected",
    ]

    # Bans: a connected client, an address; a bad address is refused before the server.
    assert client.post(f"{base}/bans", json={"clid": 5, "minutes": 60}).status_code == 204
    assert (
        client.post(f"{base}/bans", json={"ip": "203.0.113.9", "reason": "spam"}).status_code == 204
    )
    assert code(client.post(f"{base}/bans", json={"ip": "1.2.3.4 x"})) == "validation_error"
    bans = client.get(f"{base}/bans").json()
    assert [(b["ip"], b["duration_s"]) for b in bans] == [
        ("198.51.100.4", 3600),
        ("203.0.113.9", 0),
    ]
    assert client.delete(f"{base}/bans/{bans[0]['id']}").status_code == 204
    assert len(client.get(f"{base}/bans").json()) == 1

    assert client.post(f"{base}/clients/5/kick", json={"reason": "bye"}).status_code == 204
    assert client.post(f"{base}/message", json={"text": "Maintenance à 22 h"}).status_code == 204
    assert ts.messages == ["Maintenance à 22 h"]

    settings = {"name": "Les copains", "welcome": "Salut", "max_clients": 16, "log_clients": True}
    assert client.put(base, json=settings).status_code == 204
    assert client.put(base, json={**settings, "max_clients": 64}).status_code == 422
    info = client.get(base).json()
    assert (info["name"], info["max_clients"], info["log_clients"]) == ("Les copains", 16, True)

    assert client.put(f"{base}/password", json={"password": "s3cret pass"}).status_code == 204
    assert client.get(base).json()["password"] is True
    assert client.put(f"{base}/password", json={"password": ""}).status_code == 204
    assert client.get(base).json()["password"] is False

    # The admin key: the unused ones deleted, a new one shown once, never on the bus.
    assert client.get(f"{base}/admin-keys").json() == [
        {"created": 1793709499, "description": "default key"}
    ]
    key = client.post(f"{base}/admin-keys").json()["key"]
    assert ts.keys == [key] and key.startswith("newkey")
    undo()
    topics = [t for t, _ in events]
    assert {
        "teamspeak.banned",
        "teamspeak.unbanned",
        "teamspeak.kicked",
        "teamspeak.message_sent",
        "teamspeak.settings_changed",
        "teamspeak.password_changed",
        "teamspeak.admin_key_renewed",
    } <= set(topics)
    assert "s3cret" not in repr(events) and key not in repr(events)


def test_refused_when_stopped_or_not_teamspeak(client: TestClient) -> None:
    admin(client)
    body = {"template": "teamspeak", "name": "quiet", "inputs": {"eula": True}}
    deployed = client.post(f"{API}/apps", json=body).json()
    wait_job(client, deployed["job"]["id"])
    stopped = client.get(f"{API}/apps/{deployed['app']['id']}/teamspeak/clients")
    assert stopped.status_code == 409 and code(stopped) == "server_not_running"
    refused = client.post(
        f"{API}/apps", json={"template": "teamspeak", "name": "nolicense", "inputs": {}}
    )
    assert refused.status_code == 422


def test_jail_written_through_the_agent(client: TestClient) -> None:
    app_id, runtime, _ = _deploy(client)
    gw = runtime.gateway
    base = f"{API}/apps/{app_id}/teamspeak/jail"
    assert client.get(base).json()["agent"] is False
    client.put(f"{API}/host-firewall/agent", json={"enabled": True})
    rules: dict[str, Any] = {"maxretry": 3, "findtime": "10m", "bantime": "1h"}
    on = {"enabled": True, "settings": rules}
    assert code(client.put(base, json=on)) == "teamspeak_log_missing"  # never started

    logs = Path(runtime.settings.volumes_root) / "voice" / "data" / "logs"
    logs.mkdir(parents=True)
    (logs / "ts3server_0.log").write_text("")
    gw.exec_results[
        " ".join([*HOST, "fail2ban-regex", str(logs / "ts3server_0.log"), j.FILTER_FILE])
    ] = (0, "Lines: 4 lines, 0 ignored, 2 matched, 2 missed")
    assert client.put(base, json=on).status_code == 204
    writes = [c for c in gw.exec_calls if c[len(HOST) : len(HOST) + 2] == ["sh", "-c"]]
    content = writes[-1][-1]
    assert writes[-1][len(HOST) + 2].endswith(j.JAIL_FILE) and "[hivora-teamspeak-voice]" in content
    assert [*HOST, "fail2ban-client", "reload"] in gw.exec_calls
    state = client.get(base).json()
    assert (state["enabled"], state["settings"]["maxretry"], state["matched"]) == (True, 3, 2)

    # fail2ban refuses it: the previous file is put back.
    gw.exec_results[" ".join([*HOST, "fail2ban-client", "reload"])] = (255, "ERROR bad jail")
    refused = client.put(base, json={**on, "settings": {**rules, "maxretry": 4}})
    assert refused.status_code == 409
    gw.exec_results.pop(" ".join([*HOST, "fail2ban-client", "reload"]))
    assert client.get(base).json()["settings"]["maxretry"] == 3

    # The app removed: its jail goes.
    calls = len(gw.exec_calls)
    removed = client.delete(f"{API}/apps/{app_id}?remove_data=true").json()
    wait_job(client, removed["id"])
    deadline = time.monotonic() + 3
    while not any(
        c[len(HOST) + 2].endswith(j.JAIL_FILE) and "voice" not in c[-1]
        for c in gw.exec_calls[calls:]
        if len(c) > len(HOST) + 2
    ):
        assert time.monotonic() < deadline
        time.sleep(0.02)
