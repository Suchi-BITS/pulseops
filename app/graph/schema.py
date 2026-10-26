from __future__ import annotations


class GraphSchema:
    """Minimal graph schema contract for the Phase 2 semantic layer."""

    required_classes = {
        "Incident",
        "Service",
        "Application",
        "Repository",
        "Deployment",
        "Environment",
        "Log",
        "Metric",
        "Team",
        "Evidence",
        "Hypothesis",
        "Recommendation",
    }

    required_relationships = {
        "affects",
        "hasEvidence",
        "hasLog",
        "hasMetric",
        "relatedTo",
        "dependsOn",
        "implementedBy",
        "ownedBy",
        "hasDeployment",
        "deployedTo",
    }

    indexes = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Incident) REQUIRE i.incident_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.service_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.repository_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Deployment) REQUIRE d.deployment_id IS UNIQUE",
    ]

    constraints = [
        "CREATE INDEX IF NOT EXISTS FOR (i:Incident) ON (i.service_id)",
        "CREATE INDEX IF NOT EXISTS FOR (s:Service) ON (s.owner_team)",
        "CREATE INDEX IF NOT EXISTS FOR (d:Deployment) ON (d.service_id)",
    ]

    # --- Tenant boundary contract (Gate 9.1; documentation only, nothing here is executed) ------------------------
    # The ontology (ontology/pulseops.ttl: classes, properties, domain/range) is ONE shared, global semantic model.
    # Tenant data are instances of those shared classes. Instances of these classes are tenant-owned and must carry
    # ``tenant_id``; retrieval must always be scoped by it, enforced by the application/repository layer (never by a
    # prompt). The ontology has no Tenant class and none is introduced: isolation is a data-security concern.
    tenant_owned_classes = {
        "Incident", "Service", "Repository", "Deployment", "Log", "Metric", "Evidence", "Hypothesis", "Recommendation",
    }
    # Identity of a tenant-owned instance is (tenant_id, <business id>); the same incident_id may exist in two tenants.
    tenant_scoped_constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Incident) REQUIRE (i.tenant_id, i.incident_id) IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE (s.tenant_id, s.service_id) IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE (r.tenant_id, r.repository_id) IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Deployment) REQUIRE (d.tenant_id, d.deployment_id) IS UNIQUE",
    ]
    # Every future Cypher template is application-owned and must bind $tenant_id in its MATCH, e.g.
    #   MATCH (i:Incident {tenant_id: $tenant_id, incident_id: $incident_id}) ...
    # and relationships may only join nodes with the same tenant_id.
