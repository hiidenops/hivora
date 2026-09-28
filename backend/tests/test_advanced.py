from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import API, admin, code, wait_job

from hivora.apps.compose_check import problems
from hivora.core.errors import ValidationError
from hivora.templates.overrides import Overrides


def test_overrides_are_checked_and_bounded() -> None:
    ok = Overrides.model_validate({"services": {"server": {
        "env": {"LOG_LEVEL": "warn"}, "cpus": 1.5, "memory": "2g", "restart": "always",
        "ports": [{"container": 3012, "host": 3012}],
        "volumes": [{"name": "extra", "target": "/extra", "read_only": True}],
    }}})  # fmt: skip
    assert ok.of("server") is not None and ok.of("db") is None
    for bad in ({"env": {"1BAD": "x"}}, {"memory": "lots"}, {"cpus": 0},
                {"volumes": [{"name": "../x", "target": "/x"}]},
                {"volumes": [{"name": "x", "target": "/a/../../etc"}]}):  # fmt: skip
        with pytest.raises(ValueError):
            Overrides.model_validate({"services": {"server": bad}})


def test_compose_checks() -> None:
    roots = [Path("/srv/hivora/web"), Path("/opt/hivora/data/apps/web")]
    labels = {"io.hivora.app": "web"}
    good = {"name": "web", "services": {"app": {
        "image": "nginx", "labels": labels, "cap_add": ["NET_ADMIN"],
        "volumes": [{"type": "bind", "source": "/srv/hivora/web/html", "target": "/usr/share"},
                    {"type": "volume", "source": "cache", "target": "/cache"}],
    }}}  # fmt: skip
    assert problems(good, "web", roots) == []
    bad = {"name": "other", "services": {"app": {
        "image": "x", "privileged": True, "network_mode": "host", "pid": "host",
        "cap_add": ["SYS_ADMIN"], "devices": ["/dev/sda"], "sysctls": {"kernel.shmmax": 1},
        "security_opt": ["apparmor=unconfined"],
        "volumes": [{"type": "bind", "source": "/var/run/docker.sock", "target": "/s"},
                    {"type": "bind", "source": "/srv/hivora/web/../other", "target": "/o"}],
    }}, "volumes": {"root": {"driver_opts": {"device": "/", "o": "bind"}}}}  # fmt: skip
    found = "\n".join(problems(bad, "web", roots))
    for word in ("project name", "privileged", "network_mode", "pid", "SYS_ADMIN", "devices",
                 "kernel.shmmax", "unconfined", "docker.sock", "/srv/hivora/web/../other",
                 "io.hivora.app", "device /"):  # fmt: skip
        assert word in found, word


def test_advanced_settings_and_hand_written_compose(client: Any) -> None:
    admin(client)
    body = {"template": "vaultwarden", "name": "Coffre", "inputs": {"web_port": 8090}}
    deployed = client.post(f"{API}/apps", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]

    settings = client.get(f"{API}/apps/{app_id}/settings").json()
    assert settings["services"] == ["server"] and settings["overrides"] == {"services": {}}
    overrides = {"services": {"server": {
        "env": {"LOG_LEVEL": "warn"}, "memory": "512m", "cpus": 0.5, "restart": "always",
        "ports": [{"container": 3012, "host": 3012}],
        "volumes": [{"name": "extra", "target": "/extra"}],
    }}}  # fmt: skip
    change = {"inputs": settings["values"], "overrides": overrides}
    job = client.put(f"{API}/apps/{app_id}/settings", json=change).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    svc = compose["services"]["server"]
    assert svc["environment"]["LOG_LEVEL"] == "warn" and svc["mem_limit"] == "512m"
    assert svc["cpus"] == 0.5 and svc["restart"] == "always"
    assert {p["target"] for p in svc["ports"]} == {80, 3012}
    assert any(v["target"] == "/extra" and v["source"].endswith("/coffre/extra")
               for v in svc["volumes"])  # fmt: skip
    # A later settings change keeps them.
    job = client.put(f"{API}/apps/{app_id}/settings", json={"inputs": settings["values"]}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    kept = client.get(f"{API}/apps/{app_id}/settings").json()["overrides"]
    assert kept == Overrides.model_validate(overrides).model_dump()
    dup = {"services": {"server": {"ports": [{"container": 80, "host": 9000}]}}}
    refused = client.post(f"{API}/apps/{app_id}/settings/plan",
                          json={"inputs": settings["values"], "overrides": dup})  # fmt: skip
    assert refused.status_code == 422

    # Hand-written compose: checked, then applied as a revision of its own.
    text = client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"]
    evil = text.replace("restart: always", "restart: always\n    privileged: true")
    plan = client.post(f"{API}/apps/{app_id}/compose/plan", json={"compose_yaml": evil}).json()
    assert any("privileged" in p for p in plan["problems"])
    rejected = client.put(f"{API}/apps/{app_id}/compose", json={"compose_yaml": evil})
    assert rejected.status_code == 422 and code(rejected) == "compose_rejected"
    edited = text.replace("LOG_LEVEL: warn", "LOG_LEVEL: debug")
    plan = client.post(f"{API}/apps/{app_id}/compose/plan", json={"compose_yaml": edited}).json()
    assert plan["problems"] == [] and "+      LOG_LEVEL: debug" in plan["diff"]
    job = client.put(f"{API}/apps/{app_id}/compose", json={"compose_yaml": edited}).json()
    assert wait_job(client, job["id"])["status"] == "succeeded"
    assert "LOG_LEVEL: debug" in client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"]
    assert client.get(f"{API}/apps/{app_id}/settings").json()["custom_compose"] is True
    back = client.post(f"{API}/apps/{app_id}/settings/plan", json={"inputs": settings["values"]})
    assert back.json()["replaces_custom"] is True


def test_compiler_rejects_unknown_service() -> None:
    from hivora.templates import AppContext, HostInfo, compile_template
    from hivora.templates.catalog import Catalog
    from hivora.templates.forms import validate_inputs

    catalog = Catalog()
    catalog.load_directory(Path(__file__).parents[2] / "templates")
    t = catalog.get("vaultwarden").template
    form = validate_inputs(t, {}, {"host": {}, "app": {}})
    with pytest.raises(ValidationError):
        compile_template(t, AppContext("coffre", "Coffre", 1), HostInfo(), form, Path("/srv"),
                         Overrides.model_validate({"services": {"nope": {"cpus": 1}}}))  # fmt: skip
