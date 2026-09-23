from fastapi.testclient import TestClient

from hivora import __version__
from hivora.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
