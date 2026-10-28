"""HIVORA_GAMES=off (the installer's --no-games): no game in the catalog, none deployed;
the other templates as usual."""

import os
from pathlib import Path
from typing import Any

from conftest import FAKE
from fastapi.testclient import TestClient
from helpers import API, admin, code

from hivora.core.config import Settings
from hivora.docker_gateway.fake import FakeDockerGateway
from hivora.main import create_app
from hivora.runtime import Runtime


def test_the_games_turned_off(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", volumes_root=tmp_path / "srv",
                        catalog_dir=Path(__file__).parents[2] / "templates",
                        dev_insecure_cookies=True, puid=os.getuid(), pgid=os.getgid(),
                        host_lan_ip="192.168.1.10", games=False)  # fmt: skip
    runtime = Runtime.build(settings, gateway=FakeDockerGateway(), compose_cmd=FAKE)
    with TestClient(create_app(runtime=runtime)) as client:
        admin(client)
        listed: list[dict[str, Any]] = client.get(f"{API}/templates").json()
        assert listed and all(t["category"] != "games" for t in listed)
        assert any(t["slug"] == "vaultwarden" for t in listed)
        body = {"template": "minecraft", "name": "cube", "inputs": {"eula": True}}
        refused = client.post(f"{API}/apps", json=body)
        assert refused.status_code == 403 and code(refused) == "games_disabled"
        assert client.get(f"{API}/apps").json() == []
