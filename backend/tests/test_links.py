from typing import Any

from helpers import API, admin, code, wait_job
from test_templates import LINKED_DB, LINKING_TOOL

PASSWORD = "db-password-123"


def deploy(client: Any, template: str, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    r = client.post(f"{API}/apps", json={"template": template, "name": name, "inputs": inputs})
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["job"]["id"])["status"] == "succeeded"
    app: dict[str, Any] = r.json()["app"]
    return app


def env_of(client: Any, slug: str) -> str:
    rt = client.app.state.runtime
    path = rt.settings.apps_dir / slug / ".env"
    return path.read_text() if path.exists() else ""


def settings(client: Any, app_id: int, **inputs: Any) -> None:
    r = client.put(f"{API}/apps/{app_id}/settings", json={"inputs": inputs})
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["id"])["status"] == "succeeded"


def linked_pair(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """A test database and a tool linked to it (the test templates of test_templates)."""
    admin(client)
    rt = client.app.state.runtime
    rt.catalog.add_custom(LINKED_DB)
    rt.catalog.add_custom(LINKING_TOOL)
    db = deploy(client, "testdb", "Base", {"db_password": PASSWORD, "db_user": "admin"})
    tool = deploy(client, "testtool", "Outil", {"database": db["slug"]})
    return db, tool


def test_a_tool_reaches_the_app_it_links_and_its_password_only_when_asked(client: Any) -> None:
    db, tool = linked_pair(client)
    compose = client.get(f"{API}/apps/{tool['id']}/compose").json()["compose_yaml"]
    assert "DB_HOST: base-server-1" in compose
    assert "DB_URL: admin@base-server-1/app" in compose  # the database's own form
    assert "name: base_default" in compose and "external: true" in compose  # its network joined
    assert PASSWORD not in compose
    assert "HV_SECRET_LINK_DATABASE_PASSWORD" not in env_of(client, tool["slug"])  # not asked

    settings(client, tool["id"], database=db["slug"], auto_login=True)
    assert f"HV_SECRET_LINK_DATABASE_PASSWORD='{PASSWORD}'" in env_of(client, tool["slug"])
    assert PASSWORD not in client.get(f"{API}/apps/{tool['id']}/compose").json()["compose_yaml"]

    settings(client, tool["id"], database=db["slug"], auto_login=False)  # unchecked: gone
    assert "HV_SECRET_LINK_DATABASE_PASSWORD" not in env_of(client, tool["slug"])
    assert PASSWORD not in env_of(client, tool["slug"])


def test_a_link_to_a_missing_or_foreign_app_is_refused(client: Any) -> None:
    linked_pair(client)
    for target in ("nulle-part", "outil"):  # no such app; an app of another template
        r = client.post(f"{API}/apps", json={"template": "testtool", "name": f"Lien {target}",
                                             "inputs": {"database": target}})  # fmt: skip
        assert r.status_code == 422 and code(r) == "link_invalid", (target, r.text)
    nginx = deploy(client, "nginx", "Web", {"web_port": 8311})
    r = client.post(f"{API}/apps", json={"template": "testtool", "name": "Lien web",
                                         "inputs": {"database": nginx["slug"]}})  # fmt: skip
    assert r.status_code == 422 and code(r) == "link_invalid"


def test_a_linked_app_is_not_removed_before_its_tools(client: Any) -> None:
    db, tool = linked_pair(client)
    r = client.delete(f"{API}/apps/{db['id']}")
    assert r.status_code == 409 and code(r) == "app_linked"
    assert r.json()["error"]["details"]["tools"] == "Outil"
    gone = client.delete(f"{API}/apps/{tool['id']}")
    assert gone.status_code == 202 and wait_job(client, gone.json()["id"])["status"] == "succeeded"
    r = client.delete(f"{API}/apps/{db['id']}")
    assert r.status_code == 202, r.text


def test_only_the_allowed_templates_that_say_how_to_reach_them_can_be_linked(client: Any) -> None:
    linked_pair(client)
    rt = client.app.state.runtime
    # A database of another kind (a connection, but not among the tool's templates), and a
    # template the tool allows that does not say how to reach it.
    rt.catalog.add_custom(LINKED_DB.replace("slug: testdb", "slug: otherdb"))
    rt.catalog.add_custom(LINKED_DB.replace("slug: testdb", "slug: nodb").split("connection:")[0])
    rt.catalog.add_custom(LINKING_TOOL.replace("slug: testtool", "slug: widetool")
                          .replace("templates: [testdb]", "templates: [testdb, nodb]"))  # fmt: skip
    other = deploy(client, "otherdb", "Autre", {"db_password": PASSWORD})
    bare = deploy(client, "nodb", "Nue", {"db_password": PASSWORD})
    for tool, target in (("testtool", other["slug"]), ("widetool", bare["slug"])):
        r = client.post(f"{API}/apps", json={"template": tool, "name": f"{tool} {target}",
                                             "inputs": {"database": target}})  # fmt: skip
        assert r.status_code == 422 and code(r) == "link_invalid", (tool, target, r.text)
