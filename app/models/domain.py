from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUDITED = "audited"


class ApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DeploymentStatus(str, Enum):
    STARTED = "started"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class AccessMode(str, Enum):
    READ_ONLY = "read_only"


class Service(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_id: str
    service_name: str
    owner_team: str
    environment: str
    repository_id: str | None = None
    description: str | None = None
    created_at: datetime


class Incident(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: str
    service_id: str
    severity: IncidentSeverity
    status: IncidentStatus
    title: str
    description: str
    environment: str
    started_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: str
    incident_id: str | None = None
    service_id: str
    timestamp: datetime
    level: LogLevel
    message: str
    source: str
    metadata: dict[str, object] | None = None


class Metric(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: str
    incident_id: str | None = None
    service_id: str
    timestamp: datetime
    metric_name: str
    value: float
    unit: str | None = None
    source: str


class Deployment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deployment_id: str
    service_id: str
    version: str
    commit_sha: str | None = None
    environment: str
    deployed_at: datetime
    deployed_by: str | None = None
    status: DeploymentStatus


class Repository(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repository_id: str
    provider: str
    owner: str
    name: str
    default_branch: str
    access_mode: AccessMode
    active: bool = True


class RepositoryMapping(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mapping_id: str
    service_id: str
    repository_id: str
    branch: str
    path_prefix: str | None = None
    active: bool = True


class AuditEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: str | None = None
    event_id: str | None = None
    tenant_id: str | None = None
    event_type: str
    description: str
    actor: str | None = None
    actor_type: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: datetime


class HumanReview(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: str
    incident_id: str
    workflow_id: str
    reviewer: str
    decision: ApprovalDecision
    rationale: str | None = None
    created_at: datetime


class WorkflowDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision_id: str
    workflow_id: str
    decision: ApprovalDecision
    actor_id: str
    actor_type: str = "reviewer"
    reason: str | None = None
    timestamp: datetime


class IncidentWorkflow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    incident_id: str
    action: str
    requested_by: str
    details: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    policy_decision: str | None = None
    requires_approval: bool = False
    status: WorkflowStatus = WorkflowStatus.PENDING
    decision: ApprovalDecision | None = None
    reviewer: str | None = None
    rationale: str | None = None
    created_at: datetime
    updated_at: datetime
    audit_events: list[AuditEvent] = Field(default_factory=list)


class InvestigationRecord(BaseModel):
    """A stored, grounded ``InvestigationResult`` (P9.1): one per workflow, owned by exactly one tenant.

    The four epistemic categories stay separate fields. Everything here is AI-generated and untrusted data: it is
    shown to humans, never executed and never treated as an instruction.
    """

    model_config = ConfigDict(from_attributes=True)

    investigation_id: str
    tenant_id: str
    incident_id: str
    workflow_id: str
    service_id: str = "unknown"
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_calls: list[str] = Field(default_factory=list)
    source: str = "workflow"  # "workflow" (persisted live) or "backfill" (copied from a pre-P9 audit event)
    created_at: datetime
