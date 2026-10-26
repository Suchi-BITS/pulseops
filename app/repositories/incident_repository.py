from __future__ import annotations

import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.database import DatabaseManager
from app.models.domain import (
    AccessMode,
    ApprovalDecision,
    AuditEvent,
    Deployment,
    DeploymentStatus,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    IncidentWorkflow,
    InvestigationRecord,
    LogEntry,
    LogLevel,
    Metric,
    Repository,
    RepositoryMapping,
    RiskLevel,
    Service,
    WorkflowDecision,
    WorkflowStatus,
)


class TenantContextError(ValueError):
    """A repository was constructed without a usable tenant. There is no implicit or default tenant."""


class BaseRepository:
    """Every tenant-owned query is scoped by ``self.tenant_id``; a repository cannot exist without one."""

    def __init__(self, database_url: str, tenant_id: str) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise TenantContextError("tenant_id is required: repositories are always tenant-scoped")
        self.database_url = database_url
        self.tenant_id = tenant_id
        self.database_manager = DatabaseManager(database_url)

    def get_connection(self) -> sqlite3.Connection:
        return self.database_manager.get_connection()


class ServiceRepository(BaseRepository):
    def get_service(self, service_id: str) -> Service | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM services WHERE tenant_id = ? AND service_id = ?",
                (self.tenant_id, service_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_service(row)

    def list_services(self) -> list[Service]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM services WHERE tenant_id = ? ORDER BY service_name", (self.tenant_id,)
            ).fetchall()
            return [self._row_to_service(row) for row in rows]

    @staticmethod
    def _row_to_service(row: sqlite3.Row) -> Service:
        return Service(
            service_id=row["service_id"],
            service_name=row["service_name"],
            owner_team=row["owner_team"],
            environment=row["environment"],
            repository_id=row["repository_id"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


_INSERT_INCIDENT = """
    INSERT INTO incidents (
        tenant_id, incident_id, service_id, severity, status, title,
        description, environment, started_at, resolved_at,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_INSERT_OR_REPLACE_INCIDENT = """
    INSERT OR REPLACE INTO incidents (
        tenant_id, incident_id, service_id, severity, status, title,
        description, environment, started_at, resolved_at,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""



class IncidentRepository(BaseRepository):
    def create_incident(self, incident: Incident, *, replace: bool = True) -> Incident:
        """Store an incident. ``replace=False`` is a plain INSERT that raises ``sqlite3.IntegrityError`` on a duplicate id
        (P11: id allocation must never silently overwrite a concurrently created incident)."""
        statement = _INSERT_OR_REPLACE_INCIDENT if replace else _INSERT_INCIDENT
        with self.get_connection() as connection:
            connection.execute(
                statement,
                (
                    self.tenant_id,
                    incident.incident_id,
                    incident.service_id,
                    incident.severity.value,
                    incident.status.value,
                    incident.title,
                    incident.description,
                    incident.environment,
                    incident.started_at.isoformat(),
                    incident.resolved_at.isoformat() if incident.resolved_at else None,
                    incident.created_at.isoformat(),
                    incident.updated_at.isoformat(),
                ),
            )
        return incident

    def get_incident(self, incident_id: str) -> Incident | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE tenant_id = ? AND incident_id = ?",
                (self.tenant_id, incident_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_incident(row)

    def list_incidents(self) -> list[Incident]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM incidents WHERE tenant_id = ? ORDER BY started_at DESC", (self.tenant_id,)
            ).fetchall()
            return [self._row_to_incident(row) for row in rows]

    # Sort keys are a fixed whitelist mapped to SQL fragments: a caller-supplied value is never interpolated.
    _INCIDENT_SORT_SQL = {
        "started_at": "started_at",
        "created_at": "created_at",
        "incident_id": "incident_id",
        "status": "status",
        "severity": "CASE severity WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 WHEN 'critical' THEN 4 ELSE 0 END",
    }

    def list_incidents_page(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        service_id: str | None = None,
        sort: str = "started_at",
        descending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """One page of this tenant's incidents plus the total number matching the filters."""
        if sort not in self._INCIDENT_SORT_SQL:
            raise ValueError(f"unsupported sort key: {sort}")
        clauses, params = ["tenant_id = ?"], [self.tenant_id]
        for column, value in (("status", status), ("severity", severity), ("service_id", service_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = " AND ".join(clauses)
        direction = "DESC" if descending else "ASC"
        with self.get_connection() as connection:
            # nosec B608 - `where` is built only from fixed column names, the sort is a fixed whitelist and every value is bound
            total = connection.execute(f"SELECT COUNT(*) FROM incidents WHERE {where}", params).fetchone()[0]  # nosec B608
            rows = connection.execute(
                f"SELECT * FROM incidents WHERE {where} ORDER BY {self._INCIDENT_SORT_SQL[sort]} {direction}, incident_id ASC"  # nosec B608
                " LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [self._row_to_incident(row) for row in rows], total

    @staticmethod
    def _row_to_incident(row: sqlite3.Row) -> Incident:
        return Incident(
            incident_id=row["incident_id"],
            service_id=row["service_id"],
            severity=IncidentSeverity(row["severity"]),
            status=IncidentStatus(row["status"]),
            title=row["title"],
            description=row["description"],
            environment=row["environment"],
            started_at=datetime.fromisoformat(row["started_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class LogRepository(BaseRepository):
    def list_logs_for_incident(self, incident_id: str) -> list[LogEntry]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM logs WHERE tenant_id = ? AND incident_id = ? ORDER BY timestamp ASC",
                (self.tenant_id, incident_id),
            ).fetchall()
            return [self._row_to_log(row) for row in rows]

    @staticmethod
    def _row_to_log(row: sqlite3.Row) -> LogEntry:
        metadata = row["metadata"]
        if metadata is None:
            parsed_metadata = None
        else:
            try:
                parsed_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                parsed_metadata = ast.literal_eval(metadata)
        return LogEntry(
            log_id=row["log_id"],
            incident_id=row["incident_id"],
            service_id=row["service_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            level=LogLevel(row["level"]),
            message=row["message"],
            source=row["source"],
            metadata=parsed_metadata,
        )


class MetricRepository(BaseRepository):
    def list_metrics_for_incident(self, incident_id: str) -> list[Metric]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM metrics WHERE tenant_id = ? AND incident_id = ? ORDER BY timestamp ASC",
                (self.tenant_id, incident_id),
            ).fetchall()
            return [self._row_to_metric(row) for row in rows]

    @staticmethod
    def _row_to_metric(row: sqlite3.Row) -> Metric:
        return Metric(
            metric_id=row["metric_id"],
            incident_id=row["incident_id"],
            service_id=row["service_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            metric_name=row["metric_name"],
            value=float(row["value"]),
            unit=row["unit"],
            source=row["source"],
        )


class DeploymentRepository(BaseRepository):
    def list_deployments_for_service(self, service_id: str) -> list[Deployment]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM deployments WHERE tenant_id = ? AND service_id = ? ORDER BY deployed_at DESC",
                (self.tenant_id, service_id),
            ).fetchall()
            return [self._row_to_deployment(row) for row in rows]

    @staticmethod
    def _row_to_deployment(row: sqlite3.Row) -> Deployment:
        return Deployment(
            deployment_id=row["deployment_id"],
            service_id=row["service_id"],
            version=row["version"],
            commit_sha=row["commit_sha"],
            environment=row["environment"],
            deployed_at=datetime.fromisoformat(row["deployed_at"]),
            deployed_by=row["deployed_by"],
            status=DeploymentStatus(row["status"]),
        )


class RepositoryRepository(BaseRepository):
    def get_repository(self, repository_id: str) -> Repository | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE tenant_id = ? AND repository_id = ?",
                (self.tenant_id, repository_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_repository(row)

    @staticmethod
    def _row_to_repository(row: sqlite3.Row) -> Repository:
        return Repository(
            repository_id=row["repository_id"],
            provider=row["provider"],
            owner=row["owner"],
            name=row["name"],
            default_branch=row["default_branch"],
            access_mode=AccessMode(row["access_mode"]),
            active=bool(row["active"]),
        )


class RepositoryMappingRepository(BaseRepository):
    def get_for_service(self, service_id: str) -> RepositoryMapping | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM repository_mappings WHERE tenant_id = ? AND service_id = ? AND active = 1 LIMIT 1",
                (self.tenant_id, service_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_mapping(row)

    @staticmethod
    def _row_to_mapping(row: sqlite3.Row) -> RepositoryMapping:
        return RepositoryMapping(
            mapping_id=row["mapping_id"],
            service_id=row["service_id"],
            repository_id=row["repository_id"],
            branch=row["branch"],
            path_prefix=row["path_prefix"],
            active=bool(row["active"]),
        )


class WorkflowRepository(BaseRepository):
    def create_workflow(self, workflow: IncidentWorkflow) -> IncidentWorkflow:
        with self.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO workflow_instances (
                    tenant_id, workflow_id, incident_id, action, status, risk_level, policy_decision,
                    created_at, updated_at, requested_by, details, requires_approval
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.tenant_id,
                    workflow.workflow_id,
                    workflow.incident_id,
                    workflow.action,
                    workflow.status.value,
                    workflow.risk_level.value,
                    workflow.policy_decision or workflow.status.value,
                    workflow.created_at.isoformat(),
                    workflow.updated_at.isoformat(),
                    workflow.requested_by,
                    json.dumps(workflow.details),
                    int(workflow.requires_approval),
                ),
            )
        return workflow

    def get_workflow(self, workflow_id: str) -> IncidentWorkflow | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_instances WHERE tenant_id = ? AND workflow_id = ?",
                (self.tenant_id, workflow_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_workflow(row)

    def get_latest_for_incident(self, incident_id: str) -> IncidentWorkflow | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_instances WHERE tenant_id = ? AND incident_id = ?"
                " ORDER BY created_at DESC LIMIT 1",
                (self.tenant_id, incident_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_workflow(row)

    def update_workflow(self, workflow: IncidentWorkflow) -> IncidentWorkflow:
        with self.get_connection() as connection:
            connection.execute(
                """
                UPDATE workflow_instances
                SET incident_id = ?, action = ?, status = ?, risk_level = ?, policy_decision = ?,
                    updated_at = ?, requested_by = ?, details = ?, requires_approval = ?
                WHERE tenant_id = ? AND workflow_id = ?
                """,
                (
                    workflow.incident_id,
                    workflow.action,
                    workflow.status.value,
                    workflow.risk_level.value,
                    workflow.policy_decision or workflow.status.value,
                    workflow.updated_at.isoformat(),
                    workflow.requested_by,
                    json.dumps(workflow.details),
                    int(workflow.requires_approval),
                    self.tenant_id,
                    workflow.workflow_id,
                ),
            )
        return workflow

    def update_workflow_if_status(self, workflow: IncidentWorkflow, expected_status: str) -> bool:
        """Atomic compare-and-set (P11): apply the update only if the stored status is still ``expected_status``.

        Returns False when another request changed the workflow first (a lost race), so a single workflow can never
        record two different decisions."""
        with self.get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE workflow_instances
                SET incident_id = ?, action = ?, status = ?, risk_level = ?, policy_decision = ?,
                    updated_at = ?, requested_by = ?, details = ?, requires_approval = ?
                WHERE tenant_id = ? AND workflow_id = ? AND status = ?
                """,
                (
                    workflow.incident_id,
                    workflow.action,
                    workflow.status.value,
                    workflow.risk_level.value,
                    workflow.policy_decision or workflow.status.value,
                    workflow.updated_at.isoformat(),
                    workflow.requested_by,
                    json.dumps(workflow.details),
                    int(workflow.requires_approval),
                    self.tenant_id,
                    workflow.workflow_id,
                    expected_status,
                ),
            )
            return cursor.rowcount == 1

    def create_decision(self, decision: WorkflowDecision) -> WorkflowDecision:
        with self.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO workflow_decisions (
                    decision_id, tenant_id, workflow_id, decision, actor_id, actor_type, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    self.tenant_id,
                    decision.workflow_id,
                    decision.decision.value,
                    decision.actor_id,
                    decision.actor_type,
                    decision.reason,
                    decision.timestamp.isoformat(),
                ),
            )
        return decision

    def get_idempotency_entry(self, idempotency_key: str) -> dict[str, str] | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_idempotency_keys WHERE tenant_id = ? AND idempotency_key = ?",
                (self.tenant_id, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            return {
                "idempotency_key": row["idempotency_key"],
                "workflow_id": row["workflow_id"],
                "incident_id": row["incident_id"],
                "action": row["action"],
                "request_hash": row["request_hash"],
                "created_at": row["created_at"],
            }

    def create_idempotency_entry(
        self,
        *,
        idempotency_key: str,
        workflow_id: str,
        incident_id: str,
        action: str,
        request_hash: str,
    ) -> None:
        with self.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO workflow_idempotency_keys (
                    tenant_id, idempotency_key, workflow_id, incident_id, action, request_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.tenant_id,
                    idempotency_key,
                    workflow_id,
                    incident_id,
                    action,
                    request_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def create_audit_event(self, audit: AuditEvent, workflow_id: str, incident_id: str) -> AuditEvent:
        with self.get_connection() as connection:
            audit_id = audit.audit_id or audit.event_id or f"AUD-{uuid4().hex[:10].upper()}"
            connection.execute(
                """
                INSERT INTO workflow_audit_events (
                    audit_id, tenant_id, workflow_id, incident_id, event_id, event_type,
                    actor_type, actor_id, timestamp, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    self.tenant_id,
                    workflow_id,
                    incident_id,
                    audit.event_id or audit_id,
                    audit.event_type,
                    audit.actor_type or ("system" if audit.actor is None else "user"),
                    audit.actor,
                    audit.timestamp.isoformat(),
                    json.dumps(audit.metadata) if audit.metadata is not None else json.dumps({"description": audit.description}),
                ),
            )
            audit.audit_id = audit_id
            audit.event_id = audit.event_id or audit_id
        return audit

    def list_audit_events(self, workflow_id: str) -> list[AuditEvent]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_audit_events WHERE tenant_id = ? AND workflow_id = ? ORDER BY timestamp ASC",
                (self.tenant_id, workflow_id),
            ).fetchall()
            return [self._row_to_audit(row) for row in rows]

    def list_decisions_for_workflow(self, workflow_id: str) -> list[WorkflowDecision]:
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_decisions WHERE tenant_id = ? AND workflow_id = ? ORDER BY timestamp ASC",
                (self.tenant_id, workflow_id),
            ).fetchall()
            return [self._row_to_decision(row) for row in rows]

    _WORKFLOW_SORT_SQL = {"created_at": "w.created_at", "updated_at": "w.updated_at", "status": "w.status"}

    def list_workflows_page(
        self,
        *,
        status: str | None = None,
        incident_id: str | None = None,
        requires_approval: bool | None = None,
        sort: str = "created_at",
        descending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Read-only page of this tenant's workflows with their latest decision and stored-investigation summary."""
        if sort not in self._WORKFLOW_SORT_SQL:
            raise ValueError(f"unsupported sort key: {sort}")
        clauses, params = ["w.tenant_id = ?"], [self.tenant_id]
        if status is not None:
            clauses.append("w.status = ?")
            params.append(status)
        if incident_id is not None:
            clauses.append("w.incident_id = ?")
            params.append(incident_id)
        if requires_approval is not None:
            clauses.append("w.requires_approval = ?")
            params.append(int(requires_approval))
        where = " AND ".join(clauses)
        direction = "DESC" if descending else "ASC"
        latest = (
            "SELECT {col} FROM workflow_decisions d WHERE d.tenant_id = w.tenant_id AND d.workflow_id = w.workflow_id"
            " ORDER BY d.timestamp DESC, d.rowid DESC LIMIT 1"
        )
        with self.get_connection() as connection:
            # nosec B608 - same construction as above: fixed clauses, whitelisted sort, bound values
            total = connection.execute(f"SELECT COUNT(*) FROM workflow_instances w WHERE {where}", params).fetchone()[0]  # nosec B608
            rows = connection.execute(
                f"""
                SELECT w.*, i.investigation_id AS investigation_id, i.summary AS investigation_summary,
                       i.confidence AS investigation_confidence,
                       ({latest.format(col="d.decision")}) AS latest_decision,
                       ({latest.format(col="d.actor_id")}) AS latest_reviewer
                FROM workflow_instances w
                LEFT JOIN investigations i ON i.tenant_id = w.tenant_id AND i.workflow_id = w.workflow_id
                WHERE {where}
                ORDER BY {self._WORKFLOW_SORT_SQL[sort]} {direction}, w.workflow_id ASC
                LIMIT ? OFFSET ?
                """,  # nosec B608
                [*params, limit, offset],
            ).fetchall()
        return [dict(row) for row in rows], total

    @staticmethod
    def _row_to_workflow(row: sqlite3.Row) -> IncidentWorkflow:
        return IncidentWorkflow(
            workflow_id=row["workflow_id"],
            incident_id=row["incident_id"],
            action=row["action"],
            requested_by=row["requested_by"],
            details=json.loads(row["details"]) if row["details"] else {},
            risk_level=RiskLevel(row["risk_level"]),
            policy_decision=row["policy_decision"],
            requires_approval=bool(row["requires_approval"]),
            status=WorkflowStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> WorkflowDecision:
        return WorkflowDecision(
            decision_id=row["decision_id"],
            workflow_id=row["workflow_id"],
            decision=ApprovalDecision(row["decision"]),
            actor_id=row["actor_id"],
            actor_type=row["actor_type"],
            reason=row["reason"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> AuditEvent:
        details = row["details"]
        metadata = None if details is None else json.loads(details)
        return AuditEvent(
            audit_id=row["audit_id"],
            event_id=row["event_id"],
            tenant_id=row["tenant_id"],
            event_type=row["event_type"],
            description=(metadata or {}).get("description", ""),
            actor=row["actor_id"],
            actor_type=row["actor_type"],
            metadata=metadata,
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )


class OperationalEventRepository(BaseRepository):
    """Durable, tenant-scoped event-level idempotency for operational events (Phase 7 Gate 6, tenant-scoped in 9.1).

    UNIQUE (tenant_id, event_id) makes the first delivery win atomically, even under concurrent duplicate
    deliveries; the same event_id in a different tenant is an independent event.
    """

    def claim_event(self, event_id: str, request_hash: str) -> bool:
        try:
            with self.get_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO operational_events (tenant_id, event_id, request_hash, state, created_at)
                    VALUES (?, ?, ?, 'processing', ?)
                    """,
                    (self.tenant_id, event_id, request_hash, datetime.now(timezone.utc).isoformat()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_event(self, event_id: str) -> dict[str, str | None] | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM operational_events WHERE tenant_id = ? AND event_id = ?", (self.tenant_id, event_id)
            ).fetchone()
        return dict(row) if row is not None else None

    def set_incident(self, event_id: str, incident_id: str) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "UPDATE operational_events SET incident_id = ? WHERE tenant_id = ? AND event_id = ?",
                (incident_id, self.tenant_id, event_id),
            )

    def complete_event(self, event_id: str, workflow_id: str) -> None:
        with self.get_connection() as connection:
            connection.execute(
                "UPDATE operational_events SET state = 'completed', workflow_id = ? WHERE tenant_id = ? AND event_id = ?",
                (workflow_id, self.tenant_id, event_id),
            )

    def reclaim_stale(self, event_id: str, ttl_seconds: int) -> bool:
        """Atomically take over a claim that has been 'processing' with no workflow for longer than the TTL.

        One UPDATE with the staleness condition in its WHERE clause: of several concurrent reclaimers exactly one
        sees rowcount 1; a live (younger) claim is never touched. The claim timestamp is refreshed on success.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=ttl_seconds)).isoformat()
        with self.get_connection() as connection:
            cursor = connection.execute(
                "UPDATE operational_events SET created_at = ? WHERE tenant_id = ? AND event_id = ?"
                " AND state = 'processing' AND workflow_id IS NULL AND created_at < ?",
                (now.isoformat(), self.tenant_id, event_id, cutoff),
            )
            return cursor.rowcount == 1

    def release_unstarted_claim(self, event_id: str) -> None:
        """Drop a claim that never produced an incident (e.g. unknown service), so a corrected event can be retried."""
        with self.get_connection() as connection:
            connection.execute(
                "DELETE FROM operational_events WHERE tenant_id = ? AND event_id = ?"
                " AND incident_id IS NULL AND workflow_id IS NULL",
                (self.tenant_id, event_id),
            )



class InvestigationRepository(BaseRepository):
    """Tenant-scoped store of grounded investigation results (P9.1).

    Only the workflow service writes here, and only for a completed, grounded result. The composite foreign key to
    ``workflow_instances (tenant_id, workflow_id)`` makes a cross-tenant record impossible at the database level, and
    every read filters on the tenant of this repository.
    """

    _LISTS = ("evidence", "hypotheses", "missing_information", "recommendations", "tool_calls")

    @staticmethod
    def _strings(value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item if isinstance(item, str) else json.dumps(item, default=str) for item in value]

    def create(self, workflow_id: str, incident_id: str, result: dict, *, source: str = "workflow",
               created_at: datetime | None = None) -> InvestigationRecord:
        workflow = WorkflowRepository(self.database_url, self.tenant_id).get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Unknown workflow_id: {workflow_id}")
        if workflow.incident_id != incident_id or result.get("incident_id") != incident_id:
            raise ValueError("investigation does not belong to the workflow's incident")
        try:
            confidence = min(1.0, max(0.0, float(result.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        record = InvestigationRecord(
            investigation_id=f"INV-{uuid4().hex[:10].upper()}",
            tenant_id=self.tenant_id,
            incident_id=incident_id,
            workflow_id=workflow_id,
            service_id=str(result.get("service_id") or "unknown"),
            summary=str(result.get("summary") or ""),
            **{name: self._strings(result.get(name)) for name in self._LISTS},
            confidence=confidence,
            source=source,
            created_at=created_at or datetime.now(timezone.utc),
        )
        with self.get_connection() as connection:
            connection.execute(
                """
                INSERT INTO investigations (
                    tenant_id, investigation_id, incident_id, workflow_id, service_id, summary, evidence, hypotheses,
                    missing_information, recommendations, confidence, tool_calls, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.tenant_id, record.investigation_id, incident_id, workflow_id, record.service_id, record.summary,
                    json.dumps(record.evidence), json.dumps(record.hypotheses), json.dumps(record.missing_information),
                    json.dumps(record.recommendations), record.confidence, json.dumps(record.tool_calls), source,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def get(self, investigation_id: str) -> InvestigationRecord | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM investigations WHERE tenant_id = ? AND investigation_id = ?",
                (self.tenant_id, investigation_id),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_for_workflow(self, workflow_id: str) -> InvestigationRecord | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM investigations WHERE tenant_id = ? AND workflow_id = ?", (self.tenant_id, workflow_id)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_for_incident(self, incident_id: str) -> list[InvestigationRecord]:
        """Newest first."""
        with self.get_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM investigations WHERE tenant_id = ? AND incident_id = ? ORDER BY created_at DESC, row_id DESC",
                (self.tenant_id, incident_id),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def investigation_id_for_workflow(self, workflow_id: str) -> str | None:
        with self.get_connection() as connection:
            row = connection.execute(
                "SELECT investigation_id FROM investigations WHERE tenant_id = ? AND workflow_id = ?",
                (self.tenant_id, workflow_id),
            ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> InvestigationRecord:
        return InvestigationRecord(
            investigation_id=row["investigation_id"],
            tenant_id=row["tenant_id"],
            incident_id=row["incident_id"],
            workflow_id=row["workflow_id"],
            service_id=row["service_id"],
            summary=row["summary"],
            evidence=json.loads(row["evidence"]),
            hypotheses=json.loads(row["hypotheses"]),
            missing_information=json.loads(row["missing_information"]),
            recommendations=json.loads(row["recommendations"]),
            confidence=row["confidence"],
            tool_calls=json.loads(row["tool_calls"]),
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
