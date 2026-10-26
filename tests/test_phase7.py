from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import AGENT, DEV_TENANT, OPERATOR, REVIEWER
from app.services.policy_service import PolicyDecision, PolicyEngine, PolicyRule
from app.services.workflow_service import WorkflowService


def _tmp_db(tmp_path: Path) -> str:
    return "sqlite:" + (tmp_path / "workflow.db").as_posix()


def test_policy_engine_known_low_medium_and_high_actions() -> None:
    engine = PolicyEngine()

    low = engine.evaluate("notify")
    medium = engine.evaluate("page_oncall")
    high = engine.evaluate("deploy")

    assert low["risk_level"] == "low"
    assert low["decision"] == PolicyDecision.ALLOW
    assert medium["risk_level"] == "medium"
    assert medium["decision"] == PolicyDecision.NOTIFY
    assert high["risk_level"] == "high"
    assert high["decision"] == PolicyDecision.HITL_REQUIRED


def test_policy_engine_fail_closes_unknown_and_denied_actions() -> None:
    engine = PolicyEngine()

    unknown = engine.evaluate("mystery_action")
    denied = engine.evaluate("delete_data")

    assert unknown["decision"] == PolicyDecision.DENY
    assert unknown["risk_level"] == "high"
    assert denied["decision"] == PolicyDecision.DENY
    assert denied["requires_approval"] is False


def test_policy_engine_respects_policy_over_llm_risk() -> None:
    engine = PolicyEngine()

    result = engine.evaluate("notify", llm_risk_level="high")

    assert result["risk_level"] == "low"
    assert result["decision"] == PolicyDecision.ALLOW
    assert result["policy_source"] == "registry"


def test_policy_engine_validates_registry_configuration() -> None:
    invalid = PolicyRule(
        action="restart_service",
        risk_level="critical",
        decision=PolicyDecision.ALLOW,
        requires_approval=False,
        requires_human_approval=False,
        executable=True,
        allowed_action_class="executable",
        permitted_roles=["sre"],
    )

    engine = PolicyEngine(rules=[invalid])
    result = engine.evaluate("restart_service")

    assert result["decision"] == PolicyDecision.DENY
    assert result["risk_level"] == "high"
    assert result["reason"] == "invalid policy configuration"


def test_workflow_state_persists_across_service_recreation(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)
    created = service.evaluate_incident_action(
        incident_id="INC-1001",
        action="notify",
        requested_by="operator",
    )

    workflow_id = created["workflow_id"]
    reloaded = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT).get_workflow(workflow_id)

    assert reloaded is not None
    assert reloaded["workflow_id"] == workflow_id
    assert reloaded["incident_id"] == "INC-1001"
    assert reloaded["action"] == "notify"
    assert reloaded["status"] == "pending"


def test_workflow_decision_and_audit_are_persisted(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)
    created = service.evaluate_incident_action(
        incident_id="INC-1002",
        action="deploy",
        requested_by="oncall",
    )

    decision = service.record_decision(
        created["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        rationale="Approved for controlled rollout.",
        incident_id="INC-1002",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    assert decision["status"] == "approved"
    assert decision["decision"] == "approve"
    assert decision["audit_events"]
    assert decision["audit_events"][-1]["event_type"] == "approval"


def test_unknown_workflow_returns_expected_error(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)

    try:
        service.record_decision("WF-UNKNOWN", decision="approve", reviewer="incident-manager")
        raise AssertionError("Expected KeyError")
    except KeyError:
        pass


def test_workflow_service_requires_approval_for_high_risk_action() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)

    result = service.evaluate_incident_action(
        incident_id="INC-1001",
        action="deploy",
        requested_by="oncall",
        details={"target": "svc-payments", "reason": "promote canary"},
    )

    assert result["risk_level"] == "high"
    assert result["requires_approval"] is True
    assert result["status"] == "pending"
    assert result["audit_events"]


def test_workflow_service_tracks_decision_state() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)

    result = service.evaluate_incident_action(
        incident_id="INC-1001",
        action="notify",
        requested_by="pagerduty",
    )
    workflow_id = result["workflow_id"]

    decision = service.record_decision(
        workflow_id,
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-1001",
        action="notify",
        timestamp="2026-01-01T00:00:00Z",
    )

    assert decision["status"] == "approved"
    assert decision["decision"] == "approve"
    assert decision["requires_approval"] is False
    assert decision["audit_events"][-1]["event_type"] == "approval"


def test_workflow_http_routes_evaluate_risk_and_approval() -> None:
    with TestClient(app, headers=OPERATOR) as client:
        response = client.post(
            "/workflow/evaluate",
            json={
                "incident_id": "INC-1001",
                "action": "restart_service",
                "requested_by": "engineer-oncall",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["risk_level"] == "high"
        assert payload["requires_approval"] is True
        assert payload["status"] == "pending"

        workflow_id = payload["workflow_id"]
        decision_response = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=REVIEWER,
            json={
            "decision": "reject",
            "action": "restart_service",
            "timestamp": "2026-01-01T00:00:00Z",
        },
        )

        assert decision_response.status_code == 200
        decision_payload = decision_response.json()
        assert decision_payload["status"] == "rejected"
        assert decision_payload["decision"] == "reject"


def test_high_risk_action_enters_approval_pending_state() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)

    result = service.evaluate_incident_action(
        incident_id="INC-2001",
        action="deploy",
        requested_by="oncall",
    )

    assert result["requires_approval"] is True
    assert result["status"] == "pending"
    assert result["decision"] is None


