from __future__ import annotations

import json
import logging
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from pydantic import BaseModel, Field, ValidationError

from app.agent.prompts import INVESTIGATION_PROMPT_VERSION, render_system_prompt, render_user_prompt
from app.core.config import get_settings
from app.database import absolute_sqlite_url
from app.retrieval.models import IncidentRetrievalResult

# The can_use_tool callback below intentionally only gates tools *outside* allowed_tools.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

logger = logging.getLogger("pulseops.agent.investigation")

MCP_SERVER_NAME = "pulseops"
INCIDENT_CONTEXT_TOOL = "mcp__pulseops__get_incident_context"
# SDK-internal tool used to deliver the JSON-schema structured output. It performs no action.
SDK_INTERNAL_TOOL_NAMES = frozenset({"StructuredOutput"})
_MAX_FAILURE_DETAIL = 300


class IdentityContext(BaseModel):
    """Placeholder identity context for future authorization and memory integration."""

    tenant_id: str | None = None
    user_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    incident_id: str
    service_id: str = "unknown"
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_calls: list[str] = Field(default_factory=list)


class InvestigationPolicyError(RuntimeError):
    """Raised when the agent attempted a tool outside the approved PulseOps allowlist (fail closed)."""


class ToolAudit(BaseModel):
    """What the SDK message stream shows actually happened, independent of what the model claims."""

    tool_calls: list[str] = Field(default_factory=list)
    tool_failures: list[str] = Field(default_factory=list)
    unauthorized_tool_attempts: list[str] = Field(default_factory=list)
    context_attempted: bool = False
    context_retrieved: bool = False
    context_evidence: list[str] = Field(default_factory=list)
    incident_not_found: bool = False
    mcp_unavailable: bool = False


class InvestigationTelemetry(BaseModel):
    """Lightweight investigation observability record. Never contains credentials or prompt contents."""

    incident_id: str
    prompt_version: str = INVESTIGATION_PROMPT_VERSION
    model: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    tool_calls: list[str] = Field(default_factory=list)
    tool_failures: list[str] = Field(default_factory=list)
    unauthorized_tool_attempts: list[str] = Field(default_factory=list)
    grounded: bool = False
    confidence: float | None = None
    success: bool = False
    error: str | None = None
    # Gate 9: recorded only when the Claude Agent SDK exposes them (no budgets, no enforcement)
    total_cost_usd: float | None = None
    usage: dict[str, int] | None = None
    api_duration_ms: int | None = None


