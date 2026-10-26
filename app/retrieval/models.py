from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IncidentRetrievalResult(BaseModel):
    incident_id: str
    service_id: str
    title: str
    severity: str
    status: str
    repository_id: str | None = None
    deployment_ids: list[str] = Field(default_factory=list)
    related_services: list[str] = Field(default_factory=list)
    related_incidents: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
