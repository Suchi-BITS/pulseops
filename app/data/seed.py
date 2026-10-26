from __future__ import annotations

from datetime import datetime, timezone

from app.models.domain import (
    AccessMode,
    Deployment,
    DeploymentStatus,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    LogEntry,
    LogLevel,
    Metric,
    Repository,
    RepositoryMapping,
    Service,
)


SERVICE_SEED = [
    Service(
        service_id="svc-payment",
        service_name="payment-service",
        owner_team="payments",
        environment="production",
        repository_id="repo-payment",
        description="Handles payment processing",
        created_at=datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc),
    )
]

REPOSITORY_SEED = [
    Repository(
        repository_id="repo-payment",
        provider="github",
        owner="organization",
        name="payment-service",
        default_branch="main",
        access_mode=AccessMode.READ_ONLY,
        active=True,
    )
]

REPOSITORY_MAPPING_SEED = [
    RepositoryMapping(
        mapping_id="map-payment",
        service_id="svc-payment",
        repository_id="repo-payment",
        branch="main",
        path_prefix="src/payment",
        active=True,
    )
]

INCIDENT_SEED = [
    Incident(
        incident_id="INC-1007",
        service_id="svc-payment",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.OPEN,
        title="Payment service latency spike",
        description="Elevated latency and error rate during payment processing",
        environment="production",
        started_at=datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc),
    )
]

LOG_SEED = [
    LogEntry(
        log_id="log-10001",
        incident_id="INC-1007",
        service_id="svc-payment",
        timestamp=datetime(2026, 9, 29, 9, 31, 10, tzinfo=timezone.utc),
        level=LogLevel.ERROR,
        message="Database connection pool exhausted",
        source="payment-service",
        metadata={"thread": "worker-3"},
    )
]

METRIC_SEED = [
    Metric(
        metric_id="metric-20001",
        incident_id="INC-1007",
        service_id="svc-payment",
        timestamp=datetime(2026, 9, 29, 9, 31, 0, tzinfo=timezone.utc),
        metric_name="error_rate",
        value=18.4,
        unit="percent",
        source="synthetic-monitoring",
    )
]

DEPLOYMENT_SEED = [
    Deployment(
        deployment_id="deploy-30001",
        service_id="svc-payment",
        version="2026.09.29.1",
        commit_sha="abc1234",
        environment="production",
        deployed_at=datetime(2026, 9, 29, 8, 45, tzinfo=timezone.utc),
        deployed_by="release-bot",
        status=DeploymentStatus.SUCCESSFUL,
    )
]
