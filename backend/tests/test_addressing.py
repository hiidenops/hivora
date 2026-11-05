"""Static addressing: the rules (pure) and the plan as apps are deployed, moved, removed."""

from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from helpers import API, admin, code, wait_job

from hivora.addressing import plan as p
from hivora.addressing.plan import Taken
from hivora.core.errors import ConflictError, ValidationError

LAN = Taken("192.168.1.0/24", "host:lan")


# -- the rules ---------------------------------------------------------------------------


def test_a_subnet_by_hand_is_private_sized_and_free() -> None:
    zone = Taken("10.100.0.0/24", "zone:media")
    assert str(p.check_subnet("10.100.1.0/24", [zone, LAN])) == "10.100.1.0/24"
    for bad in ["8.8.8.0/24", "10.100.1.5/24", "10.0.0.0/8", "10.100.1.0/30", "not a net"]:
        with pytest.raises(ValidationError) as err:
            p.check_subnet(bad, [zone])
        assert err.value.code == "subnet_invalid"
    with pytest.raises(ConflictError) as hit:
        p.check_subnet("192.168.0.0/16", [zone, LAN])  # over the host's LAN
    assert hit.value.code == "subnet_overlap" and hit.value.details["owner"] == "host:lan"


def test_the_range_skips_what_is_taken() -> None:
    assert str(p.pick_range([])) == "10.100.0.0/16"
    assert str(p.pick_range([Taken("10.100.5.0/24", "host:eth1")])) == "10.101.0.0/16"
    hivora = p.net("10.100.0.0/16")
    assert str(p.zones_half(hivora)) == "10.100.0.0/17"
    assert str(p.apps_half(hivora)) == "10.100.128.0/17"


def test_next_to_the_vpn_and_the_next_free_address() -> None:
    assert str(p.next_to("10.8.0.0/24", [])) == "10.8.1.0/24"
    assert str(p.next_to("10.8.0.0/24", [Taken("10.8.1.0/24", "zone:a")])) == "10.8.2.0/24"
    zone = p.net("10.100.0.0/24")
    assert p.free_address(zone, [], p.FIRST_HOST) == "10.100.0.10"
    assert p.free_address(zone, ["10.100.0.10"], p.FIRST_HOST) == "10.100.0.11"
    with pytest.raises(ConflictError):
        p.free_address(p.net("10.100.0.0/30"), ["10.100.0.2"])
    assert p.check_address("10.100.0.3", zone, {}) == "10.100.0.3"
    for bad in ["10.100.0.1", "10.100.0.255", "10.100.1.3", "nope"]:  # gateway, broadcast...
        with pytest.raises(ValidationError):
            p.check_address(bad, zone, {})
    with pytest.raises(ConflictError) as taken:
        p.check_address("10.100.0.10", zone, {"10.100.0.10": "jellyfin/server"})
    assert taken.value.code == "ip_taken"


def test_a_zone_without_a_shared_network_cuts_its_24_in_16_apps() -> None:
    zone = p.net("10.100.3.0/24")
    first = p.free_subnet([zone], p.APP_PREFIX, [])
    second = p.free_subnet([zone], p.APP_PREFIX, [Taken(str(first), "app:a")])
    assert (str(first), str(second)) == ("10.100.3.0/28", "10.100.3.16/28")
    full = [Taken(str(s), "app") for s in zone.subnets(new_prefix=p.APP_PREFIX)]
    assert p.free_subnet([zone], p.APP_PREFIX, full) is None


# -- the plan, as apps live --------------------------------------------------------------


def _compose(c: TestClient, app_id: int) -> dict[str, Any]:
    return yaml.safe_load(c.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])  # type: ignore[no-any-return]


def _deploy(c: TestClient, name: str, port: int, zone: str | None = None) -> int:
    body = {"template": "nginx", "name": name, "inputs": {"web_port": port}, "zone": zone}
    created = c.post(f"{API}/apps", json=body).json()
    assert wait_job(c, created["job"]["id"])["status"] == "succeeded"
    return int(created["app"]["id"])


def _own(compose: dict[str, Any]) -> str:
    """The subnet of the app's own network."""
    return str(compose["networks"]["default"]["ipam"]["config"][0]["subnet"])


def _ip(compose: dict[str, Any], network: str = "zone") -> str:
    return str(compose["services"]["server"]["networks"][network]["ipv4_address"])


