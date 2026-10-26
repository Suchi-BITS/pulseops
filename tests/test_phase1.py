from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.domain import Incident, IncidentStatus, IncidentSeverity, Service
from app.repositories.incident_repository import IncidentRepository
from app.services.incident_service import IncidentService
from tests.helpers import DEV_IDENTITY, DEV_TENANT


def test_service_model_creation() -> None:
    service = Service(
        service_id="svc-payment",
        service_name="payment-service",
        owner_team="payments",
        environment="production",
        repository_id="repo-payment",
        description="Handles payment transactions",
        created_at=datetime.now(timezone.utc),
    )

    assert service.service_id == "svc-payment"
    assert service.service_name == "payment-service"


def test_incident_repository_roundtrip() -> None:
    settings = get_settings()
    repository = IncidentRepository(database_url=settings.database_url, tenant_id=DEV_TENANT)

    incident = Incident(
        incident_id="INC-TEST-REPO-01",
        service_id="svc-payment",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        title="Payment service latency spike",
        description="Elevated latency and error rate during payment processing",
        environment="production",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    repository.create_incident(incident)
    stored = repository.get_incident("INC-TEST-REPO-01")

    assert stored is not None
    assert stored.incident_id == "INC-TEST-REPO-01"
    assert stored.service_id == "svc-payment"


def test_incident_service_creates_incident() -> None:
    settings = get_settings()
    service = IncidentService(database_url=settings.database_url, tenant_id=DEV_TENANT)

    incident = service.create_incident(
        service_id="svc-payment",
        severity="high",
        title="Payment service latency spike",
        description="Elevated latency and error rate during payment processing",
        environment="production",
    )

    assert incident.incident_id.startswith("INC-")
    assert incident.service_id == "svc-payment"
    assert incident.severity == IncidentSeverity.HIGH
    assert incident.status == IncidentStatus.OPEN


def test_incident_api_endpoints() -> None:
    client = TestClient(app)

    response = client.post(
        "/incidents",
        json={
            "service_id": "svc-payment",
            "severity": "high",
            "title": "Payment service latency spike",
            "description": "Elevated latency and error rate during payment processing",
            "environment": "production",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["service_id"] == "svc-payment"
    assert payload["severity"] == "high"
    assert payload["status"] == "open"
    assert payload["incident_id"].startswith("INC-")

    list_response = client.get("/incidents")
    assert list_response.status_code == 200
    incident_ids = [item["incident_id"] for item in list_response.json()]
    assert payload["incident_id"] in incident_ids

    detail_response = client.get(f"/incidents/{payload['incident_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["incident_id"] == payload["incident_id"]
