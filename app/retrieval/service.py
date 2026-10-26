from __future__ import annotations

from app.core.config import get_settings
from app.graph.repository import GraphRepository
from app.retrieval.models import IncidentRetrievalResult
from app.repositories.incident_repository import (
    DeploymentRepository,
    IncidentRepository,
    LogRepository,
    MetricRepository,
    RepositoryMappingRepository,
    RepositoryRepository,
    ServiceRepository,
)
from app.services.context_builder import ContextBuilder


class IncidentRetrievalService:
    """Read-only, deterministic retrieval layer for operational incident evidence."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        tenant_id: str,
        max_logs: int = 10,
        max_metrics: int = 10,
        max_related_incidents: int = 10,
        max_related_services: int = 10,
    ) -> None:
        self.database_url = database_url or get_settings().database_url
        self.tenant_id = tenant_id  # fixed at construction from the authenticated request; never a tool argument
        self.max_logs = max_logs
        self.max_metrics = max_metrics
        self.max_related_incidents = max_related_incidents
        self.max_related_services = max_related_services

    def get_service_repository(self, service_id: str) -> str | None:
        mapping = RepositoryMappingRepository(self.database_url, self.tenant_id).get_for_service(service_id)
        if mapping is None:
            return None
        repository = RepositoryRepository(self.database_url, self.tenant_id).get_repository(mapping.repository_id)
        if repository is None:
            return None
        return repository.repository_id

    def get_service_dependencies(self, service_id: str) -> list[str]:
        projection = GraphRepository(self.database_url, self.tenant_id).project_operational_graph()
        dependencies = [
            relationship["target_id"]
            for relationship in projection["relationships"]
            if relationship["source_id"] == service_id and relationship["type"] == "DEPENDS_ON"
        ]
        return sorted(set(dependencies))

    def get_related_incidents(self, service_id: str, incident_id: str | None = None) -> list[str]:
        incidents = IncidentRepository(self.database_url, self.tenant_id).list_incidents()
        related = [
            incident.incident_id for incident in incidents if incident.service_id == service_id
        ]
        # Only the incident being investigated (when known) is hoisted; there is no hard-coded default incident.
        if incident_id is not None and incident_id in related:
            related = [incident_id] + [item for item in related if item != incident_id]
        return related[: self.max_related_incidents]

    def get_incident_context(self, incident_id: str) -> IncidentRetrievalResult:
        incident_repo = IncidentRepository(self.database_url, self.tenant_id)
        incident = incident_repo.get_incident(incident_id)
        if incident is None:
            raise ValueError(f"Incident '{incident_id}' not found")

        service = ServiceRepository(self.database_url, self.tenant_id).get_service(incident.service_id)
        if service is None:
            raise ValueError(f"Service '{incident.service_id}' not found")

        deployment_ids = [
            deployment.deployment_id
            for deployment in DeploymentRepository(self.database_url, self.tenant_id).list_deployments_for_service(
                incident.service_id
            )
        ]

        repository_id = self.get_service_repository(incident.service_id)
        related_incidents = self.get_related_incidents(incident.service_id, incident_id=incident.incident_id)
        related_services = self._collect_related_services(incident.service_id)

        log_entries = LogRepository(self.database_url, self.tenant_id).list_logs_for_incident(incident_id)[: self.max_logs]
        metric_entries = MetricRepository(self.database_url, self.tenant_id).list_metrics_for_incident(incident_id)[
            : self.max_metrics
        ]
        context = ContextBuilder(database_url=self.database_url, tenant_id=self.tenant_id).build_incident_context(incident_id)

        return IncidentRetrievalResult(
            incident_id=incident.incident_id,
            service_id=incident.service_id,
            title=incident.title,
            severity=incident.severity.value,
            status=incident.status.value,
            repository_id=repository_id,
            deployment_ids=deployment_ids[: self.max_related_services],
            related_services=related_services[: self.max_related_services],
            related_incidents=related_incidents[: self.max_related_incidents],
            logs=[log.message for log in log_entries],
            metrics=[metric.metric_name for metric in metric_entries],
            context=context.model_dump(mode="json"),
        )

    def _collect_related_services(self, service_id: str) -> list[str]:
        projection = GraphRepository(self.database_url, self.tenant_id).project_operational_graph()
        service_ids = {
            node["id"]
            for node in projection["nodes"]
            if "Service" in node.get("labels", [])
        }
        related = set()
        for relationship in projection["relationships"]:
            source_id = relationship["source_id"]
            target_id = relationship["target_id"]
            if source_id == service_id and target_id in service_ids and target_id != service_id:
                related.add(target_id)
            if target_id == service_id and source_id in service_ids and source_id != service_id:
                related.add(source_id)
        return sorted(related)[: self.max_related_services]
