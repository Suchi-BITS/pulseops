from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.models.domain import Incident, IncidentSeverity, IncidentStatus
from app.repositories.incident_repository import IncidentRepository, ServiceRepository


class IncidentService:
    def __init__(self, database_url: str, tenant_id: str) -> None:
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.service_repository = ServiceRepository(database_url, tenant_id)
        self.incident_repository = IncidentRepository(database_url, tenant_id)

    def create_incident(
        self,
        service_id: str,
        severity: str,
        title: str,
        description: str,
        environment: str,
    ) -> Incident:
        service = self.service_repository.get_service(service_id)
        if service is None:
            raise ValueError(f"Unknown service_id: {service_id}")

        now = datetime.now(timezone.utc)
        # P11: ids are allocated as "highest + 1", which two concurrent requests can both compute. The insert must never
        # replace another incident, so a collision (IntegrityError on the per-tenant unique id) re-allocates and retries.
        for _attempt in range(25):
            incident_id = self._next_incident_id()
            incident = Incident(
                incident_id=incident_id,
                service_id=service_id,
                severity=IncidentSeverity(severity.lower()),
                status=IncidentStatus.OPEN,
                title=title,
                description=description,
                environment=environment,
                started_at=now,
                created_at=now,
                updated_at=now,
            )
            try:
                return self.incident_repository.create_incident(incident, replace=False)
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("could not allocate a unique incident id")

    def list_incidents(self) -> list[Incident]:
        return self.incident_repository.list_incidents()

    def list_incidents_page(self, **filters) -> tuple[list[Incident], int]:
        return self.incident_repository.list_incidents_page(**filters)

    def get_incident(self, incident_id: str) -> Incident | None:
        return self.incident_repository.get_incident(incident_id)

    def _next_incident_id(self) -> str:
        incidents = self.incident_repository.list_incidents()
        if not incidents:
            return "INC-1001"
        current_numbers = []
        for incident in incidents:
            suffix = incident.incident_id.replace("INC-", "")
            try:
                current_numbers.append(int(suffix))
            except ValueError:
                continue
        next_number = max(current_numbers, default=1000) + 1
        return f"INC-{next_number}"
