from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.api.workflow as workflow_api
from app.agent.service import IncidentInvestigationAgent, InvestigationResult
from app.core.config import get_settings
from app.core.security import Permission, Principal, get_principal, identity_context_for, require_permission

router = APIRouter(prefix="/agent", dependencies=[Depends(get_principal)])


class InvestigateRequest(BaseModel):
    incident_id: str
    objective: str | None = None


@router.post("/investigate")
async def investigate_incident(
    payload: InvestigateRequest,
    principal: Principal = Depends(require_permission(Permission.AGENT_INVESTIGATE)),
) -> InvestigationResult:
    agent = IncidentInvestigationAgent(database_url=get_settings().database_url)
    # The agent's identity context (including its tenant) comes from the authenticated principal, never from request
    # fields. The incident must exist in that tenant; another tenant's incident is indistinguishable from a missing one.
    if workflow_api.incident_service_for(principal.tenant_id).get_incident(payload.incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    result = await agent.investigate(payload.incident_id, payload.objective, identity_context=identity_context_for(principal))
    return result
