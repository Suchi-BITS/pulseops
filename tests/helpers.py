"""Shared test helpers (Gate 9): act as a specific principal through the development-only header."""

from __future__ import annotations

from app.agent.service import IdentityContext
from app.core.config import DEV_TENANT_ID

DEV_TENANT = DEV_TENANT_ID
# Identity context of an authenticated principal of the development tenant (what the API derives from a request).
DEV_IDENTITY = IdentityContext(tenant_id=DEV_TENANT_ID, user_id="test-user", roles=["operator"], permissions=["incident:read"])


def as_principal(principal_id: str, *roles: str, kind: str = "human") -> dict[str, str]:
    """Headers for ``X-Dev-Principal: <type>:<id>:<role>+<role>`` (accepted only in the development environment)."""
    return {"X-Dev-Principal": f"{kind}:{principal_id}:{'+'.join(roles)}"}


REVIEWER = as_principal("reviewer-rita", "reviewer", "sre", "incident_manager", "release_manager")
OPERATOR = as_principal("operator-omar", "operator")
ADMIN = as_principal("admin-ada", "admin")
N8N = as_principal("svc-n8n", "service_n8n", kind="service")
AGENT = as_principal("claude", "reviewer", kind="agent")


def provision_members(database_url: str, tenant_id: str, members: dict[str, tuple[str, str, tuple[str, ...]]],
                      tenant_name: str | None = None) -> None:
    """Idempotently create a tenant (if needed), users and active memberships: ``{user_id: (type, role, domain_roles)}``.

    Users are global and shared across tenants; only the membership (and so the role) is per tenant.
    """
    from app.repositories.tenant_repository import TenantRepository

    repo = TenantRepository(database_url)
    if repo.get_tenant(tenant_id) is None:
        repo.create_tenant(tenant_id, tenant_name or tenant_id)
    for user_id, (user_type, role, domain) in members.items():
        if repo.get_user(user_id) is None:
            repo.create_user(user_id, user_id, user_type=user_type)
        if repo.resolve_active_membership(tenant_id, user_id) is None and not any(
            t == tenant_id for t, _, _ in repo.list_memberships(user_id)
        ):
            repo.add_membership(tenant_id, user_id, role, domain_roles=domain)
