from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import get_settings
from app.core.errors import ApiError, PulseOpsError
from app.core.request_context import bind
from app.core.security import Permission, Principal, get_principal, require_permission
from app.models.schemas import (
    OperationalEvent,
    WorkflowDecisionRequest,
    WorkflowEvaluationRequest,
    WorkflowEventResponse,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
)
from app.services.event_service import OperationalEventService
from app.services.incident_service import IncidentService
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflow", tags=["workflow"], dependencies=[Depends(get_principal)])


# Services are tenant-bound and built per request from the authenticated principal's tenant. There are no shared
# module-level instances, so no code path can reach another tenant's data by accident.
def incident_service_for(tenant_id: str) -> IncidentService:
    return IncidentService(database_url=get_settings().database_url, tenant_id=tenant_id)


def workflow_service_for(tenant_id: str) -> WorkflowService:
    return WorkflowService(database_url=get_settings().database_url, tenant_id=tenant_id)


def event_service_for(tenant_id: str) -> OperationalEventService:
    return OperationalEventService(
        incident_service=incident_service_for(tenant_id),
        workflow_service=workflow_service_for(tenant_id),
        database_url=get_settings().database_url,
        tenant_id=tenant_id,
    )


def _workflow_http_error(exc: Exception) -> HTTPException:
    """Map a failure to an HTTP error by its TYPE (never by the words in its message).

    Typed domain errors carry their own status and code (``NotFoundError`` 404, ``ConflictError`` 409). Any other
    ``ValueError`` is a plain validation failure (400).
    """
    if isinstance(exc, PulseOpsError):
        return exc.to_api_error()
    return ApiError(status.HTTP_400_BAD_REQUEST, str(exc))


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def evaluate_for_principal(payload: WorkflowEvaluationRequest, principal: Principal) -> WorkflowResponse:
    """Evaluate an action for an incident.

    The requester is the authenticated principal. ``payload.requested_by`` is caller-supplied, so it is never trusted.
    """
    if payload.incident_id is None or not payload.incident_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="incident_id is required")
    if not payload.action.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action is required")
    if payload.idempotency_key is not None and not payload.idempotency_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="idempotency_key must not be empty")
    if payload.severity is not None and payload.severity.strip() not in {"low", "medium", "high", "critical"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="severity must be low, medium, high, or critical")
    bind(incident_id=payload.incident_id)
    try:
        result = workflow_service_for(principal.tenant_id).evaluate_incident_action(
            incident_id=payload.incident_id,
            action=payload.action,
            requested_by=principal.principal_id,
            details=payload.details,
            severity=payload.severity,
            idempotency_key=payload.idempotency_key,
            actor_type=principal.principal_type.value,
        )
        bind(workflow_id=result.get("workflow_id"))
        return WorkflowResponse.model_validate(result)
    except (ValueError, KeyError) as exc:
        raise _workflow_http_error(exc) from exc


def _principal_decision_failure(principal: Principal) -> str | None:
    """Why this principal may not record approval decisions at all (None = it may)."""
    if not principal.is_human:
        return "Only an authenticated human principal may record an approval decision"
    if not principal.has(Permission.WORKFLOW_APPROVE):
        return f"Not authorized: {Permission.WORKFLOW_APPROVE.value} required"
    return None


def _pending_decision_failure(workflow: dict, principal: Principal, workflow_service: WorkflowService) -> str | None:
    """Why this principal may not decide THIS pending HITL workflow: role not permitted for the action, or self-approval."""
    permitted = set(workflow_service.policy_engine.evaluate(workflow["action"])["permitted_roles"])
    if "admin" not in principal.roles and not (set(principal.roles) & permitted):
        return "Not authorized to approve this action: a role permitted for the action is required"
    if workflow["requested_by"] == principal.principal_id:
        return "Self-approval is not allowed: the requester cannot approve their own workflow"
    return None


