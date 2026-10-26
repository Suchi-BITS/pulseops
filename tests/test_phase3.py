from fastapi.testclient import TestClient

from tests.helpers import DEV_TENANT
from app.core.config import get_settings
from app.main import app
from app.retrieval.service import IncidentRetrievalService


def test_incident_retrieval_service_returns_context() -> None:
    service = IncidentRetrievalService(database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    result = service.get_incident_context("INC-1007")

    assert result.incident_id == "INC-1007"
    assert result.service_id == "svc-payment"
    assert result.repository_id == "repo-payment"
    assert result.logs
    assert result.metrics
    assert result.deployment_ids
    assert result.context is not None


def test_incident_retrieval_supports_related_incident_queries() -> None:
    service = IncidentRetrievalService(database_url=get_settings().database_url, tenant_id=DEV_TENANT)

    related_incidents = service.get_related_incidents("svc-payment")
    assert "INC-1007" in related_incidents
    assert service.get_service_repository("svc-payment") == "repo-payment"
    assert service.get_service_dependencies("svc-payment") == []


def test_retrieval_api_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/retrieval/incidents/INC-1007")

    assert response.status_code == 200
    payload = response.json()
    assert payload["incident_id"] == "INC-1007"
    assert payload["service_id"] == "svc-payment"
    assert payload["repository_id"] == "repo-payment"
    assert "INC-1007" in payload["related_incidents"]
