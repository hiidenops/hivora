import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from helpers import API, admin, code, wait_job

from hivora.pyapps.analyze import ProjectError, analyze

BOT_JDR = {
    "bot.discord/Dockerfile": (
        "FROM python:3.12-slim\nWORKDIR /app\nRUN apt-get update && apt-get install -y "
        "--no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*\n"
        "COPY app/requirements.txt .\nRUN pip install -r requirements.txt\n"
        'CMD ["python", "bot_jdr.py"]\n'
    ),
    "bot.discord/docker-compose.yml": """version: "3.9"
name: bot_jdr_stack
networks:
  public_net:
    driver: bridge
services:
  bot_jdr:
    build:
      context: .
      dockerfile: Dockerfile
    image: bot_jdr:latest
    container_name: bot_jdr
    restart: unless-stopped
    networks:
      - public_net
    environment:
      TZ: Europe/Paris
      DISCORD_TOKEN: ${DISCORD_TOKEN}
    volumes:
      - ./app:/app
""",
    "bot.discord/app/bot_jdr.py": (
        "import os\nTOKEN = os.getenv('DISCORD_TOKEN')\n"
        "if __name__ == '__main__':\n    print('bot')\n"
    ),
    "bot.discord/app/requirements.txt": "discord.py==2.4.0\n",
    "bot.discord/app/__pycache__/bot_jdr.cpython-313.pyc": "x",
    "bot.discord/scripts/redeploy_bot.sh": "#!/bin/sh\n",
}

ZOMBOCITY = {
    "Dockerfile": 'FROM python:3.13-slim\nWORKDIR /app\nCMD ["python", "bot.py"]\n',
    "docker-compose.yml": """name: bot_zombocity_stack
services:
  bot_zombocity:
    build: .
    env_file:
      - .env
    environment:
      TZ: Europe/Paris
    volumes:
      - ./app:/app
      - ./data:/data
""",
    ".env": "DISCORD_TOKEN=abc123\nPZ_HOST=203.0.113.9\n",
    "app/bot.py": "import os\nport = os.environ.get('PZ_PORT', '16261')\n",
    "app/config.py": "import os\nX = os.environ['GUILD_ID']\n",
    "app/requirements.txt": "discord.py\n",
    "data/state.json": "{}",
    "README.md": "# bot",
}


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def analyze_bytes(tmp_path: Path, files: dict[str, str]) -> Any:
    path = tmp_path / "p.zip"
    path.write_bytes(make_zip(files))
    return analyze(str(path), "fallback")


def test_analysis_of_real_world_bots(tmp_path: Path) -> None:
    a = analyze_bytes(tmp_path, BOT_JDR)
    assert (a.name, a.python, a.requirements, a.workdir) == (
        "bot_jdr", "3.12", "app/requirements.txt", "/app"
    )  # fmt: skip
    assert a.entry == ["python", "bot_jdr.py"] and a.apt == ["ffmpeg"]
    assert [(m.source, m.target, m.data) for m in a.mounts] == [("app", "/app", False)]
    [token] = a.env
    assert token.key == "DISCORD_TOKEN" and token.secret and token.value == ""

    z = analyze_bytes(tmp_path, ZOMBOCITY)
    assert z.name == "bot_zombocity" and z.python == "3.13" and z.entry == ["python", "bot.py"]
    assert [(m.source, m.target, m.data) for m in z.mounts] == [
        ("app", "/app", False), ("data", "/data", True),
    ]  # fmt: skip
    env = {e.key: e for e in z.env}
    assert env["DISCORD_TOKEN"].value == "abc123" and env["DISCORD_TOKEN"].secret
    assert env["PZ_HOST"].value == "203.0.113.9" and not env["PZ_HOST"].secret
    assert env["PZ_PORT"].value == "16261" and "GUILD_ID" in env

    plain = analyze_bytes(tmp_path, {"main.py": "if __name__ == '__main__':\n  pass\n",
                                     "requirements.txt": "requests\n"})  # fmt: skip
    assert plain.entry == ["python", "main.py"] and plain.workdir == "/app"
    assert plain.requirements == "requirements.txt" and plain.python == "3.13"

    with pytest.raises(ProjectError):
        analyze_bytes(tmp_path, {"../evil.py": "x"})
    with pytest.raises(ProjectError):
        analyze_bytes(tmp_path, {"README.md": "no code"})


def test_deploy_a_python_project_then_send_new_code(client: Any) -> None:
    admin(client)
    rt = client.app.state.runtime
    found = client.post(f"{API}/apps/python/analyze", params={"filename": "zombocity.zip"},
                        content=make_zip(ZOMBOCITY)).json()  # fmt: skip
    assert found["entry"] == ["python", "bot.py"] and found["token"]
    body = {**found, "name": "Zombocity", "zone": None,
            "env": [{**e, "value": e["value"] or "1"} for e in found["env"]]}  # fmt: skip
    for key in ("notes", "files", "size"):
        body.pop(key)
    body["ports"] = []
    deployed = client.post(f"{API}/apps/python", json=body).json()
    assert wait_job(client, deployed["job"]["id"])["status"] == "succeeded"
    app_id = deployed["app"]["id"]

    compose = yaml.safe_load(client.get(f"{API}/apps/{app_id}/compose").json()["compose_yaml"])
    svc = compose["services"]["app"]
    assert svc["image"].startswith("python:3.13-slim@sha256:")
    script = svc["command"][2]
    assert "pip install -q -r /app/requirements.txt" in script and "exec python bot.py" in script
    assert svc["environment"]["PZ_HOST"] == "203.0.113.9"
    assert svc["environment"]["DISCORD_TOKEN"].startswith("${HV_SECRET_")  # never in clear
    assert "abc123" not in yaml.safe_dump(compose)
    targets = {v["target"] for v in svc["volumes"]}
    assert targets == {"/app", "/data", "/venv"}
    base = rt.settings.volumes_root / "zombocity"
    assert (base / "app" / "bot.py").exists() and (base / "data" / "state.json").exists()
    assert not (base / "app" / "README.md").exists()  # outside the mounted folders
    assert client.get(f"{API}/apps/{app_id}").json()["python"] is True

    # New code: the code folder is replaced, data kept, then a restart.
    (base / "data" / "state.json").write_text('{"kept": true}')
    newer = {**ZOMBOCITY, "app/bot.py": "print('v2')\n"}
    newer.pop("app/config.py")
    job = client.post(f"{API}/apps/{app_id}/python/code", content=make_zip(newer)).json()
    assert job["kind"] == "restart"
    assert (base / "app" / "bot.py").read_text() == "print('v2')\n"
    assert not (base / "app" / "config.py").exists()
    assert (base / "data" / "state.json").read_text() == '{"kept": true}'

    bad = client.post(f"{API}/apps/python/analyze", content=b"not a zip")
    assert bad.status_code == 422 and code(bad) == "invalid_project"
