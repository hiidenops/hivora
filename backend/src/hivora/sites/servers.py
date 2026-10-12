"""The web servers that host sites, and what differs between them.

Everything else (the sites' rows, ports, revisions, jobs, files and contents) is the
same for all. A host's server is told by its volumes (the main site's folder in the
container), so no template lookup is needed where only the volumes are read.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

# The submodules themselves, not through the package: its __init__ imports core, which
# imports this module (a cycle otherwise).
import hivora.sites.httpd as httpd
import hivora.sites.nginx as nginx


@dataclass(frozen=True, slots=True)
class WebServer:
    template: str  # its catalog slug
    label: str  # in messages
    html: str  # the main site's volume, in the container
    sites: str  # the added sites' volume (template versions that host sites)
    conf: str  # the volume of the files Hivora writes
    check: tuple[str, ...]  # checks the whole configuration (exec in the container)
    reload: tuple[str, ...]  # applies it without dropping connections
    render: Callable[[nginx.NginxSite], str]  # an added site's file
    main_off: str  # main-off.conf: the main site turned off


NGINX = WebServer(
    "nginx", "nginx", "/usr/share/nginx/html", "/usr/share/nginx/sites", "/etc/nginx/hivora.d",
    ("nginx", "-t"), ("nginx", "-s", "reload"), nginx.render_site, nginx.MAIN_OFF,
)  # fmt: skip
HTTPD = WebServer(
    "httpd", "Apache", "/usr/local/apache2/htdocs", "/usr/local/apache2/sites",
    "/usr/local/apache2/conf/hivora.d", ("httpd", "-t"), ("httpd", "-k", "graceful"),
    httpd.render_site, httpd.MAIN_OFF,
)  # fmt: skip
SERVERS = (NGINX, HTTPD)
TEMPLATES = {s.template: s for s in SERVERS}


def of_targets(targets: Iterable[str]) -> WebServer | None:
    """The server whose main site's volume is among these targets, if any."""
    found = set(targets)
    return next((s for s in SERVERS if s.html in found), None)