def test_high_risk_action_cannot_proceed_without_approval() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2002",
        action="restart_service",
        requested_by="sre",
    )

    assert workflow["status"] == "pending"
    assert workflow["requires_approval"] is True
    assert workflow["decision"] is None


def test_valid_approval_moves_workflow_past_pending() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2003",
        action="deploy",
        requested_by="oncall",
    )

    approved = service.record_decision(
        workflow["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-2003",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    assert approved["status"] == "approved"
    assert approved["decision"] == "approve"
    assert approved["reviewer"] == "incident-manager"


def test_rejection_blocks_progression_and_conflicting_reversal_fails_closed() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2004",
        action="deploy",
        requested_by="oncall",
    )

    rejected = service.record_decision(
        workflow["workflow_id"],
        decision="reject",
        reviewer="incident-manager",
        incident_id="INC-2004",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    assert rejected["status"] == "rejected"
    assert rejected["decision"] == "reject"

    with pytest.raises(ValueError, match="final|reject|approve"):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="incident-manager",
            incident_id="INC-2004",
            action="deploy",
            timestamp="2026-01-01T00:01:00Z",
        )


def test_deny_cannot_be_overridden() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2005",
        action="delete_data",
        requested_by="operator",
    )

    with pytest.raises(ValueError, match="deny|DENY|cannot"):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="platform-admin",
            incident_id="INC-2005",
            action="delete_data",
            timestamp="2026-01-01T00:00:00Z",
        )


def test_malformed_and_mismatched_approvals_fail_closed() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2006",
        action="deploy",
        requested_by="oncall",
    )

    with pytest.raises((ValueError, TypeError)):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="",
            incident_id="INC-2006",
            action="deploy",
            timestamp="2026-01-01T00:00:00Z",
        )

    with pytest.raises(ValueError):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="incident-manager",
            incident_id="INC-2006",
            action="restart_service",
            timestamp="2026-01-01T00:00:00Z",
        )

    with pytest.raises(ValueError):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="incident-manager",
            incident_id="INC-9999",
            action="deploy",
            timestamp="2026-01-01T00:00:00Z",
        )

    with pytest.raises(ValueError):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="incident-manager",
            incident_id="INC-2006",
            action="deploy",
            timestamp="",
        )


def test_ai_generated_recommendation_cannot_satisfy_hitl() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2007",
        action="deploy",
        requested_by="oncall",
    )

    with pytest.raises(ValueError, match="human|reviewer|AI|claude|agent"):
        service.record_decision(
            workflow["workflow_id"],
            decision="approve",
            reviewer="claude",
            incident_id="INC-2007",
            action="deploy",
            timestamp="2026-01-01T00:00:00Z",
        )


