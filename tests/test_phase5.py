from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock

from tests.helpers import DEV_IDENTITY
from app.core.config import get_settings
from app.agent.service import IdentityContext, IncidentInvestigationAgent, InvestigationResult


class FakeTextBlock(TextBlock):
    pass


class FakeToolUseBlock(ToolUseBlock):
    def __init__(self, name: str, *, arguments: dict[str, object] | None = None) -> None:
        super().__init__(id=f"tool-{name}", name=name, input=arguments or {})


class FakeToolResultBlock(ToolResultBlock):
    def __init__(self, tool_use_id: str, content: str | list[dict[str, object]] | None = None) -> None:
        super().__init__(tool_use_id=tool_use_id, content=content, is_error=False)


def valid_context_result() -> FakeToolResultBlock:
    context_payload = {
        "incident_id": "INC-1007",
        "service_id": "svc-payment",
        "title": "Payment service degradation",
        "severity": "high",
        "status": "open",
        "context": {
            "evidence": [
                {
                    "source_type": "log",
                    "source_id": "log-test",
                    "content": "Database connection pool exhausted",
                }
            ]
        },
    }
    return FakeToolResultBlock(
        "tool-mcp__pulseops__get_incident_context",
        content=[{"text": json.dumps(context_payload)}],
    )


class FakeAssistantMessage(AssistantMessage):
    def __init__(self, text: str | None = None, *, blocks: list[object] | None = None) -> None:
        super().__init__(content=blocks or ([FakeTextBlock(text)] if text is not None else []), model="test-model")


class FakeResultMessage(ResultMessage):
    def __init__(self, result: str | None = None, *, structured_output: dict[str, object] | None = None) -> None:
        super().__init__(
            subtype="final",
            duration_ms=0,
            duration_api_ms=0,
            is_error=False,
            num_turns=1,
            session_id="test-session",
            result=result,
            structured_output=structured_output,
        )


class FakeSDKClient:
    def __init__(self, options: object) -> None:
        self.options = options
        self.prompt: str | None = None
        self.connected = False

    async def __aenter__(self) -> "FakeSDKClient":
        self.connected = True
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        return False

    async def connect(self, prompt: str | None = None) -> None:
        self.connected = True
        self.prompt = prompt

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompt = prompt

    async def receive_response(self):
        payload = {
            "incident_id": "INC-1007",
            "service_id": "svc-payment",
            "summary": "Payment service degradation detected.",
            "evidence": ["Database connection pool exhausted"],
            "hypotheses": ["The service is saturated while processing payments."],
            "missing_information": ["No dependency timeline was included."],
            "recommendations": ["Review recent dependency and deployment signals."],
            "confidence": 0.82,
        }
        yield FakeAssistantMessage(
            blocks=[
                FakeToolUseBlock("mcp__pulseops__get_incident_context", arguments={"incident_id": "INC-1007"}),
                FakeToolUseBlock("mcp__pulseops__get_service_dependencies", arguments={"service_id": "svc-payment"}),
                valid_context_result(),
                FakeTextBlock(json.dumps(payload)),
            ]
        )
        yield FakeResultMessage(result=json.dumps(payload), structured_output=payload)


def test_agent_builds_sdk_options_for_read_only_mcp_tools() -> None:
    identity = IdentityContext(tenant_id="tenant-a", user_id="u-42", roles=["analyst"], permissions=["read:incident"])
    agent = IncidentInvestigationAgent(
        database_url=get_settings().database_url,
        api_key="test-key",
        model="claude-sonnet-4-20250514",
        max_turns=6,
    )

    options = agent._build_sdk_options("INC-1007", "Investigate the payment issue.", identity)

    assert options.model == "claude-sonnet-4-20250514"
    assert options.max_turns == 6
    assert options.tools == []
    assert options.allowed_tools == [
        "mcp__pulseops__get_incident_context",
        "mcp__pulseops__get_related_incidents",
        "mcp__pulseops__get_service_repository",
        "mcp__pulseops__get_service_dependencies",
    ]
    assert options.output_format is not None
    assert options.output_format["type"] == "json_schema"
    assert options.output_format["schema"] == InvestigationResult.model_json_schema()
    assert options.output_format == {
        "type": "json_schema",
        "schema": InvestigationResult.model_json_schema(),
    }
    assert options.mcp_servers["pulseops"]["type"] == "stdio"
    command = options.mcp_servers["pulseops"]["command"]
    assert Path(command).name.lower().startswith("python")


def test_agent_investigate_uses_sdk_client_and_returns_validated_result() -> None:
    agent = IncidentInvestigationAgent(
        database_url=get_settings().database_url,
        api_key="test-key",
        client_factory=FakeSDKClient,
    )

    result = asyncio.run(agent.investigate("INC-1007", objective="Investigate event correlation.", identity_context=DEV_IDENTITY))

    assert result.incident_id == "INC-1007"
    assert result.service_id == "svc-payment"
    assert result.summary
    assert result.evidence
    assert result.hypotheses
    assert result.missing_information
    assert result.recommendations
    assert result.tool_calls
    assert "mcp__pulseops__get_incident_context" in result.tool_calls
    assert "mcp__pulseops__get_service_dependencies" in result.tool_calls


def test_agent_prefers_structured_output_over_textual_result() -> None:
    class StructuredOutputClient(FakeSDKClient):
        async def receive_response(self):
            payload = {
                "incident_id": "INC-1007",
                "service_id": "svc-payment",
                "summary": "Structured output preferred.",
                "evidence": ["tool output"],
                "hypotheses": ["debugging signal"],
                "missing_information": [],
                "recommendations": ["check dependencies"],
                "confidence": 0.71,
            }
            yield FakeAssistantMessage(
                blocks=[
                    FakeToolUseBlock("mcp__pulseops__get_incident_context", arguments={"incident_id": "INC-1007"}),
                    valid_context_result(),
                    FakeTextBlock("plain text unrelated to result"),
                ]
            )
            yield FakeResultMessage(result="not-json", structured_output=payload)

    agent = IncidentInvestigationAgent(
        database_url=get_settings().database_url,
        api_key="test-key",
        client_factory=StructuredOutputClient,
    )

    result = asyncio.run(agent.investigate("INC-1007", identity_context=DEV_IDENTITY))
    assert result.summary == "Structured output preferred."
    assert result.tool_calls == ["mcp__pulseops__get_incident_context"]


def test_agent_requires_api_key_for_live_sdk_investigation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = IncidentInvestigationAgent(database_url=get_settings().database_url, api_key=None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        asyncio.run(agent.investigate("INC-1007", identity_context=DEV_IDENTITY))


def test_agent_rejects_malformed_structured_output() -> None:
    class BadSDKClient(FakeSDKClient):
        async def receive_response(self):
            yield FakeAssistantMessage(
                blocks=[
                    FakeToolUseBlock("mcp__pulseops__get_incident_context", arguments={"incident_id": "INC-1007"}),
                    valid_context_result(),
                    FakeTextBlock("not-json"),
                ]
            )
            yield FakeResultMessage(
                result="not-json",
                structured_output={"incident_id": "INC-1007", "summary": "broken", "confidence": 2.0},
            )

    agent = IncidentInvestigationAgent(
        database_url=get_settings().database_url,
        api_key="test-key",
        client_factory=BadSDKClient,
    )

    with pytest.raises(ValueError, match="missing required investigation evidence|validation|malformed|valid structured"):
        asyncio.run(agent.investigate("INC-1007", identity_context=DEV_IDENTITY))
