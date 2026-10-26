from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.repositories.incident_repository import (
    DeploymentRepository,
    IncidentRepository,
    RepositoryMappingRepository,
    RepositoryRepository,
    ServiceRepository,
)


class GraphRepository:
    """Deterministic, tenant-scoped graph projection for the operational data model.

    The projection only ever contains the instances of one tenant (every repository it reads is bound to
    ``tenant_id``) and every node and relationship carries that ``tenant_id``. This is the contract a future
    Neo4j projection must keep: instances are tenant-tagged, the ontology is shared, and every retrieval is scoped.
    """

    def __init__(self, database_url: str, tenant_id: str) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id

    def project_operational_graph(self) -> dict[str, list[dict[str, Any]]]:
        services = ServiceRepository(self.database_url, self.tenant_id).list_services()
        incidents = IncidentRepository(self.database_url, self.tenant_id).list_incidents()
        repository_mapping = RepositoryMappingRepository(self.database_url, self.tenant_id)
        repository_repo = RepositoryRepository(self.database_url, self.tenant_id)
        deployment_repo = DeploymentRepository(self.database_url, self.tenant_id)

        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for service in services:
            nodes.append({
                "id": service.service_id,
                "labels": ["Service"],
                "properties": {
                    "service_name": service.service_name,
                    "owner_team": service.owner_team,
                    "environment": service.environment,
                },
            })

        for incident in incidents:
            nodes.append({
                "id": incident.incident_id,
                "labels": ["Incident"],
                "properties": {
                    "service_id": incident.service_id,
                    "severity": incident.severity.value,
                    "status": incident.status.value,
                    "title": incident.title,
                },
            })
            relationships.append({
                "source_id": incident.incident_id,
                "target_id": incident.service_id,
                "type": "AFFECTS",
                "properties": {"source": "sqlite"},
            })

            for log in self._list_logs(incident.incident_id):
                nodes.append({
                    "id": log.log_id,
                    "labels": ["Log"],
                    "properties": {"message": log.message, "level": log.level.value},
                })
                relationships.append({
                    "source_id": incident.incident_id,
                    "target_id": log.log_id,
                    "type": "HAS_LOG",
                    "properties": {"source": "sqlite"},
                })

            for metric in self._list_metrics(incident.incident_id):
                nodes.append({
                    "id": metric.metric_id,
                    "labels": ["Metric"],
                    "properties": {"name": metric.metric_name, "value": metric.value},
                })
                relationships.append({
                    "source_id": incident.incident_id,
                    "target_id": metric.metric_id,
                    "type": "HAS_METRIC",
                    "properties": {"source": "sqlite"},
                })

        for service in services:
            service_mapping = repository_mapping.get_for_service(service.service_id)
            if service_mapping is not None:
                repository = repository_repo.get_repository(service_mapping.repository_id)
                if repository is not None:
                    nodes.append({
                        "id": repository.repository_id,
                        "labels": ["Repository"],
                        "properties": {
                            "owner": repository.owner,
                            "name": repository.name,
                            "default_branch": repository.default_branch,
                        },
                    })
                    relationships.append({
                        "source_id": service.service_id,
                        "target_id": repository.repository_id,
                        "type": "IMPLEMENTED_BY",
                        "properties": {"branch": service_mapping.branch},
                    })

                    deployments = deployment_repo.list_deployments_for_service(service.service_id)
                    for deployment in deployments:
                        nodes.append({
                            "id": deployment.deployment_id,
                            "labels": ["Deployment"],
                            "properties": {
                                "version": deployment.version,
                                "environment": deployment.environment,
                                "status": deployment.status.value,
                            },
                        })
                        relationships.append({
                            "source_id": repository.repository_id,
                            "target_id": deployment.deployment_id,
                            "type": "HAS_DEPLOYMENT",
                            "properties": {"source": "sqlite"},
                        })
                        relationships.append({
                            "source_id": deployment.deployment_id,
                            "target_id": deployment.environment,
                            "type": "DEPLOYED_TO",
                            "properties": {"source": "sqlite"},
                        })

                    for other_service in services:
                        if other_service.service_id == service.service_id:
                            continue
                        if other_service.environment == service.environment:
                            relationships.append({
                                "source_id": service.service_id,
                                "target_id": other_service.service_id,
                                "type": "DEPENDS_ON",
                                "properties": {"context": "same-environment"},
                            })

        deduped_nodes: list[dict[str, Any]] = []
        seen_nodes: set[tuple[str, str]] = set()
        for node in sorted(nodes, key=lambda item: (item["id"], tuple(item["labels"]))):
            key = (node["id"], tuple(node["labels"]))
            if key in seen_nodes:
                continue
            seen_nodes.add(key)
            deduped_nodes.append(node)

        deduped_relationships: list[dict[str, Any]] = []
        seen_relationships: set[tuple[str, str, str]] = set()
        for relationship in sorted(
            relationships,
            key=lambda item: (item["source_id"], item["type"], item["target_id"]),
        ):
            key = (relationship["source_id"], relationship["type"], relationship["target_id"])
            if key in seen_relationships:
                continue
            seen_relationships.add(key)
            deduped_relationships.append(relationship)

        for item in (*deduped_nodes, *deduped_relationships):
            item["tenant_id"] = self.tenant_id
        return {"nodes": deduped_nodes, "relationships": deduped_relationships}

    def get_incident_graph_context(self, incident_id: str) -> dict[str, Any]:
        projection = self.project_operational_graph()
        incident_relationships = [
            relationship for relationship in projection["relationships"]
            if relationship["source_id"] == incident_id or relationship["target_id"] == incident_id
        ]

        affected_service = next(
            (
                relationship["target_id"]
                for relationship in incident_relationships
                if relationship["type"] == "AFFECTS"
                and relationship["source_id"] == incident_id
            ),
            None,
        )
        related_services = sorted(
            {
                relationship["target_id"]
                for relationship in incident_relationships
                if relationship["source_id"] == incident_id and relationship["type"] == "AFFECTS"
            }
            | {
                relationship["source_id"]
                for relationship in incident_relationships
                if relationship["target_id"] == incident_id and relationship["type"] == "AFFECTS"
            }
        )

        repository_context = sorted(
            {
                relationship["target_id"]
                for relationship in projection["relationships"]
                if relationship["source_id"] == affected_service and relationship["type"] == "IMPLEMENTED_BY"
            }
        ) if affected_service else []

        deployments = sorted(
            {
                relationship["target_id"]
                for relationship in projection["relationships"]
                if relationship["source_id"] in repository_context and relationship["type"] == "HAS_DEPLOYMENT"
            }
        )

        return {
            "incident_id": incident_id,
            "affected_service": affected_service,
            "related_services": related_services,
            "repository_context": repository_context,
            "recent_deployments": deployments,
            "graph_relationships": [
                f"{relationship['source_id']}:{relationship['type']}:{relationship['target_id']}"
                for relationship in incident_relationships
            ],
        }

    def _list_logs(self, incident_id: str) -> list[Any]:
        from app.repositories.incident_repository import LogRepository

        return LogRepository(self.database_url, self.tenant_id).list_logs_for_incident(incident_id)

    def _list_metrics(self, incident_id: str) -> list[Any]:
        from app.repositories.incident_repository import MetricRepository

        return MetricRepository(self.database_url, self.tenant_id).list_metrics_for_incident(incident_id)