def test_missing_and_duplicate_decision_state_is_rejected() -> None:
    service = WorkflowService(tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-2008",
        action="deploy",
        requested_by="oncall",
    )

    first = service.record_decision(
        workflow["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-2008",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    assert first["status"] == "approved"

    duplicate = service.record_decision(
        workflow["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-2008",
        action="deploy",
        timestamp="2026-01-01T00:01:00Z",
    )

    assert duplicate["status"] == "approved"
    assert duplicate["decision"] == "approve"


def test_workflow_creation_is_idempotent_for_same_key(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)

    first = service.evaluate_incident_action(
        incident_id="INC-4001",
        action="deploy",
        requested_by="release-manager",
        idempotency_key="deploy-inc-4001-001",
    )
    second = service.evaluate_incident_action(
        incident_id="INC-4001",
        action="deploy",
        requested_by="release-manager",
        idempotency_key="deploy-inc-4001-001",
    )

    assert first["workflow_id"] == second["workflow_id"]
    assert len(service.repository.list_audit_events(first["workflow_id"])) >= 3


def test_conflicting_idempotency_key_reuse_fails_closed(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)

    service.evaluate_incident_action(
        incident_id="INC-4002",
        action="deploy",
        requested_by="release-manager",
        idempotency_key="deploy-inc-4002-dup",
        details={"target": "svc-a"},
    )

    with pytest.raises(ValueError, match="conflict|idempotency|different"):
        service.evaluate_incident_action(
            incident_id="INC-4002",
            action="deploy",
            requested_by="release-manager",
            idempotency_key="deploy-inc-4002-dup",
            details={"target": "svc-b"},
        )


def test_duplicate_approval_is_not_replayed_and_canonical_audit_lifecycle_exists(tmp_path: Path) -> None:
    service = WorkflowService(database_url=_tmp_db(tmp_path), tenant_id=DEV_TENANT)
    workflow = service.evaluate_incident_action(
        incident_id="INC-4003",
        action="deploy",
        requested_by="oncall",
        idempotency_key="deploy-inc-4003-001",
    )

    approved = service.record_decision(
        workflow["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-4003",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    duplicate = service.record_decision(
        workflow["workflow_id"],
        decision="approve",
        reviewer="incident-manager",
        incident_id="INC-4003",
        action="deploy",
        timestamp="2026-01-01T00:00:00Z",
    )

    event_types = [event["event_type"] for event in approved["audit_events"]]
    assert approved["status"] == "approved"
    assert duplicate["status"] == "approved"
    assert "WORKFLOW_CREATED" in event_types
    assert "POLICY_EVALUATED" in event_types
    assert "HITL_REQUESTED" in event_types
    assert "HITL_APPROVED" in event_types
    assert "WORKFLOW_COMPLETED" in event_types


def test_workflow_api_hardens_validation_and_http_contract() -> None:
    with TestClient(app, headers=OPERATOR) as client:
        created = client.post(
            "/incidents",
            json={
                "service_id": "svc-payment",
                "severity": "high",
                "title": "Gate 5 request validation",
                "description": "API safety test",
                "environment": "prod",
            },
        )
        assert created.status_code == 200
        incident_id = created.json()["incident_id"]
        valid_key = f"gate5-valid-{uuid.uuid4().hex[:8]}"
        dup_key = f"gate5-dup-{uuid.uuid4().hex[:8]}"

        valid = client.post(
            "/workflow/evaluate",
            json={
                "incident_id": incident_id,
                "action": "notify",
                "requested_by": "operator",
                "severity": "low",
                "idempotency_key": valid_key,
            },
        )
        assert valid.status_code == 200
        payload = valid.json()
        assert payload["incident_id"] == incident_id
        assert payload["action"] == "notify"
        assert payload["risk_level"] == "low"

        malformed = client.post(
            "/workflow/evaluate",
            json={"incident_id": "", "action": "deploy", "requested_by": "operator"},
        )
        assert malformed.status_code == 400
        assert "incident_id" in malformed.json()["detail"].lower()

        missing_incident = client.post(
            f"/incidents/{incident_id}-missing/workflow/evaluate",
            json={"action": "notify", "requested_by": "operator"},
        )
        assert missing_incident.status_code == 404

        invalid_action = client.post(
            "/workflow/evaluate",
            json={"incident_id": incident_id, "action": "  ", "requested_by": "operator"},
        )
        assert invalid_action.status_code == 400

        invalid_severity = client.post(
            "/workflow/evaluate",
            json={"incident_id": incident_id, "action": "notify", "requested_by": "operator", "severity": "urgent"},
        )
        assert invalid_severity.status_code == 422

        missing_workflow = client.get("/workflow/WF-DOES-NOT-EXIST")
        assert missing_workflow.status_code == 404

        duplicate_key = client.post(
            "/workflow/evaluate",
            json={
                "incident_id": incident_id,
                "action": "deploy",
                "requested_by": "release-manager",
                "idempotency_key": dup_key,
            },
        )
        assert duplicate_key.status_code == 200

        conflicting_key = client.post(
            "/workflow/evaluate",
            json={
                "incident_id": incident_id,
                "action": "deploy",
                "requested_by": "release-manager",
                "idempotency_key": dup_key,
                "details": {"target": "svc-other"},
            },
        )
        assert conflicting_key.status_code == 409

        workflow_id = duplicate_key.json()["workflow_id"]
        decision_ok = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=REVIEWER,
            json={
                "decision": "approve",
                "incident_id": incident_id,
                "action": "deploy",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert decision_ok.status_code == 200

        decision_conflict = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=REVIEWER,
            json={
                "decision": "reject",
                "incident_id": incident_id,
                "action": "deploy",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert decision_conflict.status_code == 409

        denied_workflow = client.post(
            "/workflow/evaluate",
            json={"incident_id": incident_id, "action": "delete_data", "requested_by": "operator"},
        )
        assert denied_workflow.status_code == 200
        denied_id = denied_workflow.json()["workflow_id"]
        denied_approval = client.post(
            f"/workflow/{denied_id}/decision",
            headers=REVIEWER,
            json={
                "decision": "approve",
                "incident_id": incident_id,
                "action": "delete_data",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert denied_approval.status_code == 409

        invalid_decision = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=REVIEWER,
            json={
                "decision": "maybe",
                "incident_id": incident_id,
                "action": "deploy",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert invalid_decision.status_code == 400

        # A supplied reviewer is never authoritative: an empty one cannot match the authenticated principal.
        missing_reviewer = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=REVIEWER,
            json={
                "decision": "approve",
                "reviewer": "",
                "incident_id": incident_id,
                "action": "deploy",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert missing_reviewer.status_code == 403

        ai_reviewer = client.post(
            f"/workflow/{workflow_id}/decision",
            headers=AGENT,
            json={
                "decision": "approve",
                "incident_id": incident_id,
                "action": "deploy",
                "timestamp": "2026-01-01T00:00:00Z",
            },
        )
        assert ai_reviewer.status_code == 403  # an agent principal can never approve
