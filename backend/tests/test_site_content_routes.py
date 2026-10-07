"""Content and files of one hosted site through the API (/apps/{app_id}/sites/{site_id}/...):
in the site's own folder, never in another site's."""

from pathlib import Path
from typing import Any

from helpers import (
    API,
    MAIN_PAGE,
    STRONG,
    admin,
    code,
    login,
    nginx_host,
    other_user,
    save_file,
    upload_zip,
    wait_job,
    zip_bytes,
)


def _host(client: Any) -> tuple[int, Path, dict[str, int]]:
    """A host with two added sites, blog and wiki; its main site has a page."""
    admin(client)
    app_id = nginx_host(client, running=True)
    app_dir: Path = client.app.state.runtime.settings.volumes_root / "vitrine"
    (app_dir / "html" / "index.html").write_text(MAIN_PAGE)
    for name, port in (("Blog", 8096), ("Wiki", 8097)):
        added = client.post(f"{API}/apps/{app_id}/sites", json={"name": name, "port": port})
        assert added.status_code == 202, added.text
        wait_job(client, added.json()["config_job"]["id"])
    sites = client.get(f"{API}/apps/{app_id}/sites").json()["sites"]
    return app_id, app_dir, {s["slug"]: s["id"] for s in sites}


def _base(app_id: int, site_id: int) -> str:
    return f"{API}/apps/{app_id}/sites/{site_id}"


def _tree(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): p.read_text() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def test_a_zip_on_an_added_site(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    main_before = _tree(app_dir / "html")
    body = zip_bytes(("blog/index.html", "<h1>blog</h1>"), ("blog/css/a.css", "a{}"))
    sent = upload_zip(client, _base(app_id, ids["blog"]), body)
    assert sent.status_code == 202 and sent.json()["kind"] == "site_content"
    assert wait_job(client, sent.json()["id"])["status"] == "succeeded"
    assert _tree(app_dir / "sites" / "blog") == {"index.html": "<h1>blog</h1>", "css/a.css": "a{}"}
    assert _tree(app_dir / "html") == main_before  # the main site untouched
    assert not (app_dir / "sites" / "wiki").exists()  # nor the other site
    listed = client.get(f"{_base(app_id, ids['blog'])}/files").json()
    assert [f["path"] for f in listed["files"]] == ["css/a.css", "index.html"]


def test_read_edit_create_and_conflict(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    url = _base(app_id, ids["blog"])
    created = save_file(client, url, "index.html", "<h1>v1</h1>", None)  # a new file
    assert created.status_code == 202 and created.json()["kind"] == "site_file"
    assert wait_job(client, created.json()["id"])["status"] == "succeeded"
    read = client.get(f"{url}/files/content", params={"path": "index.html"}).json()
    assert read["content"] == "<h1>v1</h1>" and len(read["sha256"]) == 64

    edited = save_file(client, url, "index.html", "<h1>v2</h1>", read["sha256"])
    assert wait_job(client, edited.json()["id"])["status"] == "succeeded"
    assert (app_dir / "sites" / "blog" / "index.html").read_text() == "<h1>v2</h1>"
    stale = save_file(client, url, "index.html", "late", read["sha256"])  # read before the edit
    assert stale.status_code == 409 and code(stale) == "file_changed"
    again = save_file(client, url, "index.html", "x", None)  # creating over an existing file
    assert again.status_code == 409 and code(again) == "file_changed"

    new = save_file(client, url, "css/a.css", "a{}", None)
    assert wait_job(client, new.json()["id"])["status"] == "succeeded"
    paths = [f["path"] for f in client.get(f"{url}/files").json()["files"]]
    assert paths == ["css/a.css", "index.html"]
    assert "<title>Vitrine</title>" in (app_dir / "html" / "index.html").read_text()


def test_no_way_from_one_site_into_another(client: Any) -> None:
    app_id, app_dir, ids = _host(client)
    sites = app_dir / "sites"
    (sites / "wiki").mkdir()
    (sites / "wiki" / "secret.html").write_text("wiki")
    (sites / "blog").mkdir()
    (sites / "blog" / "w").symlink_to(sites / "wiki")
    url = _base(app_id, ids["blog"])
    cases = [
        client.get(f"{url}/files/content", params={"path": "../wiki/secret.html"}),
        save_file(client, url, "../wiki/x.html", "x", None),
        client.get(f"{url}/files/content", params={"path": "w/secret.html"}),
        save_file(client, url, "w/x.html", "x", None),
    ]
    assert [(r.status_code, code(r)) for r in cases] == [
        (422, "invalid_path"), (422, "invalid_path"),
        (403, "permission_denied"), (403, "permission_denied"),
    ]  # fmt: skip
    assert client.get(f"{url}/files").json()["files"] == []  # the link is not listed

    # The site's own folder a link into another site: every route refuses it.
    (sites / "blog" / "w").unlink()
    (sites / "blog").rmdir()
    (sites / "blog").symlink_to(sites / "wiki")
    refused = [
        client.get(f"{url}/files"),
        client.get(f"{url}/files/content", params={"path": "secret.html"}),
        save_file(client, url, "x.html", "x", None),
        upload_zip(client, url, zip_bytes(("index.html", "x"))),
    ]
    assert {(r.status_code, code(r)) for r in refused} == {(403, "permission_denied")}
    assert _tree(sites / "wiki") == {"secret.html": "wiki"}
    assert [p.name for p in app_dir.iterdir() if p.name.startswith(".hivora")] == []


def test_unknown_sites_and_sites_of_other_apps(client: Any) -> None:
    app_id, _, ids = _host(client)
    other_id = nginx_host(client, "Autre", 8191)
    for url in (_base(app_id, 9999), _base(other_id, ids["blog"])):
        for r in (
            client.get(f"{url}/files"),
            client.get(f"{url}/files/content", params={"path": "index.html"}),
            save_file(client, url, "index.html", "x", None),
            upload_zip(client, url, zip_bytes(("index.html", "x"))),
        ):
            assert (r.status_code, code(r)) == (404, "site_not_found"), (url, r.text)


def test_viewers_read_operators_write(client: Any) -> None:
    app_id, _, ids = _host(client)
    url = _base(app_id, ids["blog"])
    wait_job(client, save_file(client, url, "index.html", "<h1>blog</h1>", None).json()["id"])
    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{url}/files").status_code == 200
        read = viewer.get(f"{url}/files/content", params={"path": "index.html"})
        assert read.status_code == 200 and read.json()["content"] == "<h1>blog</h1>"
        for r in (
            save_file(viewer, url, "index.html", "x", read.json()["sha256"]),
            upload_zip(viewer, url, zip_bytes(("index.html", "x"))),
        ):
            assert (r.status_code, code(r)) == (403, "insufficient_role")
