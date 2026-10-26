from __future__ import annotations

from pathlib import Path

from tests.helpers import DEV_TENANT
from app.context.models import TrustLevel
from app.core.config import get_settings
from app.graph.repository import GraphRepository
from app.services.context_builder import ContextBuilder


def test_ontology_artifact_exists_and_has_core_terms() -> None:
    ontology_path = Path("ontology/pulseops.ttl")
    assert ontology_path.exists()

    content = ontology_path.read_text(encoding="utf-8")
    assert "pulseops:Incident" in content
    assert "pulseops:Service" in content
    assert "pulseops:affects" in content
    assert "pulseops:hasLog" in content


def test_graph_projection_is_deterministic() -> None:
    repo = GraphRepository(database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    first = repo.project_operational_graph()
    second = repo.project_operational_graph()

    assert first == second
    assert any(node["id"] == "INC-1007" for node in first["nodes"])
    assert any(rel["type"] == "AFFECTS" for rel in first["relationships"])


def test_context_builder_creates_incident_context() -> None:
    repo = GraphRepository(database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    repo.project_operational_graph()

    builder = ContextBuilder(graph_repository=repo, database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    context = builder.build_incident_context("INC-1007")

    assert context.incident == "INC-1007"
    assert context.affected_service == "svc-payment"
    assert len(context.evidence) >= 3
    assert any(item.trust_level == TrustLevel.TRUSTED for item in context.evidence)
    assert context.model_dump_json()
