"""The nginx files Hivora writes for a host's sites: pure functions, no I/O.

The template's fixed default.conf serves the main site and includes, from the "conf"
volume, ``main-*.conf`` inside the main server and ``site-*.conf`` beside it. From the
sites recorded in the database this computes the exact set of those files.

Every value is checked against a whitelist and refused otherwise, never escaped: nothing
from a site can add an nginx directive.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from hivora.core.errors import ValidationError

MAIN_SLUG = "main"
MAIN_PORT = 80  # the main site's port inside the container (the app's web port outside)
MAIN_OFF = "return 503;\n"  # main-off.conf: the main site turned off
SITES_ROOT = "/usr/share/nginx/sites"  # the "sites" volume, in the container
MANAGED = re.compile(r"^(?:main|site)-[a-z0-9][a-z0-9-]{0,62}\.conf$")  # Hivora's files

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_SERVER_NAME = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$")


class InvalidSiteConfigError(ValidationError):
    code = "invalid_site_config"


@dataclass(frozen=True, slots=True)
class NginxSite:
    id: int
    slug: str
    root: str  # "": the main site (the html volume); else its folder in the sites volume
    port: int | None  # None: the main site
    server_name: str | None
    enabled: bool

    @property
    def main(self) -> bool:
        return self.root == ""


def check(site: NginxSite) -> None:
    """Refuse any value that is not exactly what the rendered file expects."""

    def refuse(reason: str) -> InvalidSiteConfigError:
        return InvalidSiteConfigError(reason, site=site.id)

    if site.main:
        if site.slug != MAIN_SLUG or site.port is not None or site.server_name is not None:
            raise refuse("the main site is the html volume on the app's web port")
        return
    if not _SLUG.match(site.slug) or site.slug == MAIN_SLUG:
        raise refuse("invalid site slug")
    if site.root != site.slug:
        raise refuse("a site's folder is its slug")
    # bool is an int in Python: refused explicitly.
    if type(site.port) is not int or not 1 <= site.port <= 65535 or site.port == MAIN_PORT:
        raise refuse("invalid site port")
    if site.server_name is not None and (
        len(site.server_name) > 253 or not _SERVER_NAME.match(site.server_name)
    ):
        raise refuse("invalid server name")


def render_site(site: NginxSite) -> str:
    """The server block of an added site (its own port and folder)."""
    check(site)
    if site.main:
        raise InvalidSiteConfigError("the main site is served by default.conf", site=site.id)
    return (
        f'# Managed by Hivora: site "{site.slug}" (id {site.id}). Regenerated from the'
        " database, do not edit.\n"
        "server {\n"
        f"    listen {site.port};\n"
        f"    server_name {site.server_name or '_'};\n"
        f"    root {SITES_ROOT}/{site.root};\n"
        "    index index.html index.htm;\n"
        "}\n"
    )


def desired_files(sites: Iterable[NginxSite]) -> dict[str, str]:
    """Every file Hivora's part of the conf volume must hold, by name (sorted).

    No main site row (an nginx whose sites Hivora does not manage): it stays on.
    """
    sites = list(sites)
    for site in sites:
        check(site)
    if sum(s.main for s in sites) > 1:
        raise InvalidSiteConfigError("more than one main site")
    for field in ("slug", "port"):
        values = [getattr(s, field) for s in sites if not s.main]
        if len(values) != len(set(values)):
            raise InvalidSiteConfigError(f"two sites with the same {field}")
    files: dict[str, str] = {}
    for site in sites:
        if site.enabled:
            if not site.main:
                files[f"site-{site.slug}.conf"] = render_site(site)
        elif site.main:
            files["main-off.conf"] = MAIN_OFF
    return dict(sorted(files.items()))
