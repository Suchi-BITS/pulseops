"""Tenant catalog: Tenant, User and TenantUser (Gate 9.1).

A user may belong to many tenants; the role belongs to the *membership*, not the user. This repository is the only
code that reads or writes the catalog tables. Authorization decisions (``resolve_active_membership``) fail closed:
a missing tenant, user or membership, or any inactive one, resolves to ``None``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database import TENANT_ROLES, USER_TYPES, DatabaseManager

_ID_PATTERN = re.compile(r"^[A-Za-z0-9._@:-]{1,128}$")
_STATUSES = ("active", "inactive")
# Domain roles (e.g. sre, incident_manager) match a policy rule's permitted_roles; they grant no application permission.
_DOMAIN_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    tenant_name: str
    status: str


@dataclass(frozen=True)
class User:
    user_id: str
    email: str | None
    display_name: str
    user_type: str
    status: str


@dataclass(frozen=True)
class Membership:
    """An *active* tenant membership joined with its (active) tenant and user."""

    tenant_id: str
    user_id: str
    user_type: str
    display_name: str
    role: str
    domain_roles: tuple[str, ...]

    @property
    def roles(self) -> tuple[str, ...]:
        return (self.role, *self.domain_roles)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise ValueError(f"invalid {label}")
    return value


class TenantRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._db = DatabaseManager(database_url)

    def _connect(self) -> sqlite3.Connection:
        return self._db.get_connection()

    # --- tenants ---------------------------------------------------------------------------------------------
    def create_tenant(self, tenant_id: str, tenant_name: str, status: str = "active") -> Tenant:
        _check_id(tenant_id, "tenant_id")
        if not tenant_name or not tenant_name.strip():
            raise ValueError("tenant_name is required")
        if status not in _STATUSES:
            raise ValueError("invalid tenant status")
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO tenants (tenant_id, tenant_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (tenant_id, tenant_name.strip(), status, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"tenant '{tenant_id}' already exists") from exc
        return Tenant(tenant_id, tenant_name.strip(), status)

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
        return Tenant(row["tenant_id"], row["tenant_name"], row["status"]) if row else None

    def set_tenant_status(self, tenant_id: str, status: str) -> None:
        if status not in _STATUSES:
            raise ValueError("invalid tenant status")
        with self._connect() as connection:
            connection.execute("UPDATE tenants SET status = ?, updated_at = ? WHERE tenant_id = ?", (status, _now(), tenant_id))

    # --- users -----------------------------------------------------------------------------------------------
    def create_user(
        self, user_id: str, display_name: str, *, email: str | None = None, user_type: str = "human", status: str = "active"
    ) -> User:
        _check_id(user_id, "user_id")
        if not display_name or not display_name.strip():
            raise ValueError("display_name is required")
        if user_type not in USER_TYPES:
            raise ValueError("invalid user_type")
        if status not in _STATUSES:
            raise ValueError("invalid user status")
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (user_id, email, display_name, user_type, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, email, display_name.strip(), user_type, status, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user '{user_id}' (or its email) already exists") from exc
        return User(user_id, email, display_name.strip(), user_type, status)

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return User(row["user_id"], row["email"], row["display_name"], row["user_type"], row["status"]) if row else None

    def set_user_status(self, user_id: str, status: str) -> None:
        if status not in _STATUSES:
            raise ValueError("invalid user status")
        with self._connect() as connection:
            connection.execute("UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?", (status, _now(), user_id))

    # --- memberships -----------------------------------------------------------------------------------------
    def add_membership(
        self, tenant_id: str, user_id: str, role: str, *, domain_roles: tuple[str, ...] | list[str] = (), status: str = "active"
    ) -> None:
        if role not in TENANT_ROLES:
            raise ValueError(f"invalid role '{role}'")
        if status not in _STATUSES:
            raise ValueError("invalid membership status")
        domain = tuple(domain_roles)
        if not all(isinstance(r, str) and _DOMAIN_ROLE_PATTERN.match(r) and r not in TENANT_ROLES for r in domain):
            raise ValueError("domain_roles must be lowercase names that are not application roles")
        user = self.get_user(user_id)
        if user is None:
            raise ValueError(f"unknown user '{user_id}'")
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"unknown tenant '{tenant_id}'")
        if user.user_type != "human" and role == "reviewer":
            raise ValueError("only a human user may hold the reviewer role")
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO tenant_users (tenant_id, user_id, role, domain_roles, status, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tenant_id, user_id, role, json.dumps(list(domain)), status, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user '{user_id}' is already a member of tenant '{tenant_id}'") from exc

    def set_membership_status(self, tenant_id: str, user_id: str, status: str) -> None:
        if status not in _STATUSES:
            raise ValueError("invalid membership status")
        with self._connect() as connection:
            connection.execute(
                "UPDATE tenant_users SET status = ?, updated_at = ? WHERE tenant_id = ? AND user_id = ?",
                (status, _now(), tenant_id, user_id),
            )

    def resolve_active_membership(self, tenant_id: str, user_id: str) -> Membership | None:
        """The membership only if tenant, user and membership all exist and are active (otherwise ``None``)."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT m.tenant_id, m.user_id, m.role, m.domain_roles, u.user_type, u.display_name
                FROM tenant_users m
                JOIN tenants t ON t.tenant_id = m.tenant_id AND t.status = 'active'
                JOIN users u ON u.user_id = m.user_id AND u.status = 'active'
                WHERE m.tenant_id = ? AND m.user_id = ? AND m.status = 'active'
                """,
                (tenant_id, user_id),
            ).fetchone()
        if row is None or row["role"] not in TENANT_ROLES:
            return None
        if row["user_type"] != "human" and row["role"] == "reviewer":
            return None  # fail closed on an inconsistent row: only humans review
        return Membership(
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            user_type=row["user_type"],
            display_name=row["display_name"],
            role=row["role"],
            domain_roles=tuple(json.loads(row["domain_roles"] or "[]")),
        )

    def list_memberships(self, user_id: str) -> list[tuple[str, str, str]]:
        """(tenant_id, role, status) for every tenant the user belongs to."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT tenant_id, role, status FROM tenant_users WHERE user_id = ? ORDER BY tenant_id", (user_id,)
            ).fetchall()
        return [(r["tenant_id"], r["role"], r["status"]) for r in rows]
