from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.request_context import bind, current_principal
from app.models.schemas import OperationalEvent
from app.repositories.incident_repository import OperationalEventRepository
from app.services.incident_service import IncidentService
from app.services.workflow_service import (
    FAILURE_INVESTIGATION_UNGROUNDED,
    INVESTIGATION_PENDING,
    WorkflowService,
)

if TYPE_CHECKING:
    from app.core.security import Principal

DEFAULT_REQUESTED_ACTION = "notify"
_REPLAY_WAIT_SECONDS = 120.0
_REPLAY_POLL_SECONDS = 0.2

logger = get_logger("pulseops.events")


@dataclass
class InvestigationOutcome:
    """An investigation result plus whether the agent actually grounded it in retrieved evidence."""

    result: Any
    grounded: bool
    ai_execution: dict[str, Any] | None = None  # duration / token usage / cost when the SDK exposes them


Investigator = Callable[[str, str | None], Awaitable[Any]]


def build_investigator(database_url: str) -> Investigator:
    """Adapter onto the existing Phase 6 Incident Agent (Claude Agent SDK + MCP). No second agent.

    Returns an ``InvestigationOutcome`` whose ``grounded`` flag is the agent's own audited telemetry
    (context actually retrieved from the MCP tools), not something the model claims. The agent's identity context is
    derived from the authenticated principal of the current request, never from request fields.
    """
    from app.agent.service import IncidentInvestigationAgent
    from app.core.security import identity_context_for

    agent = IncidentInvestigationAgent(database_url=database_url)

    async def _investigate(incident_id: str, objective: str | None) -> Any:
        principal = current_principal()
        # The agent runs inside the tenant of the authenticated principal (the event service already refuses a
        # principal from another tenant). Without a tenant context there is no investigation: fail closed.
        if principal is None:
            raise PermissionError("investigation requires an authenticated tenant context")
        identity = identity_context_for(principal)
        result = await agent.investigate(incident_id, objective, identity_context=identity)
        telemetry = agent.last_telemetry
        ai_execution = None
        if telemetry is not None:
            ai_execution = {
                "model": telemetry.model,
                "duration_ms": telemetry.duration_ms,
                "api_duration_ms": telemetry.api_duration_ms,
                "total_cost_usd": telemetry.total_cost_usd,
                "usage": telemetry.usage,
            }
        return InvestigationOutcome(result=result, grounded=bool(telemetry and telemetry.grounded), ai_execution=ai_execution)

    return _investigate


