from fastapi.testclient import TestClient

from app.main import app


def test_app_starts() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["app"] == "PulseOps"
        assert payload["environment"] == "development"
