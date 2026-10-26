from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceCreateRequest(BaseModel):
    service_id: str
    service_name: str
    owner_team: str
    environment: str
    repository_id: str | None = None
    description: str | None = None


class IncidentCreateRequest(BaseModel):
    service_id: str
    severity: str
    title: str
    description: str
    environment: str


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: str
    service_id: str
    severity: str
    status: str
    title: str
    description: str
    environment: str
    started_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IncidentListItem(BaseModel):
    incident_id: str
    service_id: str
    severity: str
    status: str
    title: str
    environment: str
    started_at: datetime


class WorkflowEvaluationRequest(BaseModel):
    incident_id: str | None = None
    action: str
    requested_by: str = "system"
    details: dict[str, Any] = Field(default_factory=dict)
    severity: str | None = None
    idempotency_key: str | None = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        return normalized

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty")
        return normalized


class WorkflowDecisionRequest(BaseModel):
    workflow_id: str | None = None
    incident_id: str | None = None
    action: str | None = None
    decision: str
    reviewer: str | None = None  # never authoritative: if present it must equal the authenticated principal
    rationale: str | None = None
    timestamp: datetime | str | None = None
    idempotency_key: str | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime | str | None) -> datetime | str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("timestamp must not be empty")
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError("timestamp must be a valid ISO 8601 datetime") from exc
        return value

    @field_validator("idempotency_key")
    @classmethod
    def validate_decision_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty")
        return normalized


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    incident_id: str
    action: str
    requested_by: str
    details: dict[str, Any] = Field(default_factory=dict)
    risk_level: str
    requires_approval: bool = False
    status: str
    decision: str | None = None
    reviewer: str | None = None
    rationale: str | None = None
    created_at: datetime
    updated_at: datetime
    audit_events: list[dict[str, Any]] = Field(default_factory=list)
    policy_decision: str | None = None
    policy_reason: str | None = None
    allowed_action_class: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    investigation_id: str | None = None  # P9.1: reference to the stored, grounded investigation record (if any)


class OperationalEvent(BaseModel):
    """Operational event contract accepted from the n8n orchestration layer.

    All fields are untrusted data. ``message`` and ``metadata`` are stored as
    evidence only and are never interpreted as instructions.
    """

    event_id: str
    event_type: str
    timestamp: datetime
    service_id: str
    severity: str
    source: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Optional and never authoritative: the tenant is the authenticated principal's. A value that differs from it is
    # refused (403); it can neither select nor widen the tenant.
    tenant_id: str | None = None

    @field_validator("event_id", "event_type", "service_id", "source", "message")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("severity")
    @classmethod
    def validate_event_severity(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        return normalized


class WorkflowEventResponse(WorkflowResponse):
    event_id: str
    idempotent_replay: bool = False
    investigation_status: str = "failed"  # completed | degraded | failed
    failure_reason: str | None = None  # set for degraded/failed; distinct from any policy decision
    investigation: dict[str, Any] | None = None



# --- P9: application-facing contracts -------------------------------------------------------------------------------

from app.core.errors import ErrorResponse  # noqa: E402,F401  (re-exported so schemas are the one contract module)
from app.models.domain import InvestigationRecord  # noqa: E402,F401


class MeResponse(BaseModel):
    """The authenticated caller, as the UI needs it. Contains no credential or token material."""

    principal_id: str
    user_id: str
    display_name: str
    principal_type: str
    is_human: bool
    tenant_id: str
    tenant_name: str | None = None
    roles: list[str]
    permissions: list[str]
    auth_method: str


class WorkflowSummary(BaseModel):
    """One row of the reviewer queue. ``can_decide`` is a server-computed hint; the decision endpoint stays authoritative."""

    workflow_id: str
    incident_id: str
    action: str
    requested_by: str
    risk_level: str
    requires_approval: bool
    status: str
    policy_decision: str | None = None
    decision: str | None = None
    reviewer: str | None = None
    investigation_id: str | None = None
    investigation_summary: str | None = None  # AI-generated, untrusted
    investigation_confidence: float | None = None
    can_decide: bool = False
    decision_blocked_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    items: list[WorkflowSummary]
    total: int
    limit: int
    offset: int


class AuditTimelineEntry(BaseModel):
    """An audit event without its free-form metadata (which can carry untrusted AI or event content)."""

    audit_id: str | None = None
    event_type: str
    description: str
    actor: str | None = None
    actor_type: str | None = None
    timestamp: datetime


class HitlState(BaseModel):
    required: bool
    state: str  # not_required | awaiting_decision | approved | rejected
    decision: str | None = None
    reviewer: str | None = None
    can_decide: bool = False
    decision_blocked_reason: str | None = None


class IncidentDetailResponse(BaseModel):
    incident: IncidentResponse
    workflow: WorkflowResponse | None = None
    # completed (a grounded record is stored) | degraded | failed | pending | unavailable
    investigation_status: str
    investigation: InvestigationRecord | None = None
    hitl: HitlState
    audit_timeline: list[AuditTimelineEntry] = Field(default_factory=list)


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