class OperationalEventService:
    """Operational-event ingestion boundary.

    event -> idempotency claim -> incident -> Phase 6 investigation -> deterministic policy -> workflow.
    """

    def __init__(
        self,
        *,
        incident_service: IncidentService,
        workflow_service: WorkflowService,
        database_url: str | None = None,
        tenant_id: str,
    ) -> None:
        if not (incident_service.tenant_id == workflow_service.tenant_id == tenant_id):
            raise ValueError("incident, workflow and event services must belong to the same tenant")
        self.database_url = database_url or get_settings().database_url
        self.tenant_id = tenant_id
        self.incident_service = incident_service
        self.workflow_service = workflow_service
        self.events = OperationalEventRepository(self.database_url, tenant_id)

    @staticmethod
    def requested_action(event: OperationalEvent) -> str:
        """Optional ``metadata.requested_action``; defaults to ``notify``. Untrusted: policy decides."""
        value = event.metadata.get("requested_action", DEFAULT_REQUESTED_ACTION)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("metadata.requested_action must be a non-empty string")
        return value.strip()

    @staticmethod
    def _request_hash(event: OperationalEvent, action: str) -> str:
        canonical = json.dumps(
            {"event": event.model_dump(mode="json", exclude={"tenant_id"}), "action": action}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _investigation_outcome(raw: Any, incident_id: str) -> dict[str, Any]:
        """Classify an investigation as completed / degraded; an invalid result raises (FAILED)."""
        grounded: bool | None = None
        ai_execution: dict[str, Any] | None = None
        result = raw
        if isinstance(raw, InvestigationOutcome):
            result, grounded, ai_execution = raw.result, raw.grounded, raw.ai_execution
        dumped = result.model_dump(mode="json") if hasattr(result, "model_dump") else None
        if not isinstance(dumped, dict) or dumped.get("incident_id") != incident_id:
            raise ValueError("invalid investigation result")
        if grounded is None:  # a bare result: the agent's invariant is that grounded results carry evidence
            grounded = bool(dumped.get("evidence"))
        if not grounded:
            return {"status": "degraded", "failure_reason": FAILURE_INVESTIGATION_UNGROUNDED, "result": dumped,
                    "ai_execution": ai_execution}
        return {"status": "completed", "failure_reason": None, "result": dumped, "ai_execution": ai_execution}

    async def ingest(self, event: OperationalEvent, principal: "Principal | None" = None) -> dict[str, Any]:
        if principal is not None and principal.tenant_id != self.tenant_id:
            raise PermissionError("principal is not authorized for this tenant")
        action = self.requested_action(event)
        request_hash = self._request_hash(event, action)
        requested_by = principal.principal_id if principal is not None else "system"
        actor_type = principal.principal_type.value if principal is not None else None
        bind(event_id=event.event_id)

        recovered: dict[str, Any] | None = None
        if not self.events.claim_event(event.event_id, request_hash):
            waited = await self._wait_for_or_reclaim(event.event_id, request_hash)
            if "workflow_id" in waited:  # the first delivery finished: this is a replay
                return waited
            recovered = waited  # a stale claim was reclaimed by this delivery
        return await self._process(event, action, requested_by, actor_type, recovered)

    async def _process(
        self, event: OperationalEvent, action: str, requested_by: str, actor_type: str | None,
        recovered: dict[str, Any] | None,
    ) -> dict[str, Any]:
        key = f"event:{event.event_id}"
        incident_id = recovered["incident_id"] if recovered else None
        if incident_id is None:
            try:
                incident = self.incident_service.create_incident(
                    service_id=event.service_id,
                    severity=event.severity,
                    title=f"{event.event_type} on {event.service_id}",
                    description=event.message,
                    environment=str(event.metadata.get("environment") or "unknown"),
                )
            except Exception:
                self.events.release_unstarted_claim(event.event_id)
                raise
            incident_id = incident.incident_id
        self.events.set_incident(event.event_id, incident_id)
        bind(incident_id=incident_id)

        existing = self.workflow_service.repository.get_idempotency_entry(key)
        if existing is not None:
            # A previous delivery created the workflow and then died. A still-held investigation is closed
            # (fail closed); otherwise the already-final workflow is simply returned.
            result = await asyncio.to_thread(self._settle_existing_workflow, existing["workflow_id"], requested_by, actor_type)
            result = self._finalize(result, event.event_id, replay=True)
            result["idempotent_replay"] = False
        else:
            investigator = build_investigator(self.database_url)
            objective = f"Investigate incident {incident_id}; report evidence, hypotheses and recommendations."

            def investigate() -> dict[str, Any]:
                raw = asyncio.run(investigator(incident_id, objective))
                return self._investigation_outcome(raw, incident_id)

            result = await asyncio.to_thread(
                self.workflow_service.evaluate_incident_action,
                incident_id,
                action,
                requested_by,
                details={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "event_timestamp": event.timestamp.isoformat(),
                    "service_id": event.service_id,
                    "source": event.source,
                    "event_severity": event.severity,
                    "message": event.message,
                    "metadata": event.metadata,
                },
                severity=event.severity,
                idempotency_key=key,
                investigate=investigate,
                actor_type=actor_type,
            )
            result = self._finalize(result, event.event_id, replay=False)
        workflow_id = result["workflow_id"]
        bind(workflow_id=workflow_id)
        if recovered is not None:
            self.workflow_service.record_audit_event(
                incident_id, workflow_id, "EVENT_CLAIM_RECOVERED",
                "A stale processing claim for this event was recovered and the event was processed again.",
                actor=requested_by, actor_type=actor_type,
                metadata={"result": "claim_recovered", "stale_claim_age_seconds": recovered["age_seconds"],
                          "claim_ttl_seconds": recovered["ttl_seconds"]},
            )
            refreshed = self.workflow_service.get_workflow(workflow_id)
            if refreshed is not None:
                result["audit_events"] = refreshed["audit_events"]
        self.events.complete_event(event.event_id, workflow_id)
        logger.info(
            "operational event processed",
            extra={"operation": "event_ingest", "outcome": result.get("investigation_status"),
                   "error_class": result.get("failure_reason")},
        )
        return result

    def _settle_existing_workflow(self, workflow_id: str, requested_by: str, actor_type: str | None) -> dict[str, Any]:
        workflow = self.workflow_service.get_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Unknown workflow_id: {workflow_id}")
        if workflow["policy_decision"] == INVESTIGATION_PENDING:
            return self.workflow_service.abandon_investigation(workflow_id, requested_by=requested_by, actor_type=actor_type)
        return workflow

    @staticmethod
    def _age_seconds(row: dict[str, Any]) -> float:
        created = datetime.fromisoformat(str(row["created_at"]))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds()

    async def _wait_for_or_reclaim(self, event_id: str, request_hash: str) -> dict[str, Any]:
        """Replay a finished event, wait for a live one, or reclaim a claim older than the TTL.

        Returns the replayed response (has ``workflow_id``) or ``{"incident_id", "age_seconds", "ttl_seconds"}`` when
        this delivery atomically reclaimed a stale claim. A claim younger than the TTL is never reclaimed.
        """
        ttl = get_settings().event_claim_ttl_seconds
        waited = 0.0
        while True:
            row = self.events.get_event(event_id)
            if row is None:  # the first delivery released its claim; nothing to replay
                raise ConflictError("event conflict: first delivery did not complete; resend the event")
            if row["request_hash"] != request_hash:
                raise ConflictError("conflicting event_id reuse with different event data")
            if row["state"] == "completed" and row["workflow_id"]:
                workflow = self.workflow_service.get_workflow(row["workflow_id"])
                if workflow is None:
                    raise NotFoundError(f"Unknown workflow_id: {row['workflow_id']}")
                return self._finalize(workflow, event_id, replay=True)
            age = self._age_seconds(row)
            if age > ttl and self.events.reclaim_stale(event_id, ttl):
                return {"incident_id": row["incident_id"], "age_seconds": round(age, 1), "ttl_seconds": ttl}
            if waited >= _REPLAY_WAIT_SECONDS:
                raise ConflictError("event conflict: event is still being processed")
            await asyncio.sleep(_REPLAY_POLL_SECONDS)
            waited += _REPLAY_POLL_SECONDS

    @staticmethod
    def _finalize(result: dict[str, Any], event_id: str, *, replay: bool) -> dict[str, Any]:
        result = dict(result)
        audit = result.get("audit_events") or []
        if replay:
            # A replay is rebuilt from persisted state; recover investigation/policy facts from the audit trail.
            by_type = {e["event_type"]: e for e in audit}
            result["failure_reason"] = None
            if "INVESTIGATION_COMPLETED" in by_type:
                meta = by_type["INVESTIGATION_COMPLETED"].get("metadata") or {}
                result["investigation_status"] = "completed"
                result["investigation"] = meta.get("investigation")
            elif "INVESTIGATION_DEGRADED" in by_type:
                meta = by_type["INVESTIGATION_DEGRADED"].get("metadata") or {}
                result["investigation_status"] = "degraded"
                result["investigation"] = meta.get("investigation")
                result["failure_reason"] = meta.get("failure_reason")
            else:
                meta = (by_type.get("INVESTIGATION_FAILED") or {}).get("metadata") or {}
                result["investigation_status"] = "failed"
                result["investigation"] = None
                result["failure_reason"] = meta.get("failure_reason")
            policy = by_type.get("POLICY_EVALUATED")
            result["policy_reason"] = (policy.get("metadata") or {}).get("reason") if policy else None
        result["event_id"] = event_id
        result["idempotency_key"] = f"event:{event_id}"
        result["correlation_id"] = event_id
        result["idempotent_replay"] = replay
        return result
