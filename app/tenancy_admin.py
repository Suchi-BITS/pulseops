"""Operator CLI for the tenant catalog (Gate 9.1). There is no public API for this: provisioning is an operator action.

    python -m app.tenancy_admin create-tenant acme "Acme Corp"
    python -m app.tenancy_admin create-user alice "Alice A." --email alice@example.com
    python -m app.tenancy_admin create-user svc-n8n "n8n" --type service
    python -m app.tenancy_admin add-member acme alice reviewer --domain-roles sre,incident_manager
    python -m app.tenancy_admin set-membership acme alice inactive

Then bind a bearer credential to (user, tenant) in PULSEOPS_API_CREDENTIALS:
    {"principal_id": "alice", "tenant_id": "acme", "token_sha256": "<python -m app.core.credentials --generate>"}
The database is PULSEOPS_DATABASE_URL (or --database-url).
"""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.repositories.tenant_repository import TenantRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tenancy_admin")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-tenant")
    p.add_argument("tenant_id")
    p.add_argument("tenant_name")
    p = sub.add_parser("create-user")
    p.add_argument("user_id")
    p.add_argument("display_name")
    p.add_argument("--email")
    p.add_argument("--type", default="human", choices=["human", "service", "agent", "system"])
    p = sub.add_parser("add-member")
    p.add_argument("tenant_id")
    p.add_argument("user_id")
    p.add_argument("role", choices=["service_n8n", "reviewer", "operator", "admin"])
    p.add_argument("--domain-roles", default="", help="comma-separated, e.g. sre,incident_manager")
    p = sub.add_parser("set-membership")
    p.add_argument("tenant_id")
    p.add_argument("user_id")
    p.add_argument("status", choices=["active", "inactive"])
    args = parser.parse_args(argv)

    repo = TenantRepository(args.database_url or get_settings().database_url)
    try:
        if args.command == "create-tenant":
            repo.create_tenant(args.tenant_id, args.tenant_name)
        elif args.command == "create-user":
            repo.create_user(args.user_id, args.display_name, email=args.email, user_type=args.type)
        elif args.command == "add-member":
            repo.add_membership(args.tenant_id, args.user_id, args.role,
                                domain_roles=[r for r in args.domain_roles.split(",") if r])
        else:
            repo.set_membership_status(args.tenant_id, args.user_id, args.status)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
