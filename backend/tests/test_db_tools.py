import sqlite3
from typing import Any

import yaml
from helpers import API, admin, code, wait_job

DB_PASSWORD = "mariadb-pass-123"
PG_PASSWORD = "postgres-pass-123"


def deploy(client: Any, template: str, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    r = client.post(f"{API}/apps", json={"template": template, "name": name, "inputs": inputs})
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["job"]["id"])["status"] == "succeeded"
    app: dict[str, Any] = r.json()["app"]
    return app


def compose_of(client: Any, app_id: int) -> dict[str, Any]:
    text = client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"]
    compose: dict[str, Any] = yaml.safe_load(text)
    return compose


def env_file(client: Any, slug: str) -> str:
    path = client.app.state.runtime.settings.apps_dir / slug / ".env"
    return path.read_text() if path.exists() else ""


def update(client: Any, app_id: int, inputs: dict[str, Any]) -> None:
    r = client.put(f"{API}/apps/{app_id}/settings", json={"inputs": inputs})
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["id"])["status"] == "succeeded"


def test_phpmyadmin_opens_the_linked_mariadb_and_logs_in_only_when_asked(client: Any) -> None:
    admin(client)
    db = deploy(client, "mariadb", "Base", {"db_password": DB_PASSWORD})
    pma = deploy(client, "phpmyadmin", "Admin", {"web_port": 8401, "database": db["slug"]})
    compose = compose_of(client, pma["id"])
    env = compose["services"]["server"]["environment"]
    assert (env["PMA_HOST"], env["PMA_PORT"]) == ("base-server-1", "3306")
    assert "PMA_USER" not in env and "PMA_PASSWORD" not in env  # the login page, as usual
    assert compose["networks"]["reach0"] == {"name": "base_default", "external": True}

    update(client, pma["id"], {"web_port": 8401, "database": db["slug"], "auto_login": True})
    env = compose_of(client, pma["id"])["services"]["server"]["environment"]
    assert env["PMA_USER"] == "app"
    assert env["PMA_PASSWORD"] == "${HV_SECRET_LINK_DATABASE_PASSWORD:-}"  # a reference only
    assert f"HV_SECRET_LINK_DATABASE_PASSWORD='{DB_PASSWORD}'" in env_file(client, pma["slug"])

    update(client, pma["id"], {"web_port": 8401, "database": db["slug"], "auto_login": False})
    assert "PMA_USER" not in compose_of(client, pma["id"])["services"]["server"]["environment"]
    assert DB_PASSWORD not in env_file(client, pma["slug"])

    alone = deploy(client, "phpmyadmin", "Libre", {"web_port": 8402})  # no database: as 1.0.0
    env = compose_of(client, alone["id"])["services"]["server"]["environment"]
    assert "PMA_HOST" not in env and env["PMA_ARBITRARY"] == "1"
    wrong = client.post(f"{API}/apps", json={"template": "phpmyadmin", "name": "Faux",
                                             "inputs": {"database": alone["slug"]}})  # fmt: skip
    assert wrong.status_code == 422 and code(wrong) == "link_invalid"  # not a MariaDB


def test_pgadmin_registers_the_linked_postgresql(client: Any) -> None:
    admin(client)
    pg = deploy(client, "postgresql", "Entrepot", {"db_password": PG_PASSWORD, "db_name": "stock"})
    common = {"web_port": 8403, "email": "admin@example.org", "password": "pgadmin-pass-12"}
    tool = deploy(client, "pgadmin", "Pg", {**common, "database": pg["slug"]})
    compose = compose_of(client, tool["id"])
    svc = compose["services"]["server"]
    assert svc["environment"]["PGADMIN_SERVER_JSON_FILE"] == "/pgadmin4/servers-hivora.json"
    servers = next(c["content"] for c in compose["configs"].values()
                   if "servers-hivora" in str(c) or "Servers" in str(c.get("content")))  # fmt: skip
    assert '"Host": "entrepot-server-1"' in servers and '"Port": 5432' in servers
    assert '"MaintenanceDB": "stock"' in servers and '"Username": "app"' in servers
    assert PG_PASSWORD not in yaml.safe_dump(compose)  # pgAdmin asks for it, then saves it
    assert PG_PASSWORD not in env_file(client, tool["slug"])
    bare = deploy(client, "pgadmin", "Seul", {**common, "web_port": 8404})
    env = compose_of(client, bare["id"])["services"]["server"]["environment"]
    assert "PGADMIN_SERVER_JSON_FILE" not in env


def test_database_settings_reach_the_server_and_odd_ones_are_refused(client: Any) -> None:
    admin(client)
    maria = deploy(client, "mariadb", "Reglee", {
        "db_password": DB_PASSWORD, "max_connections": 300, "charset": "latin1",
        "innodb_buffer_pool": "1G", "extra_args": "--max-allowed-packet=64M --wait-timeout=600",
    })  # fmt: skip
    command = compose_of(client, maria["id"])["services"]["server"]["command"]
    assert command == (
        "--character-set-server=latin1 --max-connections=300 "
        "--innodb-buffer-pool-size=1G --max-allowed-packet=64M --wait-timeout=600"
    )
    slow = "-c log_min_duration_statement=500"
    pg = deploy(client, "postgresql", "Pg", {"db_password": PG_PASSWORD, "extra_args": slow})
    assert compose_of(client, pg["id"])["services"]["server"]["command"] == (
        "postgres -c max_connections=100 -c shared_buffers=128MB -c work_mem=4MB "
        "-c log_min_duration_statement=500")  # fmt: skip
    for template, extra in (("mariadb", "--a=1; rm -rf /"), ("mariadb", "--a=$(id)"),
                            ("mariadb", "-c x=1"), ("postgresql", "-c a=1 && reboot"),
                            ("postgresql", "--max-connections=5")):  # fmt: skip
        r = client.post(f"{API}/apps", json={"template": template, "name": "X",
                        "inputs": {"db_password": DB_PASSWORD, "extra_args": extra}})  # fmt: skip
        assert r.status_code == 422 and code(r) == "form_invalid", (template, extra)


def test_databases_and_tools_deployed_in_1_0_0_are_offered_1_1_0(client: Any) -> None:
    admin(client)
    db = deploy(client, "mariadb", "Ancienne", {"db_password": DB_PASSWORD})
    pma = deploy(client, "phpmyadmin", "Outil", {"web_port": 8405})
    rt = client.app.state.runtime
    with sqlite3.connect(rt.settings.db_path) as conn:  # deployed from the 1.0.0 templates
        conn.execute("UPDATE template_version SET version = '1.0.0' "
                     "WHERE slug IN ('mariadb', 'phpmyadmin')")  # fmt: skip
    for app in (db, pma):
        status = client.get(f"{API}/apps/{app['id']}/upgrade").json()
        assert status["available"] and (status["current"], status["latest"]) == ("1.0.0", "1.1.0")
        job = client.post(f"{API}/apps/{app['id']}/upgrade", json={}).json()
        assert wait_job(client, job["id"])["status"] == "succeeded"
    assert "--max-connections=151" in compose_of(client, db["id"])["services"]["server"]["command"]
    update(client, pma["id"], {"web_port": 8405, "database": db["slug"]})  # now it can link
    assert compose_of(client, pma["id"])["services"]["server"]["environment"]["PMA_HOST"] == (
        "ancienne-server-1")  # fmt: skip
