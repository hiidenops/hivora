import ast
from pathlib import Path
from typing import Any

import pytest

import hivora.hostfw.routing as routing
from hivora.core.errors import ConflictError, ValidationError
from hivora.hostfw.routing import (
    Route,
    check,
    connected,
    delete_argv,
    plan,
    replace_argv,
    route,
)

# ip -j route, as on the dev VM: DHCP's default route and LAN, Docker's bridges (one down).
HOST: list[dict[str, Any]] = [
    {"dst": "default", "gateway": "192.168.70.2", "dev": "enp2s0", "protocol": "dhcp",
     "prefsrc": "192.168.70.150", "metric": 1002, "flags": []},
    {"dst": "172.17.0.0/16", "dev": "docker0", "protocol": "kernel", "scope": "link",
     "prefsrc": "172.17.0.1", "flags": ["linkdown"]},
    {"dst": "172.18.0.0/16", "dev": "br-bd6101b73143", "protocol": "kernel", "scope": "link",
     "prefsrc": "172.18.0.1", "flags": []},
    {"dst": "192.168.70.0/24", "dev": "enp2s0", "protocol": "dhcp", "scope": "link",
     "prefsrc": "192.168.70.150", "metric": 1002, "flags": []},
    {"dst": "10.20.0.0/16", "gateway": "192.168.70.9", "dev": "enp2s0", "protocol": "static"},
]  # fmt: skip
LAN = connected(HOST)


def test_the_connected_networks_and_interfaces_are_read_from_the_routing_table() -> None:
    assert [(str(n), d) for n, d in LAN.networks] == [
        ("172.17.0.0/16", "docker0"),
        ("172.18.0.0/16", "br-bd6101b73143"),
        ("192.168.70.0/24", "enp2s0"),
    ]  # fmt: skip  (not the default route, not a route through a gateway)
    assert LAN.devs == {"enp2s0", "docker0", "br-bd6101b73143"}


def test_a_route_is_canonical_and_its_command_line_exact() -> None:
    r = route("10.8.0.5/24", "192.168.70.20", "enp2s0", 50)
    assert r == Route("10.8.0.0/24", "192.168.70.20", "enp2s0", 50)
    check(r, LAN, requester="192.168.70.150")
    assert replace_argv(r) == ["ip", "route", "replace", "10.8.0.0/24", "via", "192.168.70.20",
                               "dev", "enp2s0", "metric", "50", "proto", "241"]  # fmt: skip
    one = route("10.9.0.7", "192.168.70.20", "", None)  # one address: /32; no dev, no metric
    assert replace_argv(one) == ["ip", "route", "replace", "10.9.0.7/32", "via",
                                 "192.168.70.20", "proto", "241"]  # fmt: skip
    assert delete_argv("10.8.0.0/24") == ["ip", "route", "del", "10.8.0.0/24", "proto", "241"]


@pytest.mark.parametrize("args", [
    ("0.0.0.0/0", "192.168.70.20"), ("10.8.0.0/0", "192.168.70.20"),  # the default route
    ("fd00::/64", "192.168.70.20"), ("10.8.0.0/24", "fe80::1"),  # IPv6
    ("127.0.0.0/8", "192.168.70.20"), ("224.0.0.0/4", "192.168.70.20"),
    ("169.254.0.0/16", "192.168.70.20"), ("10.8.0.0/33", "192.168.70.20"),
    ("10.8.0.0/24 via 1.2.3.4", "192.168.70.20"), ("10.8.0.0/24\nproto 0", "192.168.70.20"),
    ("10.8.0.0/24", "192.168.70.20 dev lo"), ("10.8.0.0/24", "0.0.0.0"),
    ("10.8.0.0/24", "127.0.0.1"), ("exemple.fr", "192.168.70.20"),
    ("10.8.0.0/24", "192.168.70.20", "eth0; reboot"), ("10.8.0.0/24", "192.168.70.20", "a" * 16),
    ("10.8.0.0/24", "192.168.70.20", None, -1), ("10.8.0.0/24", "192.168.70.20", None, 2**32),
])  # fmt: skip
def test_malformed_routes_are_refused(args: tuple[Any, ...]) -> None:
    with pytest.raises(ValidationError) as caught:
        route(*args)
    assert caught.value.code == "invalid_route"


@pytest.mark.parametrize(("args", "requester", "error"), [
    (("192.168.70.0/25", "192.168.70.20"), None, "route_overlaps_connected"),  # inside the LAN
    (("192.168.0.0/16", "192.168.70.20"), None, "route_overlaps_connected"),  # over it
    (("172.18.5.0/24", "192.168.70.20"), None, "route_overlaps_connected"),  # a Docker bridge
    (("10.8.0.0/24", "192.168.70.20"), "10.8.0.33", "route_contains_requester"),
    (("10.8.0.0/24", "192.168.70.20"), "::ffff:10.8.0.33", "route_contains_requester"),
    (("10.8.0.0/24", "192.168.70.20", "wg0"), None, "unknown_interface"),
    (("10.8.0.0/24", "10.99.0.1"), None, "gateway_not_connected"),
    (("10.8.0.0/24", "192.168.70.20", "docker0"), None, "gateway_not_connected"),  # not its LAN
])  # fmt: skip
def test_routes_that_could_cut_the_host_off_are_refused(
    args: tuple[Any, ...], requester: str | None, error: str
) -> None:
    with pytest.raises(ConflictError) as caught:
        check(route(*args), LAN, requester=requester)
    assert caught.value.code == error


def test_a_requester_that_is_not_an_address_is_ignored() -> None:
    check(route("10.8.0.0/24", "192.168.70.20"), LAN, requester="testclient")


def test_the_plan_replaces_every_wanted_route_and_deletes_only_the_stale_marked_ones() -> None:
    wanted = [route("10.9.0.7", "192.168.70.20"), route("10.8.0.0/24", "192.168.70.20")]
    present = [  # ip -j route show proto 241: one address shown without its /32
        {"dst": "10.9.0.7", "gateway": "192.168.70.20", "dev": "enp2s0", "protocol": "241"},
        {"dst": "10.7.0.0/16", "gateway": "192.168.70.21", "dev": "enp2s0", "protocol": "241"},
    ]
    keep, stale = plan(wanted, present)
    assert [r.destination for r in keep] == ["10.8.0.0/24", "10.9.0.7/32"]
    assert stale == ["10.7.0.0/16"]  # 10.9.0.7 kept, whatever its spelling
    assert plan([], []) == ([], [])


def test_the_routing_module_does_no_io() -> None:
    tree = ast.parse(Path(routing.__file__).read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {"ipaddress", "re", "collections.abc", "dataclasses", "typing",
                        "hivora.core.errors"}  # fmt: skip
