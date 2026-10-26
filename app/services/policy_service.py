from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    NOTIFY = "notify"
    HITL_REQUIRED = "hitl_required"
    DENY = "deny"


class PolicyRule(BaseModel):
    action: str
    risk_level: str
    decision: PolicyDecision
    requires_approval: bool = False
    requires_human_approval: bool = False
    executable: bool = False
    allowed_action_class: str = "informational"
    permitted_roles: list[str] = Field(default_factory=list)
    description: str = ""


class PolicyEngine:
    """Deterministic policy engine for Phase 7 Gate 1."""

    VALID_RISK_LEVELS = {"low", "medium", "high"}
    VALID_ACTION_CLASSES = {"informational", "guarded", "production"}

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = rules or self._default_registry()

    @staticmethod
    def _default_registry() -> list[PolicyRule]:
        return [
            PolicyRule(
                action="notify",
                risk_level="low",
                decision=PolicyDecision.ALLOW,
                requires_approval=False,
                requires_human_approval=False,
                executable=False,
                allowed_action_class="informational",
                permitted_roles=["operator", "sre", "incident_manager"],
                description="Informational incident notification or status update.",
            ),
            PolicyRule(
                action="page_oncall",
                risk_level="medium",
                decision=PolicyDecision.NOTIFY,
                requires_approval=False,
                requires_human_approval=False,
                executable=False,
                allowed_action_class="informational",
                permitted_roles=["oncall", "sre"],
                description="Escalate attention without changing production state.",
            ),
            PolicyRule(
                action="deploy",
                risk_level="high",
                decision=PolicyDecision.HITL_REQUIRED,
                requires_approval=True,
                requires_human_approval=True,
                executable=False,
                allowed_action_class="guarded",
                permitted_roles=["release_manager", "incident_manager", "sre"],
                description="Deployment action requires explicit human approval.",
            ),
            PolicyRule(
                action="restart_service",
                risk_level="high",
                decision=PolicyDecision.HITL_REQUIRED,
                requires_approval=True,
                requires_human_approval=True,
                executable=False,
                allowed_action_class="guarded",
                permitted_roles=["sre", "incident_manager"],
                description="Service restart action requires explicit human approval.",
            ),
            PolicyRule(
                action="delete_data",
                risk_level="high",
                decision=PolicyDecision.DENY,
                requires_approval=False,
                requires_human_approval=False,
                executable=False,
                allowed_action_class="guarded",
                permitted_roles=["platform_admin"],
                description="Data deletion is denied by policy and never auto-executed.",
            ),
        ]

    @staticmethod
    def normalize_action(action: str) -> str:
        return "_".join(part for part in action.strip().lower().replace("-", "_").replace("/", "_").split() if part)

    @staticmethod
    def _decision_from_risk(risk_level: str) -> PolicyDecision:
        if risk_level == "high":
            return PolicyDecision.HITL_REQUIRED
        if risk_level == "medium":
            return PolicyDecision.NOTIFY
        return PolicyDecision.ALLOW

    @classmethod
    def _validate_rule(cls, rule: PolicyRule) -> bool:
        if rule.risk_level.lower() not in cls.VALID_RISK_LEVELS:
            return False
        if rule.decision not in PolicyDecision:
            return False
        if rule.allowed_action_class.lower() not in cls.VALID_ACTION_CLASSES:
            return False
        if rule.executable:
            return False
        if rule.risk_level.lower() == "high" and rule.decision not in {PolicyDecision.HITL_REQUIRED, PolicyDecision.DENY}:
            return False
        if rule.risk_level.lower() != "high" and rule.decision == PolicyDecision.DENY:
            return False
        return True

    def _find_rule(self, action: str) -> PolicyRule | None:
        normalized = self.normalize_action(action)
        for rule in self._rules:
            if self.normalize_action(rule.action) == normalized:
                return rule
        return None

    def evaluate(
        self,
        action: str,
        *,
        actor: str | None = None,
        role: str | None = None,
        llm_risk_level: str | None = None,
    ) -> dict[str, Any]:
        normalized = self.normalize_action(action)
        if not normalized:
            return {
                "action": "",
                "normalized_action": "",
                "risk_level": "high",
                "decision": PolicyDecision.DENY,
                "requires_approval": False,
                "executable": False,
                "allowed_action_class": "informational",
                "permitted_roles": [],
                "actor": actor,
                "reason": "unknown action",
                "policy_source": "registry",
            }

        rule = self._find_rule(normalized)
        if rule is None:
            return {
                "action": action,
                "normalized_action": normalized,
                "risk_level": "high",
                "decision": PolicyDecision.DENY,
                "requires_approval": False,
                "executable": False,
                "allowed_action_class": "informational",
                "permitted_roles": [],
                "actor": actor,
                "reason": "unknown action",
                "policy_source": "registry",
            }

        if not self._validate_rule(rule):
            return {
                "action": action,
                "normalized_action": normalized,
                "risk_level": "high",
                "decision": PolicyDecision.DENY,
                "requires_approval": False,
                "executable": False,
                "allowed_action_class": "informational",
                "permitted_roles": rule.permitted_roles,
                "actor": actor,
                "reason": "invalid policy configuration",
                "policy_source": "registry",
            }

        if llm_risk_level is not None:
            llm_risk_level = llm_risk_level.strip().lower()

        decision = rule.decision
        if decision is PolicyDecision.HITL_REQUIRED:
            requires_approval = True
        elif decision is PolicyDecision.DENY:
            requires_approval = False
        else:
            requires_approval = bool(rule.requires_approval)

        return {
            "action": action,
            "normalized_action": normalized,
            "risk_level": rule.risk_level,
            "decision": decision,
            "requires_approval": requires_approval,
            "executable": False,
            "allowed_action_class": rule.allowed_action_class,
            "permitted_roles": rule.permitted_roles,
            "actor": actor,
            "reason": rule.description or "policy matched",
            "policy_source": "registry",
        }
