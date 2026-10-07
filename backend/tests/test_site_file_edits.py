"""A hosted site's text files (/apps/{app}/sites/{site}/files): read at once, saved by a
site_file job if the file is still the one read."""

import os
import time
from typing import Any

import pytest
from helpers import (
    API,
    NGINX_VOLUMES,
    STRONG,
    admin,
    code,
    deploy_nginx,
    host_before_deploy,
    login,
    main_site_url,
    other_user,
    read_file,
    save_file,
    site_id_of,
    spy_events,
    upload_zip,
    volumes_of,
    wait_job,
    zip_bytes,
)


def test_edit_a_file_through_its_job(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    html = volumes_of(client) / "html"
    base = read_file(client, url, "index.html").json()["sha256"]
    published, undo = spy_events(client)
    try:
        saved = save_file(client, url, "index.html", "<h1>Bienvenue</h1>", base)
        assert saved.status_code == 202, saved.text
        assert saved.json()["kind"] == "site_file"
        job = wait_job(client, saved.json()["id"])
    finally:
        undo()
    assert job["status"] == "succeeded", job["error"]
    assert (html / "index.html").read_text() == "<h1>Bienvenue</h1>"
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES  # nothing staged
    events = [(t, p) for t, p in published if t.startswith("site.")]
    saved_event = {"app": "vitrine", "path": "index.html", "bytes": 18, "created": False,
                   "site_id": site_id_of(url)}  # fmt: skip
    assert events == [("site.file_saved", saved_event)]
    detail = client.get(f"{API}/jobs/{job['id']}").json()
    assert "Bienvenue" not in detail["log"] and "index.html (18 bytes)" in detail["log"]
    time.sleep(0.8)  # the recorder writes in small batches
    audit = [a for a in client.get(f"{API}/audit", params={"limit": 1000}).json()
             if a["action"] == "site.file_saved"]  # fmt: skip
    assert [(a["target"], a["payload"]["path"]) for a in audit] == [("vitrine", "index.html")]
    assert "Bienvenue" not in str(audit)  # never the content

    stale = save_file(client, url, "index.html", "late", base)  # read before the edit
    assert stale.status_code == 409 and code(stale) == "file_changed"
    assert (html / "index.html").read_text() == "<h1>Bienvenue</h1>"


def test_create_a_file_in_new_folders(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    saved = save_file(client, url, "css/theme/main.css", "body{margin:0}", None)
    job = wait_job(client, saved.json()["id"])
    assert job["status"] == "succeeded"
    assert "created css/theme/main.css" in client.get(f"{API}/jobs/{job['id']}").json()["log"]
    paths = [f["path"] for f in client.get(f"{url}/files").json()["files"]]
    assert paths == ["css/theme/main.css", "index.html"]
    again = save_file(client, url, "css/theme/main.css", "x", None)
    assert again.status_code == 409 and code(again) == "file_changed"


def test_bad_edits_are_refused_before_any_job(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    html = volumes_of(client) / "html"
    (html / "nul.html").write_bytes(b"a\x00b")
    (html / "link.html").symlink_to(html / "index.html")
    base = read_file(client, url, "index.html").json()["sha256"]
    jobs_before = client.get(f"{API}/jobs").json()
    cases = [
        (save_file(client, url, "../evil.html", "x", None), 422, "invalid_path"),
        (save_file(client, url, "shell.php", "x", None), 422, "file_not_editable"),
        (save_file(client, url, "index.html", "a\x00b", base), 422, "not_text"),
        (save_file(client, url, "index.html", "é" * 600_000, base), 422, "file_too_large"),
        (save_file(client, url, "index.html", "x", "0" * 64), 409, "file_changed"),
        (save_file(client, url, "gone.html", "x", base), 404, "site_file_not_found"),
        (save_file(client, url, "link.html", "x", None), 403, "permission_denied"),
        (save_file(client, url, "index.html", "x", "not-a-hash"), 422, "request_invalid"),
        (read_file(client, url, "nul.html"), 422, "not_text"),
        (read_file(client, url, "link.html"), 403, "permission_denied"),
        (read_file(client, url, "gone.html"), 404, "site_file_not_found"),
        (read_file(client, url, "../../etc/passwd.html"), 422, "invalid_path"),
    ]
    for r, status, error in cases:
        assert (r.status_code, code(r)) == (status, error), r.text
    assert client.get(f"{API}/jobs").json() == jobs_before  # nothing queued
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES  # nothing staged
    assert "<title>Vitrine</title>" in (html / "index.html").read_text()


def test_a_zip_applied_in_between_wins_over_a_stale_edit(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    base = read_file(client, url, "index.html").json()["sha256"]
    zipped = upload_zip(client, url, zip_bytes(("index.html", "from the zip")))
    saved = save_file(client, url, "index.html", "stale edit", base)  # sent right after
    assert wait_job(client, zipped.json()["id"])["status"] == "succeeded"
    if saved.status_code == 202:  # queued before the zip was applied: refused by the job
        job = wait_job(client, saved.json()["id"])
        assert job["status"] == "failed" and "changed since it was read" in job["error"]
    else:  # the zip was already applied: refused at once
        assert saved.status_code == 409 and code(saved) == "file_changed"
    assert (volumes_of(client) / "html" / "index.html").read_text() == "from the zip"
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES


def test_old_staged_edits_are_swept(client: Any) -> None:
    admin(client)
    url = main_site_url(client)
    app_dir = volumes_of(client)
    old, recent = app_dir / ".hivora-edit-old", app_dir / ".hivora-edit-new"
    old.write_text("x")
    recent.write_text("x")  # may belong to a queued job: kept
    day_ago = time.time() - 2 * 24 * 3600
    os.utime(old, (day_ago, day_ago))
    base = read_file(client, url, "index.html").json()["sha256"]
    job = wait_job(client, save_file(client, url, "index.html", "x", base).json()["id"])
    assert job["status"] == "succeeded"
    assert sorted(p.name for p in app_dir.iterdir()) == [".hivora-edit-new", *NGINX_VOLUMES]


def test_file_routes_roles_and_unknown(client: Any) -> None:
    admin(client)
    manual = deploy_nginx(client, "Manuel", 8180).json()
    wait_job(client, manual["job"]["id"])
    url = main_site_url(client)
    base = read_file(client, url, "index.html").json()["sha256"]
    for app_id in (manual["app"]["id"], 9999):  # a catalog nginx hosts no sites yet
        other = f"{API}/apps/{app_id}/sites/{site_id_of(url)}"
        for r in (
            client.get(f"{other}/files"),
            read_file(client, other, "index.html"),
            save_file(client, other, "index.html", "x", None),
        ):
            assert r.status_code == 404 and code(r) == "site_not_found"

    client.post(f"{API}/users", json={"username": "victor", "role": "viewer",
                                      "password": "temporary-pass-1"})  # fmt: skip
    with other_user(client) as viewer:
        login(viewer, "victor", "temporary-pass-1")
        viewer.post(f"{API}/auth/password", json={"current": "temporary-pass-1", "new": STRONG})
        assert viewer.get(f"{url}/files").status_code == 200
        assert read_file(viewer, url, "index.html").json()["sha256"] == base
        r = save_file(viewer, url, "index.html", "x", base)
        assert r.status_code == 403 and code(r) == "insufficient_role"


def test_editing_needs_a_deployed_site(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    client.portal.call(rt.jobs.stop)  # the deploy job stays queued
    url = host_before_deploy(client, deploy_nginx(client, "Vitrine", 8190).json()["app"]["id"])
    assert client.get(f"{url}/files").json() == {"files": [], "truncated": False}
    refused = save_file(client, url, "index.html", "x", None)
    assert refused.status_code == 409 and code(refused) == "conflict"
    assert "not deployed" in refused.json()["error"]["message"]


def test_a_staged_edit_is_removed_if_it_cannot_be_queued(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin(client)
    url = main_site_url(client)
    base = read_file(client, url, "index.html").json()["sha256"]

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(client.app.state.runtime.jobs, "add", broken)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        save_file(client, url, "index.html", "x", base)
    assert sorted(p.name for p in volumes_of(client).iterdir()) == NGINX_VOLUMES
