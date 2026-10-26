from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.context.models import EvidenceRecord, EvidenceSourceType, InvestigationContext, TrustLevel
from app.graph.repository import GraphRepository
from app.repositories.incident_repository import (
    DeploymentRepository,
    IncidentRepository,
    LogRepository,
    MetricRepository,
    RepositoryMappingRepository,
    RepositoryRepository,
    ServiceRepository,
)


class ContextBuilder:
    """Deterministic builder for investigation context from SQLite and graph-derived relationships."""

    def __init__(
        self,
        graph_repository: GraphRepository | None = None,
        database_url: str | None = None,
        *,
        tenant_id: str,
        max_logs: int = 5,
        max_metrics: int = 5,
        max_deployments: int = 3,
        max_graph_relationships: int = 10,
        max_repository_items: int = 5,
    ) -> None:
        self.database_url = database_url or get_settings().database_url
        self.tenant_id = tenant_id
        if graph_repository is not None and graph_repository.tenant_id != tenant_id:
            raise ValueError("graph repository belongs to a different tenant")
        self.graph_repository = graph_repository or GraphRepository(self.database_url, tenant_id)
        self.max_logs = max_logs
        self.max_metrics = max_metrics
        self.max_deployments = max_deployments
        self.max_graph_relationships = max_graph_relationships
        self.max_repository_items = max_repository_items
        self.incident_repository = IncidentRepository(self.database_url, tenant_id)
        self.service_repository = ServiceRepository(self.database_url, tenant_id)
        self.log_repository = LogRepository(self.database_url, tenant_id)
        self.metric_repository = MetricRepository(self.database_url, tenant_id)
        self.deployment_repository = DeploymentRepository(self.database_url, tenant_id)
        self.repository_repository = RepositoryRepository(self.database_url, tenant_id)
        self.repository_mapping_repository = RepositoryMappingRepository(self.database_url, tenant_id)

    def build_incident_context(self, incident_id: str) -> InvestigationContext:
        incident = self.incident_repository.get_incident(incident_id)
        if incident is None:
            raise ValueError(f"Incident not found: {incident_id}")

        service = self.service_repository.get_service(incident.service_id)
        if service is None:
            raise ValueError(f"Service not found: {incident.service_id}")

        graph_context = self.graph_repository.get_incident_graph_context(incident_id)
        evidence: list[EvidenceRecord] = []

        evidence.append(
            EvidenceRecord(
                evidence_id=f"evidence-{incident_id}-incident",
                source_type=EvidenceSourceType.INCIDENT,
                source_id=incident.incident_id,
                timestamp=incident.started_at,
                content=f"{incident.title}: {incident.description}",
                trust_level=TrustLevel.TRUSTED,
                relevance=1.0,
                metadata={"service_id": incident.service_id},
            )
        )

        logs = self.log_repository.list_logs_for_incident(incident_id)[: self.max_logs]
        for log in logs:
            evidence.append(
                EvidenceRecord(
                    evidence_id=f"evidence-{log.log_id}",
                    source_type=EvidenceSourceType.LOG,
                    source_id=log.log_id,
                    timestamp=log.timestamp,
                    content=log.message,
                    trust_level=TrustLevel.TRUSTED,
                    relevance=0.9,
                    metadata={"level": log.level.value, "source": log.source},
                )
            )

        metrics = self.metric_repository.list_metrics_for_incident(incident_id)[: self.max_metrics]
        for metric in metrics:
            evidence.append(
                EvidenceRecord(
                    evidence_id=f"evidence-{metric.metric_id}",
                    source_type=EvidenceSourceType.METRIC,
                    source_id=metric.metric_id,
                    timestamp=metric.timestamp,
                    content=f"{metric.metric_name}={metric.value}{metric.unit or ''}",
                    trust_level=TrustLevel.TRUSTED,
                    relevance=0.8,
                    metadata={"metric_name": metric.metric_name, "source": metric.source},
                )
            )

        deployments = self.deployment_repository.list_deployments_for_service(incident.service_id)[
            : self.max_deployments
        ]
        for deployment in deployments:
            evidence.append(
                EvidenceRecord(
                    evidence_id=f"evidence-{deployment.deployment_id}",
                    source_type=EvidenceSourceType.DEPLOYMENT,
                    source_id=deployment.deployment_id,
                    timestamp=deployment.deployed_at,
                    content=f"Deployment {deployment.version} to {deployment.environment}",
                    trust_level=TrustLevel.CONTROLLED,
                    relevance=0.7,
                    metadata={"version": deployment.version, "status": deployment.status.value},
                )
            )

        mapping = self.repository_mapping_repository.get_for_service(incident.service_id)
        if mapping is not None:
            repository = self.repository_repository.get_repository(mapping.repository_id)
            if repository is not None:
                evidence.append(
                    EvidenceRecord(
                        evidence_id=f"evidence-{repository.repository_id}",
                        source_type=EvidenceSourceType.REPOSITORY,
                        source_id=repository.repository_id,
                        timestamp=datetime.now(timezone.utc),
                        content=f"Repository {repository.owner}/{repository.name} active={repository.active}",
                        trust_level=TrustLevel.CONTROLLED,
                        relevance=0.6,
                        metadata={"branch": mapping.branch, "path_prefix": mapping.path_prefix},
                    )
                )

        graph_relationships = graph_context.get("graph_relationships", [])[: self.max_graph_relationships]
        for relationship in graph_relationships:
            evidence.append(
                EvidenceRecord(
                    evidence_id=f"evidence-graph-{relationship}",
                    source_type=EvidenceSourceType.GRAPH_RELATIONSHIP,
                    source_id=relationship,
                    timestamp=datetime.now(timezone.utc),
                    content=relationship,
                    trust_level=TrustLevel.CONTROLLED,
                    relevance=0.5,
                    metadata={"relationship": relationship},
                )
            )

        evidence = sorted(
            evidence,
            key=lambda item: (
                item.timestamp or datetime.min.replace(tzinfo=timezone.utc),
                item.source_id,
            ),
            reverse=True,
        )

        all_incidents = self.incident_repository.list_incidents()
        historical_incidents = [
            incident_record.incident_id
            for incident_record in all_incidents
            if incident_record.incident_id != incident_id and incident_record.service_id == service.service_id
        ]

        missing_information = []
        if not logs:
            missing_information.append("No recent logs were available for the affected incident.")
        if not metrics:
            missing_information.append("No recent metrics were available for the affected incident.")
        if not deployments:
            missing_information.append("No deployment history was available for the affected service.")

        return InvestigationContext(
            incident=incident.incident_id,
            affected_service=service.service_id,
            related_services=graph_context.get("related_services", []),
            evidence=evidence,
            recent_deployments=graph_context.get("recent_deployments", [])[: self.max_deployments],
            historical_incidents=historical_incidents[: self.max_repository_items],
            repository_context=graph_context.get("repository_context", [])[: self.max_repository_items],
            graph_relationships=graph_context.get("graph_relationships", [])[: self.max_graph_relationships],
            missing_information=missing_information,
            metadata={
                "service_name": service.service_name,
                "environment": service.environment,
                "max_logs": self.max_logs,
                "max_metrics": self.max_metrics,
                "max_deployments": self.max_deployments,
            },
        )