def test_addresses_are_fixed_kept_and_given_again_once_free(client: TestClient) -> None:
    admin(client)
    zone = client.post(f"{API}/zones", json={"name": "Media", "color": "#d97706",
                                             "network_mode": "shared"}).json()  # fmt: skip
    a = _deploy(client, "Alpha", 8401, zone["slug"])
    b = _deploy(client, "Beta", 8402, zone["slug"])
    assert (_ip(_compose(client, a)), _ip(_compose(client, b))) == ("10.100.0.10", "10.100.0.11")
    assert _own(_compose(client, a)) == "10.100.128.0/28"
    assert _own(_compose(client, b)) == "10.100.128.16/28"
    # A settings change (new revision) keeps them.
    upd = client.put(f"{API}/apps/{a}/settings", json={"inputs": {"web_port": 8411}}).json()
    assert wait_job(client, upd["id"])["status"] == "succeeded"
    assert _ip(_compose(client, a)) == "10.100.0.10"
    # Removed: its address and network are given to the next app.
    gone = client.delete(f"{API}/apps/{a}").json()
    assert wait_job(client, gone["id"])["status"] == "succeeded"
    c = _deploy(client, "Gamma", 8403, zone["slug"])
    assert _ip(_compose(client, c)) == "10.100.0.10"
    assert _own(_compose(client, c)) == "10.100.128.0/28"


def test_apps_of_a_zone_without_a_shared_network_get_a_piece_of_it(client: TestClient) -> None:
    admin(client)
    zone = client.post(f"{API}/zones", json={"name": "Labo", "color": "#d97706"}).json()
    assert zone["network_mode"] == "none" and zone["subnet"] == "10.100.0.0/24"
    a = _deploy(client, "Alpha", 8421, zone["slug"])
    b = _deploy(client, "Beta", 8422, zone["slug"])
    assert list(_compose(client, a)["networks"]) == ["default"]
    assert _own(_compose(client, a)) == "10.100.0.0/28"
    assert _ip(_compose(client, b), "default") == "10.100.0.18"  # 10.100.0.16/28, .2
    # The zone now shares a network: each app moves to the range's own /28, and joins it.
    edit = client.put(f"{API}/zones/{zone['slug']}", json={
        "name": "Labo", "color": "#d97706", "network_mode": "shared"})  # fmt: skip
    assert edit.status_code == 200
    for job in client.get(f"{API}/jobs").json():
        wait_job(client, job["id"])
    compose = _compose(client, a)
    assert _own(compose) == "10.100.128.0/28"
    assert _ip(compose) == "10.100.0.10"


def test_a_zone_never_overlaps_the_host_lan(tmp_path: Any) -> None:
    import asyncio

    from hivora.addressing import Addressing
    from hivora.db.engine import make_engine, make_sessionmaker
    from hivora.db.migrate import upgrade_to_head
    from hivora.docker_gateway.fake import FakeDockerGateway
    from hivora.docker_gateway.models import NetworkInfo
    from hivora.zones import create_zone
    from hivora.zones.models import NetworkMode

    async def run() -> tuple[str, str | None]:
        db = tmp_path / "hivora.db"
        upgrade_to_head(db)
        sessions = make_sessionmaker(make_engine(db))
        gw = FakeDockerGateway()
        gw.networks.append(NetworkInfo("x", "bridge", "bridge", False, subnets=("10.100.0.0/16",)))
        addressing = Addressing(sessions=sessions, gateway=gw)

        async def lan(_: Any) -> list[Taken]:
            return [Taken("10.101.0.0/16", "host:lan")]

        addressing.sources.append(lan)
        from hivora.core.clock import SystemClock

        async with sessions() as session, session.begin():
            zone = await create_zone(session, SystemClock(), "Jeux", "#000000", NetworkMode.SHARED)
            subnet = await addressing.zone_subnet(session, zone)
            return str(await addressing.hivora_range(session)), subnet

    assert asyncio.run(run()) == ("10.102.0.0/16", "10.102.0.0/24")  # docker0-like and LAN skipped


# -- the Addressing page's API -----------------------------------------------------------


def _zone(c: TestClient, name: str, mode: str = "shared") -> dict[str, Any]:
    return c.post(f"{API}/zones", json={"name": name, "color": "#d97706",  # type: ignore[no-any-return]
                                        "network_mode": mode}).json()  # fmt: skip


def _wait_all(c: TestClient, out: dict[str, Any]) -> None:
    for job in out["jobs"]:
        assert wait_job(c, job["id"])["status"] == "succeeded"


def test_the_overview_shows_the_plan_and_what_docker_applied(client: TestClient) -> None:
    admin(client)
    zone = _zone(client, "Media")
    a = _deploy(client, "Alpha", 8431, zone["slug"])
    view = client.get(f"{API}/addressing").json()
    assert view["range"] == "10.100.0.0/16" and view["apps_block"] == "10.100.128.0/17"
    assert {"network": "192.168.1.0/24", "owner": "host:lan"} in view["excluded"]
    media = next(z for z in view["zones"] if z["slug"] == zone["slug"])
    assert (media["subnet"], media["origin"], media["used"], media["size"]) == (
        "10.100.0.0/24",
        "range",
        1,
        253,
    )
    row = media["rows"][0]
    assert (row["app_id"], row["service"], row["planned"]) == (a, "server", "10.100.0.10")
    assert row["state"] in ("ok", "pending")  # the fake Docker may not give IPs
    admin_zone = next(z for z in view["zones"] if z["slug"] == "administration")
    assert (admin_zone["subnet"], admin_zone["origin"]) == ("10.254.254.0/24", "system")
    assert view["app_networks"][0]["subnet"] == "10.100.128.0/28"