def decision_hint(workflow: dict, principal: Principal, workflow_service: WorkflowService) -> tuple[bool, str | None]:
    """``(can_decide, reason)``: the same rules ``decide_for_principal`` enforces, evaluated read-only for the UI.

    A hint only. The decision endpoint re-checks everything and is the single authority.
    """
    if not (workflow["requires_approval"] and workflow["status"] == "pending"):
        return False, "No approval decision is pending for this workflow"
    failure = _principal_decision_failure(principal) or _pending_decision_failure(workflow, principal, workflow_service)
    return failure is None, failure


def decide_for_principal(workflow_id: str, payload: WorkflowDecisionRequest, principal: Principal) -> WorkflowResponse:
    """Record an approve/reject decision made by the authenticated principal.

    The reviewer is ALWAYS the authenticated principal. A supplied ``reviewer`` is never authoritative: if present it
    must equal the principal id, otherwise the request is rejected (403). Authorization (RBAC, policy
    ``permitted_roles``, no self-approval) is checked here, separately from and before the deterministic rules the
    workflow service enforces (DENY, final states, AI actors, idempotency, conflicts), which are unchanged.
    """
    # Tenant first: the workflow is looked up inside the principal's tenant only, so another tenant's workflow is
    # indistinguishable from a missing one (404) before any role or state is considered.
    workflow_service = workflow_service_for(principal.tenant_id)
    workflow = workflow_service.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown workflow_id: {workflow_id}")
    bind(workflow_id=workflow_id, incident_id=workflow["incident_id"])
    failure = _principal_decision_failure(principal)
    if failure is not None:
        raise _forbidden(failure)
    if payload.reviewer is not None and payload.reviewer.strip() != principal.principal_id:
        raise _forbidden("reviewer does not match the authenticated principal")
    if payload.decision is None or payload.decision.strip().lower() not in {"approve", "reject"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="decision must be 'approve' or 'reject'")
    if payload.idempotency_key is not None and not payload.idempotency_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="idempotency_key must not be empty")
    if workflow["requires_approval"] and workflow["status"] == "pending":
        # A live HITL decision. Final, denied or already-decided workflows fall through to the service, which keeps
        # its existing 409 conflict / idempotency behaviour.
        failure = _pending_decision_failure(workflow, principal, workflow_service)
        if failure is not None:
            raise _forbidden(failure)
    try:
        result = workflow_service.record_decision(
            workflow_id,
            decision=payload.decision,
            reviewer=principal.principal_id,
            rationale=payload.rationale,
            incident_id=payload.incident_id,
            action=payload.action,
            timestamp=payload.timestamp,
            idempotency_key=payload.idempotency_key,
            actor_type=principal.principal_type.value,
            actor_roles=list(principal.roles),
        )
        return WorkflowResponse.model_validate(result)
    except (ValueError, KeyError) as exc:
        raise _workflow_http_error(exc) from exc


@router.post("/evaluate")
async def evaluate_incident_workflow(
    payload: WorkflowEvaluationRequest,
    principal: Principal = Depends(require_permission(Permission.WORKFLOW_EVALUATE)),
) -> WorkflowResponse:
    return evaluate_for_principal(payload, principal)


