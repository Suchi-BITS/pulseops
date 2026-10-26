from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrustLevel(str, Enum):
    TRUSTED = "trusted"
    CONTROLLED = "controlled"
    UNTRUSTED = "untrusted"


class EvidenceSourceType(str, Enum):
    INCIDENT = "incident"
    LOG = "log"
    METRIC = "metric"
    DEPLOYMENT = "deployment"
    REPOSITORY = "repository"
    HISTORICAL_INCIDENT = "historical_incident"
    GRAPH_RELATIONSHIP = "graph_relationship"


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: str
    source_type: EvidenceSourceType
    source_id: str
    timestamp: datetime | None = None
    content: str
    trust_level: TrustLevel = TrustLevel.TRUSTED
    relevance: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestigationContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident: str
    affected_service: str
    related_services: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    recent_deployments: list[str] = Field(default_factory=list)
    historical_incidents: list[str] = Field(default_factory=list)
    repository_context: list[str] = Field(default_factory=list)
    graph_relationships: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_dump_json(self, **kwargs: Any) -> str:
        return super().model_dump_json(**kwargs)
