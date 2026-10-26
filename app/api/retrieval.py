from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.security import Permission, Principal, get_principal, require_permission
from app.retrieval.service import IncidentRetrievalService

router = APIRouter(prefix="/retrieval", dependencies=[Depends(get_principal)])


@router.get("/incidents/{incident_id}")
async def get_incident_retrieval(
    incident_id: str,
    principal: Principal = Depends(require_permission(Permission.INCIDENT_READ)),
) -> dict[str, Any]:
    service = IncidentRetrievalService(database_url=get_settings().database_url, tenant_id=principal.tenant_id)
    try:
        result = service.get_incident_context(incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/services/{service_id}/dependencies")
async def get_service_dependencies(
    service_id: str,
    principal: Principal = Depends(require_permission(Permission.INCIDENT_READ)),
) -> dict[str, Any]:
    service = IncidentRetrievalService(database_url=get_settings().database_url, tenant_id=principal.tenant_id)
    return {"service_id": service_id, "dependencies": service.get_service_dependencies(service_id)}


@router.get("/services/{service_id}/incidents")
async def get_service_incidents(
    service_id: str,
    principal: Principal = Depends(require_permission(Permission.INCIDENT_READ)),
) -> dict[str, Any]:
    service = IncidentRetrievalService(database_url=get_settings().database_url, tenant_id=principal.tenant_id)
    return {"service_id": service_id, "incidents": service.get_related_incidents(service_id)}
