"""The Apache files Hivora writes for a host's sites: pure functions, no I/O.

The template's fixed httpd.conf serves the main site on port 80 and includes, from the
"conf" volume, ``main-*.conf`` inside the main virtual host and ``site-*.conf`` beside
it, like nginx. Values are checked by ``nginx.check`` (the same whitelist): nothing from
a site can add an Apache directive.
"""

from hivora.sites.nginx import InvalidSiteConfigError, NginxSite, check

MAIN_OFF = "Redirect 503 /\n"  # main-off.conf: the main site turned off
SITES_ROOT = "/usr/local/apache2/sites"  # the "sites" volume, in the container


def render_site(site: NginxSite) -> str:
    """The virtual host of an added site: its own port (Listen) and folder."""
    check(site)
    if site.main:
        raise InvalidSiteConfigError("the main site is served by httpd.conf", site=site.id)
    root = f"{SITES_ROOT}/{site.root}"
    name = f"    ServerName {site.server_name}\n" if site.server_name else ""
    return (
        f'# Managed by Hivora: site "{site.slug}" (id {site.id}). Regenerated from the'
        " database, do not edit.\n"
        f"Listen {site.port}\n"
        f"<VirtualHost *:{site.port}>\n"
        f"{name}"
        f'    DocumentRoot "{root}"\n'
        f'    <Directory "{root}">\n'
        "        Require all granted\n"
        "    </Directory>\n"
        "</VirtualHost>\n"
    )