@router.post("/events")
async def ingest_operational_event(
    event: OperationalEvent,
    principal: Principal = Depends(require_permission(Permission.EVENTS_INGEST)),
) -> WorkflowEventResponse:
    """Operational-event boundary for the n8n orchestration layer (see docs/phase-7-gate-6.md).

    Thin: event idempotency, incident creation, Phase 6 investigation and deterministic policy
    evaluation all live in ``OperationalEventService``. The requester is the authenticated principal.
    """
    if event.tenant_id is not None and event.tenant_id != principal.tenant_id:
        raise _forbidden("The event names a tenant this credential is not authorized for")
    try:
        result = await event_service_for(principal.tenant_id).ingest(event, principal)
    except PermissionError as exc:
        raise _forbidden(str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise _workflow_http_error(exc) from exc
    return WorkflowEventResponse.model_validate(result)


@router.post("/webhook", deprecated=True)
async def workflow_webhook(
    payload: WorkflowEvaluationRequest,
    principal: Principal = Depends(require_permission(Permission.WORKFLOW_EVALUATE)),
) -> WorkflowResponse:
    return evaluate_for_principal(payload, principal)


@router.get("")
async def list_workflows(
    workflow_status: Literal["pending", "approved", "rejected", "audited"] | None = Query(default=None, alias="status"),
    incident_id: str | None = Query(default=None, max_length=128),
    requires_approval: bool | None = None,
    sort: Literal["created_at", "updated_at", "status"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_permission(Permission.WORKFLOW_READ)),
) -> WorkflowListResponse:
    """Reviewer queue (read-only, tenant-scoped). The pending approval queue is ``?status=pending&requires_approval=true``.

    The tenant is always the authenticated principal's; a ``tenant_id`` query parameter does not exist and is ignored.
    """
    service = workflow_service_for(principal.tenant_id)
    rows, total = service.list_workflows(
        status=workflow_status, incident_id=incident_id, requires_approval=requires_approval,
        sort=sort, descending=order == "desc", limit=limit, offset=offset,
    )
    items = []
    for row in rows:
        can_decide, reason = decision_hint(
            {"requires_approval": bool(row["requires_approval"]), "status": row["status"], "action": row["action"],
             "requested_by": row["requested_by"]}, principal, service,
        )
        items.append(WorkflowSummary(
            workflow_id=row["workflow_id"], incident_id=row["incident_id"], action=row["action"],
            requested_by=row["requested_by"], risk_level=row["risk_level"],
            requires_approval=bool(row["requires_approval"]), status=row["status"],
            policy_decision=row["policy_decision"], decision=row["latest_decision"], reviewer=row["latest_reviewer"],
            investigation_id=row["investigation_id"], investigation_summary=row["investigation_summary"],
            investigation_confidence=row["investigation_confidence"],
            can_decide=can_decide, decision_blocked_reason=reason,
            created_at=row["created_at"], updated_at=row["updated_at"],
        ))
    return WorkflowListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str, principal: Principal = Depends(require_permission(Permission.WORKFLOW_READ))
) -> WorkflowResponse:
    workflow = workflow_service_for(principal.tenant_id).get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return WorkflowResponse.model_validate(workflow)


@router.post("/{workflow_id}/decision")
async def record_workflow_decision(
    workflow_id: str,
    payload: WorkflowDecisionRequest,
    principal: Principal = Depends(get_principal),
) -> WorkflowResponse:
    return decide_for_principal(workflow_id, payload, principal)


@router.post("/incidents/{incident_id}/evaluate", deprecated=True)
async def evaluate_incident_workflow_for_incident(
    incident_id: str,
    payload: WorkflowEvaluationRequest,
    principal: Principal = Depends(require_permission(Permission.WORKFLOW_EVALUATE)),
) -> WorkflowResponse:
    payload_data = payload.model_copy(update={"incident_id": incident_id})
    if not incident_service_for(principal.tenant_id).get_incident(incident_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return evaluate_for_principal(payload_data, principal)


@router.post("/incidents/{incident_id}/decision", deprecated=True)
async def record_incident_workflow_decision(
    incident_id: str,
    payload: WorkflowDecisionRequest,
    principal: Principal = Depends(get_principal),
) -> WorkflowResponse:
    if not incident_service_for(principal.tenant_id).get_incident(incident_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    workflow = workflow_service_for(principal.tenant_id).get_latest_workflow_for_incident(incident_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No workflow exists for incident")
    workflow_id = payload.workflow_id or workflow["workflow_id"]
    return decide_for_principal(workflow_id, payload, principal)