def test_a_zone_subnet_by_hand_previewed_refused_or_applied(client: TestClient) -> None:
    admin(client)
    zone = _zone(client, "Jeux")
    a = _deploy(client, "Alpha", 8441, zone["slug"])
    url = f"{API}/addressing/zones/{zone['slug']}"
    lan = client.put(url, json={"subnet": "192.168.1.0/25"})
    assert lan.status_code == 409 and code(lan) == "subnet_overlap"
    public = client.put(url, json={"subnet": "8.8.8.0/24"})
    assert public.status_code == 422 and code(public) == "subnet_invalid"
    preview = client.put(url, json={"subnet": "172.20.5.0/24", "dry_run": True}).json()
    assert preview["value"] == "172.20.5.0/24" and preview["apps"] == ["Alpha"]
    create = f"docker network create --subnet 172.20.5.0/24 hivora-zone-{zone['slug']}"
    assert preview["commands"][-1] == create
    assert preview["jobs"] == []
    assert client.get(f"{API}/zones").json()[-1]["subnet"] == "10.100.0.0/24"  # nothing kept
    done = client.put(url, json={"subnet": "172.20.5.0/24"}).json()
    _wait_all(client, done)
    assert _ip(_compose(client, a)) == "172.20.5.10"
    z = client.get(f"{API}/zones").json()[-1]
    assert (z["subnet"], z["subnet_manual"]) == ("172.20.5.0/24", True)
    back = client.put(url, json={"subnet": None}).json()  # automatic again
    _wait_all(client, back)
    assert back["value"] == "10.100.0.0/24" and _ip(_compose(client, a)) == "10.100.0.10"


def test_an_address_by_hand_is_checked_shown_and_applied(client: TestClient) -> None:
    admin(client)
    zone = _zone(client, "Media")
    a = _deploy(client, "Alpha", 8451, zone["slug"])
    b = _deploy(client, "Beta", 8452, zone["slug"])
    net = f"hivora-zone-{zone['slug']}"
    url = f"{API}/addressing/apps/{b}/ip"
    taken = client.put(url, json={"service": "server", "network": net, "address": "10.100.0.10"})
    assert taken.status_code == 409 and code(taken) == "ip_taken"
    gateway = client.put(url, json={"service": "server", "network": net, "address": "10.100.0.1"})
    assert gateway.status_code == 422 and code(gateway) == "ip_invalid"
    fifty = {"service": "server", "network": net, "address": "10.100.0.50"}
    preview = client.put(url, json={**fifty, "dry_run": True}).json()
    assert "+        ipv4_address: 10.100.0.50" in preview["diff"] and preview["jobs"] == []
    done = client.put(url, json=fifty).json()
    _wait_all(client, done)
    assert _ip(_compose(client, b)) == "10.100.0.50" and _ip(_compose(client, a)) == "10.100.0.10"
    row = next(r for z in client.get(f"{API}/addressing").json()["zones"] for r in z["rows"]
               if r["app_id"] == b)  # fmt: skip
    assert (row["planned"], row["manual"]) == ("10.100.0.50", True)


def test_a_new_range_moves_the_zones_and_apps_it_gave(client: TestClient) -> None:
    admin(client)
    zone = _zone(client, "Media")
    a = _deploy(client, "Alpha", 8461, zone["slug"])
    lan = client.put(f"{API}/addressing/range", json={"range": "192.168.0.0/16"})
    assert lan.status_code == 409 and code(lan) == "subnet_overlap"
    done = client.put(f"{API}/addressing/range", json={"range": "10.42.0.0/16"}).json()
    _wait_all(client, done)
    assert done["apps"] == ["Alpha"]
    compose = _compose(client, a)
    assert _ip(compose) == "10.42.0.10"
    assert _own(compose) == "10.42.128.0/28"
    view = client.get(f"{API}/addressing").json()
    assert view["range"] == "10.42.0.0/16"
    assert (
        next(z for z in view["zones"] if z["slug"] == "administration")["subnet"]
        == "10.254.254.0/24"
    )


def test_apply_the_plan_redeploys_only_the_apps_behind_it(client: TestClient) -> None:
    admin(client)
    a = _deploy(client, "Alpha", 8471)
    assert client.post(f"{API}/addressing/apply").json()["apps"] == []  # already applied
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    import asyncio

    from sqlalchemy import update

    from hivora.apps.models import AppRevision

    async def forget() -> None:  # as if deployed before static addressing
        async with rt.sessions() as session, session.begin():
            await session.execute(update(AppRevision).values(compose_yaml="services: {}\n"))

    asyncio.run(forget())
    out = client.post(f"{API}/addressing/apply").json()
    assert out["apps"] == ["Alpha"]
    _wait_all(client, out)
    assert _ip(_compose(client, a), "default") == "10.100.128.2"