class IncidentInvestigationAgent:
    """Application-facing incident investigation agent using the Claude Agent SDK and MCP tool boundary."""

    MCP_TOOL_NAMES = [
        "mcp__pulseops__get_incident_context",
        "mcp__pulseops__get_related_incidents",
        "mcp__pulseops__get_service_repository",
        "mcp__pulseops__get_service_dependencies",
    ]
    DISALLOWED_TOOL_NAMES = [
        "Bash",
        "Edit",
        "Write",
        "Read",
        "Grep",
        "Glob",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "Task",
        "Agent",
    ]

    def __init__(
        self,
        database_url: str | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        max_turns: int | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        settings = get_settings()
        self.database_url = database_url or settings.database_url
        self.model = model or settings.claude_model
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.max_turns = max_turns if max_turns is not None else settings.claude_max_turns
        self.project_root = Path(__file__).resolve().parents[2]
        self.client_factory = client_factory or ClaudeSDKClient
        self.last_telemetry: InvestigationTelemetry | None = None

    async def investigate(
        self,
        incident_id: str,
        objective: str | None = None,
        identity_context: IdentityContext | None = None,
    ) -> InvestigationResult:
        return await self._investigate_async(incident_id, objective=objective, identity_context=identity_context)

    async def _investigate_async(
        self,
        incident_id: str,
        *,
        objective: str | None = None,
        identity_context: IdentityContext | None = None,
    ) -> InvestigationResult:
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required to run a live Claude SDK investigation. "
                "Set the environment variable or pass api_key to IncidentInvestigationAgent."
            )

        telemetry = InvestigationTelemetry(
            incident_id=incident_id, model=self.model, started_at=datetime.now(timezone.utc)
        )
        started = time.perf_counter()
        try:
            identity = identity_context or IdentityContext()
            prompt = self._build_prompt(incident_id, objective, identity)
            options = self._build_sdk_options(incident_id, objective, identity)

            try:
                async with self.client_factory(options) as client:
                    await client.query(prompt)
                    messages = [msg async for msg in client.receive_response()]
            except Exception as exc:  # pragma: no cover - exercised via real SDK integration tests
                raise RuntimeError(f"Claude SDK investigation failed for {incident_id}: {exc}") from exc

            self._record_ai_execution(telemetry, messages)
            audit = self._audit_messages(messages)
            telemetry.tool_calls = audit.tool_calls
            telemetry.tool_failures = audit.tool_failures
            telemetry.unauthorized_tool_attempts = audit.unauthorized_tool_attempts
            telemetry.grounded = audit.context_retrieved

            result = self._result_from_messages(incident_id, messages, audit=audit)
            telemetry.confidence = result.confidence
            telemetry.success = True
            return result
        except Exception as exc:
            telemetry.error = f"{type(exc).__name__}: {str(exc)[:_MAX_FAILURE_DETAIL]}"
            raise
        finally:
            telemetry.ended_at = datetime.now(timezone.utc)
            telemetry.duration_ms = int((time.perf_counter() - started) * 1000)
            self.last_telemetry = telemetry
            logger.info("investigation %s", telemetry.model_dump_json())

    @staticmethod
    def _record_ai_execution(telemetry: InvestigationTelemetry, messages: list[Any]) -> None:
        """Copy duration, token usage and total cost from the SDK result message when available (never raises)."""
        result_message = next((m for m in reversed(messages) if isinstance(m, ResultMessage)), None)
        if result_message is None:
            return
        try:
            cost = getattr(result_message, "total_cost_usd", None)
            telemetry.total_cost_usd = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
            api_ms = getattr(result_message, "duration_api_ms", None)
            telemetry.api_duration_ms = int(api_ms) if isinstance(api_ms, (int, float)) and not isinstance(api_ms, bool) else None
            usage = getattr(result_message, "usage", None)
            if isinstance(usage, dict):
                numeric = {str(k): int(v) for k, v in usage.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                telemetry.usage = numeric or None
        except (TypeError, ValueError):  # metadata is best-effort and must never break an investigation
            return

    @staticmethod
    def _structured_output_schema() -> dict[str, Any]:
        return {
            "type": "json_schema",
            "schema": InvestigationResult.model_json_schema(),
        }

    @classmethod
    async def _can_use_tool(cls, tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
        """Runtime allowlist gate for any tool that is not auto-approved via allowed_tools."""
        if tool_name in cls.MCP_TOOL_NAMES or tool_name in SDK_INTERNAL_TOOL_NAMES:
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=f"Tool '{tool_name}' is not permitted. PulseOps investigations are read-only "
            "and limited to approved PulseOps MCP retrieval tools.",
        )

    def _build_sdk_options(
        self,
        incident_id: str,
        objective: str | None,
        identity_context: IdentityContext | None = None,
    ) -> ClaudeAgentOptions:
        identity = identity_context or IdentityContext()
        if not identity.tenant_id or not identity.tenant_id.strip():
            # The tenant comes from the authenticated principal. The agent can never pick one, and without one the
            # MCP server would not start, so fail closed here with a clear reason.
            raise RuntimeError("An authenticated tenant context is required to run an investigation")
        mcp_server_config = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "app.mcp.server"],
            "env": {
                "PYTHONPATH": str(self.project_root),
                # Same database as the application, as an absolute URL so the subprocess working directory
                # cannot change which file is read.
                "PULSEOPS_DATABASE_URL": absolute_sqlite_url(self.database_url),
                "PULSEOPS_INCIDENT_ID": incident_id,
                "PULSEOPS_TENANT_ID": identity.tenant_id or "",
                "PULSEOPS_USER_ID": identity.user_id or "",
            },
        }

        return ClaudeAgentOptions(
            model=self.model,
            max_turns=self.max_turns,
            tools=[],
            allowed_tools=list(self.MCP_TOOL_NAMES),
            disallowed_tools=list(self.DISALLOWED_TOOL_NAMES),
            can_use_tool=self._can_use_tool,
            mcp_servers={MCP_SERVER_NAME: mcp_server_config},
            system_prompt=self._system_prompt(incident_id, objective, identity),
            output_format=self._structured_output_schema(),
        )

    @staticmethod
    def _identity_text(identity_context: IdentityContext) -> str:
        if not (identity_context.tenant_id or identity_context.user_id):
            return ""
        return (
            f"Tenant={identity_context.tenant_id or 'unknown'}; "
            f"User={identity_context.user_id or 'unknown'}; Roles={identity_context.roles}."
        )

    @staticmethod
    def _system_prompt(
        incident_id: str,
        objective: str | None,
        identity_context: IdentityContext,
    ) -> str:
        return render_system_prompt(
            incident_id, objective, IncidentInvestigationAgent._identity_text(identity_context)
        )

    @staticmethod
    def _build_prompt(
        incident_id: str,
        objective: str | None,
        identity_context: IdentityContext,
    ) -> str:
        return render_user_prompt(
            incident_id, objective, IncidentInvestigationAgent._identity_text(identity_context)
        )

    @staticmethod
    def _parse_agent_payload(raw_text: str | None) -> dict[str, Any]:
        if raw_text is None or not str(raw_text).strip():
            raise ValueError("Claude returned no final response payload.")
        text = str(raw_text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Claude returned malformed JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Claude final response is not a JSON object.")
        return payload

    @staticmethod
    def _tool_result_content(block: ToolResultBlock) -> str:
        content = block.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(getattr(item, "text", item)))
            return "\n".join(part for part in parts if part)
        return ""

    @classmethod
    def _context_evidence(cls, block: ToolResultBlock, expected_incident_id: str | None) -> list[str]:
        try:
            payload = json.loads(cls._tool_result_content(block))
            if not isinstance(payload, dict):
                return []
            context = IncidentRetrievalResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            return []

        if (
            not expected_incident_id
            or context.incident_id.casefold() != expected_incident_id.strip().casefold()
            or not context.service_id.strip()
        ):
            return []

        evidence: list[str] = []
        context_items = context.context.get("evidence", [])
        if isinstance(context_items, list):
            for item in context_items:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue
                source_type = str(item.get("source_type") or "context").strip()
                source_id = str(item.get("source_id") or "").strip()
                source = f"{source_type} ({source_id})" if source_id else source_type
                evidence.append(f"{source}: {content.strip()}")

        if not evidence:
            if context.title.strip():
                evidence.append(f"Incident title: {context.title.strip()}")
            evidence.extend(f"Log: {item.strip()}" for item in context.logs if item.strip())
            evidence.extend(f"Metric: {item.strip()}" for item in context.metrics if item.strip())
            evidence.extend(f"Deployment: {item.strip()}" for item in context.deployment_ids if item.strip())
            if context.repository_id and context.repository_id.strip():
                evidence.append(f"Repository mapping: {context.repository_id.strip()}")

        return cls._merge_unique(evidence)

    @classmethod
    def _tool_result_text(cls, block: ToolResultBlock) -> str:
        text = " ".join(cls._tool_result_content(block).split())
        return text[:_MAX_FAILURE_DETAIL] or "no error detail returned"

    @classmethod
    def _audit_messages(cls, messages: list[Any]) -> ToolAudit:
        """Derive tool usage and failures solely from SDK events (ToolUseBlock / ToolResultBlock / init)."""
        audit = ToolAudit()
        tool_names_by_id: dict[str, str] = {}
        tool_inputs_by_id: dict[str, dict[str, Any]] = {}
        context_call_ids: set[str] = set()
        context_result_ids: set[str] = set()
        successful_context_ids: set[str] = set()

        for message in messages:
            if isinstance(message, SystemMessage) and message.subtype == "init":
                for server in (message.data or {}).get("mcp_servers") or []:
                    if isinstance(server, dict) and server.get("name") == MCP_SERVER_NAME:
                        status = str(server.get("status", "unknown"))
                        if status != "connected":
                            audit.mcp_unavailable = True
                            audit.tool_failures.append(
                                f"PulseOps MCP server was unavailable (status={status})."
                            )

            for block in getattr(message, "content", None) or []:
                if isinstance(block, ToolUseBlock):
                    tool_names_by_id[block.id] = block.name
                    tool_inputs_by_id[block.id] = block.input if isinstance(block.input, dict) else {}
                    if block.name in cls.MCP_TOOL_NAMES:
                        if block.name not in audit.tool_calls:
                            audit.tool_calls.append(block.name)
                        if block.name == INCIDENT_CONTEXT_TOOL:
                            audit.context_attempted = True
                            context_call_ids.add(block.id)
                    elif block.name not in SDK_INTERNAL_TOOL_NAMES:
                        if block.name not in audit.unauthorized_tool_attempts:
                            audit.unauthorized_tool_attempts.append(block.name)
                elif isinstance(block, ToolResultBlock):
                    name = tool_names_by_id.get(block.tool_use_id, "unknown tool")
                    if name in SDK_INTERNAL_TOOL_NAMES:
                        # e.g. a structured-output attempt the SDK asked the model to retry; not retrieval.
                        continue
                    if name == INCIDENT_CONTEXT_TOOL:
                        context_result_ids.add(block.tool_use_id)

                    if block.is_error:
                        detail = cls._tool_result_text(block)
                        audit.tool_failures.append(f"{name} failed: {detail}")
                        if name == INCIDENT_CONTEXT_TOOL and "not found" in detail.lower():
                            audit.incident_not_found = True
                    elif name == INCIDENT_CONTEXT_TOOL:
                        expected_incident_id = tool_inputs_by_id.get(block.tool_use_id, {}).get("incident_id")
                        evidence = cls._context_evidence(block, expected_incident_id)
                        if evidence:
                            successful_context_ids.add(block.tool_use_id)
                            audit.context_evidence = cls._merge_unique(audit.context_evidence, evidence)
                        else:
                            audit.tool_failures.append(
                                f"{name} returned no usable incident evidence."
                            )

            if isinstance(message, ResultMessage):
                for denial in message.permission_denials or []:
                    name = denial.get("tool_name") if isinstance(denial, dict) else None
                    if name and name not in cls.MCP_TOOL_NAMES and name not in audit.unauthorized_tool_attempts:
                        audit.unauthorized_tool_attempts.append(str(name))

        for call_id in context_call_ids - context_result_ids:
            audit.tool_failures.append(f"{INCIDENT_CONTEXT_TOOL} returned no matching tool result.")

        audit.context_retrieved = bool(successful_context_ids) and not audit.mcp_unavailable
        return audit

    @classmethod
    def _extract_tool_calls(cls, messages: list[Any]) -> list[str]:
        """Approved tool calls actually observed as SDK ToolUseBlock events (never taken from model text)."""
        return cls._audit_messages(messages).tool_calls

    @staticmethod
    def _extract_final_payload(messages: list[Any]) -> dict[str, Any]:
        for message in reversed(messages):
            if isinstance(message, ResultMessage):
                if isinstance(message.structured_output, dict):
                    return message.structured_output
                if isinstance(message.structured_output, list):
                    if message.structured_output and isinstance(message.structured_output[0], dict):
                        return message.structured_output[0]
                if message.result:
                    return IncidentInvestigationAgent._parse_agent_payload(message.result)
            if isinstance(message, AssistantMessage):
                for block in reversed(getattr(message, "content", [])):
                    if isinstance(block, TextBlock) and block.text.strip():
                        try:
                            return IncidentInvestigationAgent._parse_agent_payload(block.text)
                        except ValueError:
                            continue
        raise ValueError("Claude did not provide a valid structured final response.")

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if item is not None and str(item).strip()]

    @staticmethod
    def _merge_unique(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for item in group:
                if item not in merged:
                    merged.append(item)
        return merged

    def _ungrounded_result(
        self, incident_id: str, payload: dict[str, Any], audit: ToolAudit
    ) -> InvestigationResult:
        """Safe degradation: without retrieved incident context nothing the model says is kept.

        ``payload`` (the model's output) is accepted for call-site compatibility but is deliberately ignored: model
        evidence, hypotheses, confidence, recommendations and missing_information are all discarded.
        """
        if audit.incident_not_found:
            reason = f"Incident {incident_id} could not be retrieved: it was not found in PulseOps."
            required = [
                f"Verify that incident identifier {incident_id} is correct and that the incident exists in PulseOps.",
                "Provide the affected service, logs, metrics and deployment records for the incident so it can be investigated.",
            ]
        elif audit.mcp_unavailable or audit.tool_failures:
            reason = f"Incident context for {incident_id} could not be retrieved because PulseOps retrieval tools failed."
            required = [
                "Restore access to the PulseOps retrieval tools and re-run the investigation.",
                f"Incident context (service, logs, metrics, deployments) for {incident_id} is required before any conclusion can be drawn.",
            ]
        else:
            reason = f"Incident context for {incident_id} was not retrieved during the investigation."
            required = [
                f"Re-run the investigation so that incident context for {incident_id} is retrieved through PulseOps tools.",
            ]

        return InvestigationResult(
            incident_id=incident_id,
            service_id="unknown",
            summary=f"{reason} No evidence-based conclusion is possible.",
            evidence=[],
            hypotheses=[],
            # Gate 8: nothing the model said survives an ungrounded result. Only system-authored reasons,
            # recorded tool failures and required next steps remain.
            missing_information=self._merge_unique([reason], audit.tool_failures),
            recommendations=self._merge_unique(required),
            confidence=0.0,
            tool_calls=audit.tool_calls,
        )

    def _result_from_messages(
        self, incident_id: str, messages: list[Any], audit: ToolAudit | None = None
    ) -> InvestigationResult:
        audit = audit or self._audit_messages(messages)

        if audit.unauthorized_tool_attempts:
            raise InvestigationPolicyError(
                "Investigation attempted unapproved tools and was rejected (fail closed): "
                + ", ".join(audit.unauthorized_tool_attempts)
            )

        retrieval_failed = bool(audit.tool_failures) or audit.mcp_unavailable
        try:
            payload = self._extract_final_payload(messages)
        except ValueError:
            if audit.context_retrieved or not (audit.context_attempted or retrieval_failed):
                raise
            return self._ungrounded_result(incident_id, {}, audit)

        if not isinstance(payload, dict):
            raise ValueError("Claude final response is not a structured dictionary.")

        if not audit.context_retrieved:
            return self._ungrounded_result(incident_id, payload, audit)

        return self._validate_payload(incident_id, payload, audit)

    def _validate_payload(self, incident_id: str, payload: dict[str, Any], audit: ToolAudit) -> InvestigationResult:
        payload_incident_id = str(payload.get("incident_id") or incident_id).strip()
        if not payload_incident_id:
            raise ValueError("Claude final structured output is missing incident_id.")
        if payload_incident_id.upper() != incident_id.strip().upper():
            raise ValueError(
                f"Claude final structured output refers to incident {payload_incident_id!r}, expected {incident_id!r}."
            )
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise ValueError("Claude final structured output is missing a valid summary.")

        has_evidence = bool(audit.context_evidence)
        has_hypotheses = isinstance(payload.get("hypotheses"), list) and bool(payload.get("hypotheses"))
        has_recommendations = isinstance(payload.get("recommendations"), list) and bool(payload.get("recommendations"))
        if not (has_evidence or has_hypotheses or has_recommendations):
            raise ValueError(
                "Claude final structured output is missing required investigation evidence, hypotheses, or recommendations."
            )

        try:
            result = InvestigationResult.model_validate({
                "incident_id": incident_id,
                "service_id": str(payload.get("service_id") or "unknown"),
                "summary": summary,
                "evidence": audit.context_evidence,
                "hypotheses": payload.get("hypotheses") or [],
                "missing_information": self._merge_unique(
                    self._string_list(payload.get("missing_information")), audit.tool_failures
                ),
                "recommendations": payload.get("recommendations") or [],
                "confidence": payload.get("confidence", 0.0),
                "tool_calls": audit.tool_calls,
            })
        except ValidationError as exc:
            raise ValueError(f"Claude final response failed validation: {exc}") from exc
        return result
