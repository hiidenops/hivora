from hivora.docker_gateway import ContainerState, Health, PublishedPort
from hivora.docker_gateway.local import (
    container_from_inspect,
    container_from_summary,
    event_from_raw,
    stats_from_raw,
)


def test_summary_with_health_field() -> None:
    c = container_from_summary(
        {
            "Id": "abc",
            "Names": ["/demo-web-1"],
            "Image": "traefik/whoami:v1.10",
            "State": "running",
            "Status": "Up 3 seconds (healthy)",
            "Health": {"Status": "healthy"},
            "Labels": {"io.hivora.app": "demo"},
            "Ports": [{"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"}],
            "NetworkSettings": {"Networks": {"demo_default": {}}},
        }
    )
    assert c.name == "demo-web-1"
    assert c.state is ContainerState.RUNNING and c.health is Health.HEALTHY
    assert c.ports == (PublishedPort(80, "tcp", "0.0.0.0", 8080),)
    assert c.networks == ("demo_default",)


def test_summary_old_engine_status_fallback_and_exit_code() -> None:
    starting = container_from_summary(
        {"Id": "a", "State": "running", "Status": "Up 1 second (health: starting)"}
    )
    assert starting.health is Health.STARTING
    exited = container_from_summary({"Id": "b", "State": "exited", "Status": "Exited (3) 2s ago"})
    assert exited.exit_code == 3 and exited.health is Health.NONE


def test_inspect() -> None:
    c = container_from_inspect(
        {
            "Id": "abc",
            "Name": "/demo-web-1",
            "State": {"Status": "exited", "ExitCode": 137, "Health": {"Status": "unhealthy"}},
            "Config": {"Image": "demo:1", "Labels": {"a": "b"}},
            "NetworkSettings": {
                "Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}], "53/udp": None},
                "Networks": {"bridge": {}},
            },
        }
    )
    assert c.exit_code == 137 and c.health is Health.UNHEALTHY
    assert set(c.ports) == {
        PublishedPort(80, "tcp", "127.0.0.1", 8080),
        PublishedPort(53, "udp", None, None),
    }


def test_stats_matches_docker_cli_formula() -> None:
    s = stats_from_raw(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300},
                "system_cpu_usage": 2000,
                "online_cpus": 4,
            },
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
            "memory_stats": {"usage": 1000, "limit": 4000, "stats": {"inactive_file": 200}},
            "networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 5}, "eth1": {"rx_bytes": 1}},
        }
    )
    assert s.cpu_percent == 80.0
    assert (s.mem_bytes, s.mem_limit, s.net_rx, s.net_tx) == (800, 4000, 11, 5)


def test_event() -> None:
    e = event_from_raw(
        {
            "Type": "container",
            "Action": "health_status: healthy",
            "timeNano": 1_700_000_000_000_000_000,
            "Actor": {"ID": "abc", "Attributes": {"io.hivora.app": "demo"}},
        }
    )
    assert (e.type, e.actor_id, e.attributes) == ("container", "abc", {"io.hivora.app": "demo"})
    assert e.time is not None and e.time.year == 2023
