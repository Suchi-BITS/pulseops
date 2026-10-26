from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

import app.api.workflow as workflow_api
from app.core.security import Permission, Principal, get_principal, require_permission
from app.models.schemas import (
    AuditTimelineEntry,
    HitlState,
    IncidentCreateRequest,
    IncidentDetailResponse,
    IncidentListItem,
    IncidentResponse,
    InvestigationRecord,
    WorkflowDecisionRequest,
    WorkflowEvaluationRequest,
    WorkflowResponse,
)
router = APIRouter(prefix="/incidents", dependencies=[Depends(get_principal)])


@router.post("")
async def create_incident(
    payload: IncidentCreateRequest,
    principal: Principal = Depends(require_permission(Permission.INCIDENT_WRITE)),
) -> IncidentResponse:
    try:
        incident = workflow_api.incident_service_for(principal.tenant_id).create_incident(
            service_id=payload.service_id,
            severity=payload.severity,
            title=payload.title,
            description=payload.description,
            environment=payload.environment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IncidentResponse.model_validate(incident.model_dump(mode="json"))


@router.get("")
async def list_incidents(
    response: Response,
    incident_status: Literal["open", "investigating", "mitigated", "resolved", "closed"] | None = Query(default=None, alias="status"),
    severity: Literal["low", "medium", "high", "critical"] | None = None,
    service_id: str | None = Query(default=None, max_length=128),
    sort: Literal["started_at", "created_at", "incident_id", "status", "severity"] = "started_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_permission(Permission.INCIDENT_READ)),
) -> list[IncidentListItem]:
    """The tenant's incidents, one page at a time. The body stays a JSON list (existing clients); the number of
    incidents matching the filters is returned in ``X-Total-Count``. The tenant is always the principal's."""
    incidents, total = workflow_api.incident_service_for(principal.tenant_id).list_incidents_page(
        status=incident_status, severity=severity, service_id=service_id,
        sort=sort, descending=order == "desc", limit=limit, offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return [
        IncidentListItem(
            incident_id=incident.incident_id,
            service_id=incident.service_id,
            severity=incident.severity.value,
            status=incident.status.value,
            title=incident.title,
            environment=incident.environment,
            started_at=incident.started_at,
        )
        for incident in incidents
    ]


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str, principal: Principal = Depends(require_permission(Permission.INCIDENT_READ))
) -> IncidentResponse:
    incident = workflow_api.incident_service_for(principal.tenant_id).get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentResponse.model_validate(incident.model_dump(mode="json"))


@router.post("/{incident_id}/workflow/evaluate")
async def evaluate_incident_workflow(
    incident_id: str,
    payload: WorkflowEvaluationRequest,
    principal: Principal = Depends(require_permission(Permission.WORKFLOW_EVALUATE)),
) -> WorkflowResponse:
    """Same behaviour (and the same authorization) as ``POST /workflow/incidents/{id}/evaluate``."""
    request = payload.model_copy(update={"incident_id": incident_id})
    if not workflow_api.incident_service_for(principal.tenant_id).get_incident(incident_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return workflow_api.evaluate_for_principal(request, principal)


@router.post("/{incident_id}/workflow/decision")
async def record_incident_workflow_decision(
    incident_id: str,
    payload: WorkflowDecisionRequest,
    principal: Principal = Depends(get_principal),
) -> WorkflowResponse:
    """Same authorization as ``POST /workflow/{id}/decision``: the reviewer is the authenticated principal."""
    workflow = workflow_api.workflow_service_for(principal.tenant_id).get_latest_workflow_for_incident(incident_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No workflow exists for incident")
    return workflow_api.decide_for_principal(workflow["workflow_id"], payload, principal)


@router.get("/{incident_id}/investigations")
async def list_incident_investigations(
    incident_id: str, principal: Principal = Depends(require_permission(Permission.INCIDENT_READ))
) -> list[InvestigationRecord]:
    """Stored, grounded investigation records for an incident, newest first. AI-generated content: evidence,
    hypotheses, missing information and recommendations are separate fields and are data, never instructions."""
    if workflow_api.incident_service_for(principal.tenant_id).get_incident(incident_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return workflow_api.workflow_service_for(principal.tenant_id).investigations.list_for_incident(incident_id)


@router.get("/{incident_id}/detail", dependencies=[Depends(require_permission(Permission.WORKFLOW_READ))])
async def get_incident_detail(
    incident_id: str, principal: Principal = Depends(require_permission(Permission.INCIDENT_READ))
) -> IncidentDetailResponse:
    """Everything the incident page needs in one read: incident, latest workflow, its investigation, HITL state and
    audit timeline. Read-only; approvals still go through the decision endpoints."""
    incident = workflow_api.incident_service_for(principal.tenant_id).get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    workflow_service = workflow_api.workflow_service_for(principal.tenant_id)
    workflow = workflow_service.get_latest_workflow_for_incident(incident_id)
    investigation = None
    investigation_status = "unavailable"
    hitl = HitlState(required=False, state="not_required")
    timeline: list[AuditTimelineEntry] = []
    if workflow is not None:
        investigation = workflow_service.investigations.get_for_workflow(workflow["workflow_id"])
        policy_decision = workflow.get("policy_decision")
        if investigation is not None:
            investigation_status = "completed"
        elif policy_decision == "investigation_degraded":
            investigation_status = "degraded"
        elif policy_decision == "investigation_failed":
            investigation_status = "failed"
        elif policy_decision == "investigation_pending":
            investigation_status = "pending"
        decisions = workflow_service.repository.list_decisions_for_workflow(workflow["workflow_id"])
        latest = decisions[-1] if decisions else None
        can_decide, reason = workflow_api.decision_hint(workflow, principal, workflow_service)
        if workflow["status"] == "approved":
            state = "approved"
        elif workflow["status"] == "rejected" and latest is not None and latest.decision.value == "reject":
            state = "rejected"
        elif workflow["requires_approval"] and workflow["status"] == "pending":
            state = "awaiting_decision"
        else:
            state = "not_required"
        hitl = HitlState(
            required=bool(workflow["requires_approval"]) or latest is not None, state=state,
            decision=latest.decision.value if latest else None, reviewer=latest.actor_id if latest else None,
            can_decide=can_decide, decision_blocked_reason=None if can_decide or state != "awaiting_decision" else reason,
        )
        timeline = [
            AuditTimelineEntry(
                audit_id=event.get("audit_id"), event_type=event["event_type"], description=event["description"],
                actor=event.get("actor"), actor_type=event.get("actor_type"), timestamp=event["timestamp"],
            )
            for event in workflow["audit_events"]
        ]
    return IncidentDetailResponse(
        incident=IncidentResponse.model_validate(incident.model_dump(mode="json")),
        workflow=WorkflowResponse.model_validate(workflow) if workflow is not None else None,
        investigation_status=investigation_status,
        investigation=investigation,
        hitl=hitl,
        audit_timeline=timeline,
    )
