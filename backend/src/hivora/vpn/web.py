"""The VPN's web proxy: a name of the VPN's DNS aimed at a web port other than 80 opens
without its port (http://actual.lan for Actual on 5006).

One Caddy for the whole panel, ``hivora-web``: one of Hivora's own containers, not an app
(never privileged, no published port), on the network of each zone it serves, at a fixed
address of the addressing plan. The VPN's DNS gives that address for such a name; Caddy
sends the request on to the app's container and port. Plain HTTP (no certificate).
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from hivora.docker_gateway import DockerGateway
from hivora.proxy.caddy import Site, sites_file

logger = logging.getLogger(__name__)

NAME = "hivora-web"  # its container
SLUG = "_hivora-web"  # its addresses in the addressing plan (no app can have this slug)
SERVICE = "proxy"
# The same Caddy as the HTTPS proxy's template (templates/caddy), pinned by digest.
IMAGE = (
    "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
)
LABELS = {"io.hivora.web": "true"}
CADDYFILE = """\
# Written by Hivora: the VPN's web proxy, plain HTTP. Do not edit.
{
    admin localhost:2019
    auto_https off
}
import /etc/caddy/sites.caddy
"""
RELOAD = ["caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
DIRECT_PORT = 80  # a name for port 80 needs no proxy: it gives the app's own address


@dataclass(frozen=True, slots=True)
class Route:
    """A name the proxy serves: the app's container, its port, its zone's network."""

    name: str
    container: str
    port: int
    network: str


def via_proxy(port: int | None) -> bool:
    """A name aimed at a port other than 80 goes through the proxy (the app itself, no
    port: the app's address, any protocol; port 80: the app's address too)."""
    return port is not None and port != DIRECT_PORT


def container_of(slug: str, service: str) -> str:
    """The Docker name of an app's service container (Compose: <project>-<service>-1)."""
    return f"{slug}-{service}-1"


def sites(routes: list[Route]) -> str:
    return sites_file([Site(f"http://{r.name}", f"{r.container}:{r.port}") for r in routes])


def write_files(directory: Path, routes: list[Route]) -> bool:
    """The Caddyfile and the sites; True when the sites changed."""
    directory.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, text in (("Caddyfile", CADDYFILE), ("sites.caddy", sites(routes))):
        path = directory / name
        try:
            if path.read_text() == text:
                continue
        except OSError:
            pass
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        tmp.replace(path)
        changed = changed or name == "sites.caddy"
    return changed


async def apply(gateway: DockerGateway, directory: Path, routes: list[Route],
                addresses: dict[str, str]) -> str:  # fmt: skip
    """The proxy as it must be now: removed with no route, else on its networks (at their
    fixed addresses) with these sites, reloaded when they changed. What was done, in words."""
    if not routes:
        removed = await gateway.remove_agent(NAME)
        return "no name through the proxy: removed" if removed else "no name through the proxy"
    changed = write_files(directory, routes)
    binds = [f"{directory}:/etc/caddy:ro"]
    cid = await gateway.ensure_sidecar(NAME, IMAGE, LABELS, binds, addresses)
    if changed:
        for attempt in range(5):  # just created: its admin endpoint needs a moment
            code, out = await gateway.exec_run(cid, RELOAD)
            if code == 0:
                break
            if attempt == 4:
                logger.warning("web proxy not reloaded", extra={"output": out[-300:]})
            await asyncio.sleep(1)
    names = ", ".join(sorted(r.name for r in routes))
    return f"{len(routes)} name(s) through the proxy ({names}) on {', '.join(sorted(addresses))}"


if __name__ == "__main__":
    assert not via_proxy(None) and not via_proxy(80) and via_proxy(5006)
    text = sites([Route("actual.lan", "actual-app-1", 5006, "hivora-zone-test")])
    assert "http://actual.lan {" in text and "reverse_proxy actual-app-1:5006" in text
