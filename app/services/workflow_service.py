from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.request_context import get_request_id
from app.models.domain import (
    ApprovalDecision,
    AuditEvent,
    IncidentWorkflow,
    RiskLevel,
    WorkflowDecision,
    WorkflowStatus,
)
from app.repositories.incident_repository import InvestigationRepository, WorkflowRepository
from app.services.policy_service import PolicyDecision, PolicyEngine


# Workflow `policy_decision` values that are NOT policy decisions: the investigation gate, not the policy engine,
# held or closed the workflow. DENY is reserved for genuine deterministic policy denials.
INVESTIGATION_PENDING = "investigation_pending"
INVESTIGATION_DEGRADED = "investigation_degraded"
INVESTIGATION_FAILED = "investigation_failed"
FAILURE_INVESTIGATION_FAILED = "investigation_failed"
FAILURE_INVESTIGATION_UNGROUNDED = "investigation_ungrounded"
FAILURE_INVESTIGATION_ABANDONED = "investigation_abandoned"  # the process died while the investigation was held


class WorkflowService:
    """Tenant-scoped workflow service: every read and write goes through a repository bound to ``tenant_id``."""

    def __init__(self, database_url: str | None = None, *, tenant_id: str) -> None:
        self.database_url = database_url or get_settings().database_url
        self.tenant_id = tenant_id
        self.policy_engine = PolicyEngine()
        self.repository = WorkflowRepository(self.database_url, tenant_id)
        self.investigations = InvestigationRepository(self.database_url, tenant_id)

    @staticmethod
    def _normalise_action(action: str) -> str:
        return PolicyEngine.normalize_action(action)

    @staticmethod
    def _classify_risk(action: str, severity: str | None = None) -> RiskLevel:
        del severity
        policy = PolicyEngine().evaluate(action, actor="system")
        return RiskLevel(policy["risk_level"])

    @staticmethod
    def _is_ai_actor(actor: str | None) -> bool:
        if actor is None:
            return False
        normalized = actor.strip().lower()
        if not normalized:
            return False
        ai_markers = {"ai", "assistant", "claude", "llm", "agent", "bot", "model"}
        return normalized in ai_markers or any(marker in normalized for marker in ("ai", "claude", "llm", "agent", "assistant", "bot", "model"))

    @staticmethod
    def _coerce_timestamp(value: str | datetime | None) -> datetime:
        if value is None:
            raise ValueError("timestamp is required for approval decisions")
        if isinstance(value, datetime):
            parsed = value
        else:
            normalized = str(value).strip()
            if not normalized:
                raise ValueError("timestamp is required for approval decisions")
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:  # pragma: no cover - defensive branch
                raise ValueError("approval timestamp must be a valid ISO 8601 datetime") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _request_hash(
        *,
        incident_id: str,
        action: str,
        requested_by: str,
        details: dict[str, Any] | None,
        severity: str | None,
    ) -> str:
        payload = {
            "incident_id": incident_id,
            "action": action,
            "requested_by": requested_by,
            "details": details or {},
            "severity": severity,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _record_audit(
        self,
        incident_id: str,
        workflow_id: str,
        event_type: str,
        description: str,
        *,
        actor: str | None = None,
        actor_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        request_id = get_request_id()
        # Every audit row names its tenant; the request id correlates it with the HTTP request that caused it.
        metadata = {**(metadata if metadata is not None else {"description": description}), "tenant_id": self.tenant_id}
        if request_id:
            metadata["request_id"] = request_id
        event = AuditEvent(
            audit_id=f"AUD-{uuid4().hex[:10].upper()}",
            event_id=f"EVT-{uuid4().hex[:10].upper()}",
            tenant_id=self.tenant_id,
            event_type=event_type,
            description=description,
            actor=actor,
            actor_type=actor_type,
            metadata=metadata,
            timestamp=datetime.now(timezone.utc),
        )
        self.repository.create_audit_event(event, workflow_id, incident_id)
        return event

    def _serialize_workflow(self, raw: IncidentWorkflow) -> dict[str, Any]:
        payload = raw.model_dump(mode="json")
        payload["investigation_id"] = self.investigations.investigation_id_for_workflow(raw.workflow_id)
        payload["audit_events"] = [
            {
                "audit_id": event.audit_id,
                "event_id": event.event_id,
                "tenant_id": event.tenant_id,
                "event_type": event.event_type,
                "description": event.description,
                "actor": event.actor,
                "actor_type": event.actor_type,
                "metadata": event.metadata,
                "timestamp": event.timestamp.isoformat(),
            }
            for event in raw.audit_events
        ]
        return payload

    def _close_unsuccessful_investigation(
        self,
        persisted: IncidentWorkflow,
        *,
        status: str,
        failure_reason: str,
        action: str,
        requested_by: str,
        actor_type: str | None = None,
        audit_type: str,
        audit_description: str,
        audit_metadata: dict[str, Any],
        investigation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """DEGRADED / FAILED: terminal, rejected (cannot be approved), never a policy decision."""
        persisted.policy_decision = INVESTIGATION_DEGRADED if status == "degraded" else INVESTIGATION_FAILED
        persisted.status = WorkflowStatus.REJECTED
        persisted.requires_approval = False
        persisted.details = {
            **(persisted.details or {}),
            "investigation": {"status": status, "failure_reason": failure_reason},
        }
        persisted.updated_at = datetime.now(timezone.utc)
        self.repository.update_workflow(persisted)
        self._record_audit(
            persisted.incident_id,
            persisted.workflow_id,
            audit_type,
            audit_description,
            actor="incident_agent",
            metadata={**audit_metadata, "failure_reason": failure_reason},
        )
        self._record_audit(
            persisted.incident_id,
            persisted.workflow_id,
            "WORKFLOW_FAILED",
            f"Workflow failed closed for action '{action}': investigation {status}.",
            actor=requested_by,
            actor_type=actor_type,
            metadata={"action": action, "result": f"investigation_{status}", "failure_reason": failure_reason},
        )
        persisted.audit_events = self.repository.list_audit_events(persisted.workflow_id)
        payload = self._serialize_workflow(persisted)
        payload["policy_reason"] = None  # the policy engine never evaluated this workflow
        payload["allowed_action_class"] = "informational"
        payload["investigation_status"] = status
        payload["failure_reason"] = failure_reason
        payload["investigation"] = investigation
        return payload

    def evaluate_incident_action(
        self,
        incident_id: str,
        action: str,
        requested_by: str = "system",
        *,
        details: dict[str, Any] | None = None,
        severity: str | None = None,
        idempotency_key: str | None = None,
        investigate: Callable[[], dict[str, Any]] | None = None,
        actor_type: str | None = None,
    ) -> dict[str, Any]:
        """Create (or replay) a workflow for an incident action.

        ``investigate`` is optional (Gate 6 event ingestion). When supplied it runs after the workflow
        exists and *before* the policy outcome is applied. The workflow is held in a fail-closed
        rejected state (``investigation_pending``, not a policy decision) until the investigation completes. ``investigate`` returns ``{"status": "completed"|"degraded", "result": {...}, "failure_reason": ...}``;
        raising (or any other shape) is FAILED. DEGRADED and FAILED are terminal ``rejected`` workflows whose
        ``policy_decision`` is a non-policy value (never DENY). The investigation never influences the policy decision.
        """
        if not incident_id:
            raise ValueError("incident_id is required")
        if not action or not action.strip():
            raise ValueError("action is required")

        normalized_key = str(idempotency_key).strip() if idempotency_key is not None else None
        if normalized_key is not None and not normalized_key:
            raise ValueError("idempotency_key must not be empty")
        request_hash = self._request_hash(
            incident_id=incident_id,
            action=action,
            requested_by=requested_by,
            details=details,
            severity=severity,
        )

        if normalized_key is not None:
            existing = self.repository.get_idempotency_entry(normalized_key)
            if existing is not None:
                if existing["incident_id"] != incident_id or existing["action"] != action or existing["request_hash"] != request_hash:
                    raise ConflictError("conflicting idempotency key reuse with different workflow data")
                workflow = self.repository.get_workflow(existing["workflow_id"])
                if workflow is None:
                    raise NotFoundError(f"Unknown workflow_id: {existing['workflow_id']}")
                workflow.audit_events = self.repository.list_audit_events(workflow.workflow_id)
                return self._serialize_workflow(workflow)

        policy = self.policy_engine.evaluate(action, actor=requested_by, role=requested_by, llm_risk_level=severity)
        risk_level = RiskLevel(policy["risk_level"])
        requires_approval = bool(policy["requires_approval"])
        status = WorkflowStatus.PENDING
        if policy["decision"] == PolicyDecision.DENY:
            status = WorkflowStatus.REJECTED

        now = datetime.now(timezone.utc)
        workflow = IncidentWorkflow(
            workflow_id=f"WF-{uuid4().hex[:8].upper()}",
            incident_id=incident_id,
            action=action,
            requested_by=requested_by,
            details=details or {},
            risk_level=risk_level,
            policy_decision=policy["decision"].value,
            requires_approval=requires_approval,
            status=status,
            created_at=now,
            updated_at=now,
        )
        if investigate is not None:
            # Fail closed until the investigation completes and policy is applied. The hold is NOT a policy
            # decision, so it must not be represented as DENY.
            workflow.status = WorkflowStatus.REJECTED
            workflow.policy_decision = INVESTIGATION_PENDING
            workflow.requires_approval = False
        persisted = self.repository.create_workflow(workflow)
        if normalized_key is not None:
            self.repository.create_idempotency_entry(
                idempotency_key=normalized_key,
                workflow_id=persisted.workflow_id,
                incident_id=incident_id,
                action=action,
                request_hash=request_hash,
            )

        self._record_audit(
            incident_id,
            persisted.workflow_id,
            "INCIDENT_RECEIVED",
            "Incident action request received for evaluation.",
            actor=requested_by,
            actor_type=actor_type,
            metadata={"action": action, "incident_id": incident_id, "result": "received"},
        )
        self._record_audit(
            incident_id,
            persisted.workflow_id,
            "WORKFLOW_CREATED",
            f"Workflow for action '{action}' was created.",
            actor=requested_by,
            actor_type=actor_type,
            metadata={"action": action, "result": "workflow_created"},
        )
        investigation: dict[str, Any] | None = None
        if investigate is not None:
            self._record_audit(
                incident_id,
                persisted.workflow_id,
                "INVESTIGATION_STARTED",
                "Incident investigation started before policy evaluation.",
                actor="incident_agent",
                metadata={"result": "investigation_started"},
            )
            try:
                outcome = investigate()
                outcome_status = outcome.get("status") if isinstance(outcome, dict) else None
                if outcome_status not in {"completed", "degraded"}:
                    raise ValueError("invalid investigation outcome")
            except Exception as exc:  # fail closed; only the exception type is recorded (no secrets/internals)
                return self._close_unsuccessful_investigation(
                    persisted,
                    status="failed",
                    failure_reason=FAILURE_INVESTIGATION_FAILED,
                    action=action,
                    requested_by=requested_by,
                    actor_type=actor_type,
                    audit_type="INVESTIGATION_FAILED",
                    audit_description="Incident investigation did not produce a valid result.",
                    audit_metadata={"result": "investigation_failed", "error_type": type(exc).__name__},
                    investigation=None,
                )
            if outcome_status == "degraded":
                return self._close_unsuccessful_investigation(
                    persisted,
                    status="degraded",
                    failure_reason=outcome.get("failure_reason") or FAILURE_INVESTIGATION_UNGROUNDED,
                    action=action,
                    requested_by=requested_by,
                    actor_type=actor_type,
                    audit_type="INVESTIGATION_DEGRADED",
                    audit_description="Incident investigation could not establish grounded context; failing closed.",
                    audit_metadata={"result": "investigation_degraded", "investigation": outcome.get("result"),
                                    "ai_execution": outcome.get("ai_execution")},
                    investigation=outcome.get("result"),
                )
            investigation = outcome.get("result")
            # P9.1: only a completed, grounded result reaches this point (degraded/failed outcomes were closed above
            # and are never stored as investigation records).
            stored = self.investigations.create(persisted.workflow_id, incident_id, investigation)
            self._record_audit(
                incident_id,
                persisted.workflow_id,
                "INVESTIGATION_COMPLETED",
                "Incident investigation completed; result is evidence/analysis only.",
                actor="incident_agent",
                metadata={"result": "investigation_completed", "investigation": investigation,
                          "investigation_id": stored.investigation_id, "ai_execution": outcome.get("ai_execution")},
            )
            # Policy outcome is deterministic and independent of the investigation.
            persisted.status = WorkflowStatus.REJECTED if policy["decision"] == PolicyDecision.DENY else WorkflowStatus.PENDING
            persisted.policy_decision = policy["decision"].value
            persisted.requires_approval = requires_approval
            persisted.updated_at = datetime.now(timezone.utc)
            self.repository.update_workflow(persisted)

        self._record_audit(
            incident_id,
            persisted.workflow_id,
            "POLICY_EVALUATED",
            f"Policy evaluation for action '{action}' returned {policy['decision']} with risk {policy['risk_level']}.",
            actor=requested_by,
            actor_type=actor_type,
            metadata={
                "action": action,
                "risk_level": policy["risk_level"],
                "decision": policy["decision"].value,
                "requires_approval": requires_approval,
                "reason": policy["reason"],
                "result": "policy_evaluated",
            },
        )

        if requires_approval:
            self._record_audit(
                incident_id,
                persisted.workflow_id,
                "HITL_REQUESTED",
                f"Human approval is required for action '{action}'.",
                actor=requested_by,
                actor_type=actor_type,
                metadata={"action": action, "result": "hitl_requested"},
            )
        if investigate is not None and policy["decision"] in {PolicyDecision.ALLOW, PolicyDecision.NOTIFY}:
            self._record_audit(
                incident_id,
                persisted.workflow_id,
                "NOTIFICATION_REQUESTED",
                f"Notification path selected by policy for action '{action}'.",
                actor=requested_by,
                actor_type=actor_type,
                metadata={"action": action, "decision": policy["decision"].value, "result": "notification_requested"},
            )
        if policy["decision"] == PolicyDecision.DENY:
            self._record_audit(
                incident_id,
                persisted.workflow_id,
                "WORKFLOW_FAILED",
                f"Workflow denied by policy for action '{action}'.",
                actor=requested_by,
                actor_type=actor_type,
                metadata={"action": action, "result": "denied"},
            )

        persisted.audit_events = self.repository.list_audit_events(persisted.workflow_id)
        payload = self._serialize_workflow(persisted)
        payload["policy_decision"] = policy["decision"].value
        payload["policy_reason"] = policy["reason"]
        payload["allowed_action_class"] = policy["allowed_action_class"]
        if investigate is not None:
            payload["investigation_status"] = "completed"
            payload["failure_reason"] = None
            payload["investigation"] = investigation
        return payload

    def record_audit_event(
        self,
        incident_id: str,
        workflow_id: str,
        event_type: str,
        description: str,
        *,
        actor: str | None = None,
        actor_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Public audit hook for application services (the request id is attached automatically)."""
        return self._record_audit(
            incident_id, workflow_id, event_type, description, actor=actor, actor_type=actor_type, metadata=metadata
        )

    def abandon_investigation(self, workflow_id: str, *, requested_by: str, actor_type: str | None = None) -> dict[str, Any]:
        """Close a workflow whose investigation hold was orphaned by a process crash (fail closed, auditable)."""
        workflow = self.repository.get_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Unknown workflow_id: {workflow_id}")
        if workflow.policy_decision != INVESTIGATION_PENDING:
            raise ValueError("only an orphaned investigation hold can be abandoned")
        return self._close_unsuccessful_investigation(
            workflow,
            status="failed",
            failure_reason=FAILURE_INVESTIGATION_ABANDONED,
            action=workflow.action,
            requested_by=requested_by,
            actor_type=actor_type,
            audit_type="INVESTIGATION_FAILED",
            audit_description="Investigation was abandoned: the process stopped while it was running; failing closed.",
            audit_metadata={"result": "investigation_abandoned"},
            investigation=None,
        )

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        workflow = self.repository.get_workflow(workflow_id)
        if workflow is None:
            return None
        workflow.audit_events = self.repository.list_audit_events(workflow_id)
        return self._serialize_workflow(workflow)

    def list_workflows(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        """Read-only page of workflows (tenant-scoped by the repository)."""
        return self.repository.list_workflows_page(**filters)

    def get_latest_workflow_for_incident(self, incident_id: str) -> dict[str, Any] | None:
        workflow = self.repository.get_latest_for_incident(incident_id)
        if workflow is None:
            return None
        workflow.audit_events = self.repository.list_audit_events(workflow.workflow_id)
        return self._serialize_workflow(workflow)

    def record_decision(
        self,
        workflow_id: str,
        *,
        decision: str,
        reviewer: str,
        rationale: str | None = None,
        incident_id: str | None = None,
        action: str | None = None,
        timestamp: str | datetime | None = None,
        idempotency_key: str | None = None,
        actor_type: str | None = None,
        actor_roles: list[str] | None = None,
        _after_lost_race: bool = False,
    ) -> dict[str, Any]:
        """Record an approve/reject decision.

        Gate 9: API callers pass the authenticated principal's id as ``reviewer`` with ``actor_type`` (and roles). A
        non-human ``actor_type`` can never approve. Legacy direct callers that pass no ``actor_type`` keep the older
        name-based AI-reviewer guard.
        """
        workflow = self.repository.get_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Unknown workflow_id: {workflow_id}")

        if reviewer is None or not str(reviewer).strip():
            raise ValueError("reviewer is required for approval decisions")
        if actor_type is not None:
            if actor_type != "human":
                raise ConflictError("human reviewer is required; AI-generated approval does not satisfy HITL")
        elif self._is_ai_actor(str(reviewer)):
            raise ConflictError("human reviewer is required; AI-generated approval does not satisfy HITL")

        if workflow.policy_decision and workflow.policy_decision.lower() == "deny":
            raise ConflictError("DENY policy cannot be overridden by an approval decision")
        if workflow.status in {WorkflowStatus.APPROVED, WorkflowStatus.REJECTED}:
            prior_decisions = self.repository.list_decisions_for_workflow(workflow_id)
            if prior_decisions:
                current = prior_decisions[-1]
                if current.decision.value == str(decision).strip().lower() and current.actor_id == str(reviewer).strip():
                    workflow.decision = current.decision
                    workflow.reviewer = current.actor_id
                    workflow.rationale = current.reason
                    workflow.status = WorkflowStatus.APPROVED if current.decision is ApprovalDecision.APPROVE else WorkflowStatus.REJECTED
                    workflow.requires_approval = False
                    workflow.updated_at = datetime.now(timezone.utc)
                    workflow.audit_events = self.repository.list_audit_events(workflow_id)
                    return self._serialize_workflow(workflow)
            raise ConflictError(f"Workflow {workflow_id} is already in a final state: {workflow.status.value}")
        if workflow.requires_approval and workflow.status != WorkflowStatus.PENDING:
            raise ValueError("workflow must remain in approval-pending state until a decision is recorded")

        normalized_decision = str(decision).strip().lower()
        if normalized_decision not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")

        parsed_decision = ApprovalDecision(normalized_decision)

        if timestamp is None:
            if workflow.requires_approval or (workflow.policy_decision and workflow.policy_decision.lower() in {"hitl_required", "deny"}):
                raise ValueError("timestamp is required for approval decisions on consequential workflows")
            parsed_timestamp = datetime.now(timezone.utc)
        else:
            parsed_timestamp = self._coerce_timestamp(timestamp)

        if incident_id is not None and str(incident_id).strip() and str(incident_id) != workflow.incident_id:
            raise ValueError("incident_id does not match the workflow being approved")
        if action is not None and str(action).strip() and self._normalise_action(str(action)) != self._normalise_action(workflow.action):
            raise ValueError("action does not match the workflow being approved")
        if workflow.action and (not action or not action.strip()) and workflow.requires_approval:
            raise ValueError("approval requires the correct workflow action to be supplied")

        existing_decisions = self.repository.list_decisions_for_workflow(workflow_id)
        for existing in existing_decisions:
            if existing.actor_id == str(reviewer).strip() and existing.decision.value == normalized_decision:
                workflow.decision = existing.decision
                workflow.reviewer = existing.actor_id
                workflow.status = WorkflowStatus.APPROVED if existing.decision is ApprovalDecision.APPROVE else WorkflowStatus.REJECTED
                workflow.requires_approval = False
                workflow.updated_at = datetime.now(timezone.utc)
                self.repository.update_workflow(workflow)
                workflow.audit_events = self.repository.list_audit_events(workflow_id)
                return self._serialize_workflow(workflow)
            if existing.decision.value != normalized_decision:
                raise ConflictError("decision conflicts with the existing workflow decision history")

        observed_status = workflow.status.value
        workflow.decision = parsed_decision
        workflow.reviewer = reviewer
        workflow.rationale = rationale
        workflow.status = WorkflowStatus.APPROVED if parsed_decision is ApprovalDecision.APPROVE else WorkflowStatus.REJECTED
        workflow.requires_approval = False
        workflow.updated_at = datetime.now(timezone.utc)
        # P11: the read-check-write above is not atomic, so two reviewers could both pass the checks and both record a
        # decision. The status change is an atomic compare-and-set; the request that loses the race is re-evaluated
        # against the now-final state (idempotent repeat, or a 409 conflict) and records nothing.
        if not self.repository.update_workflow_if_status(workflow, observed_status):
            if _after_lost_race:
                raise ConflictError(f"Workflow {workflow_id} was changed by a concurrent request; reload and retry")
            return self.record_decision(
                workflow_id, decision=decision, reviewer=reviewer, rationale=rationale, incident_id=incident_id,
                action=action, timestamp=timestamp, idempotency_key=idempotency_key, actor_type=actor_type,
                actor_roles=actor_roles, _after_lost_race=True,
            )

        decision_record = WorkflowDecision(
            decision_id=f"DEC-{uuid4().hex[:10].upper()}",
            workflow_id=workflow.workflow_id,
            decision=parsed_decision,
            actor_id=reviewer,
            actor_type=actor_type or "reviewer",
            reason=rationale,
            timestamp=parsed_timestamp,
        )
        self.repository.create_decision(decision_record)

        event_type = "HITL_APPROVED" if parsed_decision is ApprovalDecision.APPROVE else "HITL_REJECTED"
        self._record_audit(
            workflow.incident_id,
            workflow.workflow_id,
            event_type,
            f"Workflow {workflow.workflow_id} was {parsed_decision.value}d by {reviewer}.",
            actor=reviewer,
            actor_type=actor_type,
            metadata={
                "action": workflow.action,
                "decision": parsed_decision.value,
                "rationale": rationale,
                "timestamp": parsed_timestamp.isoformat(),
                "result": parsed_decision.value,
                "principal_type": actor_type,
                "principal_roles": actor_roles,
            },
        )

        final_event_type = "WORKFLOW_COMPLETED" if parsed_decision is ApprovalDecision.APPROVE else "WORKFLOW_FAILED"
        self._record_audit(
            workflow.incident_id,
            workflow.workflow_id,
            final_event_type,
            f"Workflow completed with {parsed_decision.value} decision.",
            actor=reviewer,
            actor_type=actor_type,
            metadata={
                "action": workflow.action,
                "decision": parsed_decision.value,
                "result": parsed_decision.value,
                "workflow_status": workflow.status.value,
            },
        )
        self._record_audit(
            workflow.incident_id,
            workflow.workflow_id,
            "approval",
            f"Workflow {workflow.workflow_id} was {parsed_decision.value}d by {reviewer}.",
            actor=reviewer,
            actor_type=actor_type,
            metadata={"decision": parsed_decision.value, "rationale": rationale, "timestamp": parsed_timestamp.isoformat()},
        )

        workflow.audit_events = self.repository.list_audit_events(workflow_id)
        return self._serialize_workflow(workflow)

