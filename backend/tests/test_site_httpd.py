"""Apache (the httpd template) hosts sites like nginx: its own files, checked by
``httpd -t`` then reloaded by ``httpd -k graceful``, or put back as they were."""

from typing import Any

import pytest
from helpers import API, admin, nginx_host, wait_job

from hivora.sites import httpd, servers
from hivora.sites.nginx import InvalidSiteConfigError, NginxSite, desired_files

BLOG = NginxSite(7, "blog", "blog", 8096, "blog.example.com", enabled=True)
WIKI = NginxSite(8, "wiki", "wiki", 8097, None, enabled=True)
MAIN_OFF = NginxSite(1, "main", "", None, None, enabled=False)


def test_an_added_site_is_its_own_virtual_host() -> None:
    assert httpd.render_site(BLOG) == (
        '# Managed by Hivora: site "blog" (id 7). Regenerated from the database, do not edit.\n'
        "Listen 8096\n"
        "<VirtualHost *:8096>\n"
        "    ServerName blog.example.com\n"
        '    DocumentRoot "/usr/local/apache2/sites/blog"\n'
        '    <Directory "/usr/local/apache2/sites/blog">\n'
        "        Require all granted\n"
        "    </Directory>\n"
        "</VirtualHost>\n"
    )
    assert "ServerName" not in httpd.render_site(WIKI)  # no name: any name, on its port


def test_the_files_apache_gets_and_what_is_refused() -> None:
    files = desired_files([MAIN_OFF, BLOG, WIKI], servers.HTTPD.render, servers.HTTPD.main_off)
    assert list(files) == ["main-off.conf", "site-blog.conf", "site-wiki.conf"]
    assert files["main-off.conf"] == "Redirect 503 /\n"  # the main site answers 503
    with pytest.raises(InvalidSiteConfigError):  # the main site is httpd.conf's
        httpd.render_site(NginxSite(1, "main", "", None, None, enabled=True))
    for bad in ("a.com\nListen 1", 'a.com" Include /etc', "<Directory />"):
        with pytest.raises(InvalidSiteConfigError):  # the same whitelist as nginx
            httpd.render_site(NginxSite(7, "blog", "blog", 8096, bad, enabled=True))


def test_the_server_is_told_by_its_volumes() -> None:
    assert servers.of_targets(["/usr/local/apache2/htdocs", "/x"]) is servers.HTTPD
    assert servers.of_targets(["/usr/share/nginx/html"]) is servers.NGINX
    assert servers.of_targets(["/data"]) is None


def test_an_apache_hosts_sites_through_the_api(client: Any) -> None:
    admin(client)
    gw = client.app.state.runtime.gateway
    app_id = nginx_host(client, "Atelier", 8190, running=True, template="httpd")
    conf = client.app.state.runtime.settings.volumes_root / "atelier" / "conf"
    host = client.get(f"{API}/apps/{app_id}/sites").json()
    assert (host["server"], host["upgrade_required"]) == ("Apache", False)
    assert [s["main"] for s in host["sites"]] == [True]

    added = client.post(f"{API}/apps/{app_id}/sites", json={"name": "Docs", "port": 8096}).json()
    job = wait_job(client, added["config_job"]["id"])
    assert job["status"] == "succeeded", job["error"]
    assert (conf / "site-docs.conf").read_text().split("\n", 1)[1].startswith("Listen 8096\n")
    calls = [" ".join(c) for c in gw.exec_calls]
    assert calls[-2:] == ["httpd -t", "httpd -k graceful"]  # checked, then reloaded

    # The main site off: Apache answers 503 there, the other site goes on.
    main = host["sites"][0]["id"]
    off = client.put(f"{API}/apps/{app_id}/sites/{main}/enabled", json={"enabled": False}).json()
    assert wait_job(client, off["id"])["status"] == "succeeded"
    assert (conf / "main-off.conf").read_text() == "Redirect 503 /\n"

    # Apache refuses: the files are put back, the error says so.
    gw.exec_results["httpd -t"] = (1, "AH00526: Syntax error on line 2")
    on = client.put(f"{API}/apps/{app_id}/sites/{main}/enabled", json={"enabled": True}).json()
    job = wait_job(client, on["id"])
    assert job["status"] == "failed" and "Apache refused the configuration" in job["error"]
    assert (conf / "main-off.conf").exists()  # put back as it was


def test_other_apps_still_cannot_host_sites(client: Any) -> None:
    admin(client)
    vw = client.post(f"{API}/apps", json={"template": "vaultwarden", "name": "Coffre"}).json()
    assert wait_job(client, vw["job"]["id"])["status"] == "succeeded"
    r = client.post(f"{API}/apps/{vw['app']['id']}/sites/hosting")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "not_a_nginx_app")
