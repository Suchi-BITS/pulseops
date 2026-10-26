"""Replay/live execution of golden cases against the real PulseOps Incident Agent.

Replay: real agent code + scripted SDK messages + temporary eval database. No API key, deterministic.
Tool results marked ``real`` are produced by the real PulseOps MCP server over the eval database.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from app.agent.service import IdentityContext, IncidentInvestigationAgent, InvestigationResult
from app.core.config import DEV_TENANT_ID
from app.database import DatabaseManager
from app.mcp.server import build_mcp_server
from evals.contracts import GoldenCase

_TENANT = DEV_TENANT_ID  # evaluation databases hold exactly one tenant: the development tenant
_TS = "2026-09-29T09:30:00+00:00"
_IDENTITY = IdentityContext(tenant_id=DEV_TENANT_ID, user_id="eval-harness", roles=["operator"], permissions=["incident:read"])


@dataclass
class CaseRun:
    case: GoldenCase
    result: InvestigationResult | None = None
    exception: BaseException | None = None
    telemetry: Any = None
    corpus: str = ""  # concatenated successful tool outputs: the only retrieved ground truth
    notes: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)  # milliseconds; informational only

    @property
    def outcome(self) -> str:
        return "result" if self.exception is None else f"raised:{type(self.exception).__name__}"


def ensure_non_empty_tables(db: sqlite3.Connection) -> None:
    """DatabaseManager re-seeds ANY empty table on every start, which would leak production seed rows into a
    case that deliberately has none (and violate foreign keys). Keep each table non-empty with inert sentinel rows
    that are not linked to the incident under evaluation."""

    def empty(table: str) -> bool:
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (_TENANT,)).fetchone()[0] == 0

    if empty("incidents"):
        db.execute(
            "INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description, environment,"
            " started_at, resolved_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (_TENANT, "INC-EVAL-SENTINEL", "svc-payment", "low", "closed", "sentinel", "sentinel", "eval", _TS, None, _TS, _TS),
        )
    if empty("logs"):
        db.execute(
            "INSERT INTO logs (tenant_id, log_id, incident_id, service_id, timestamp, level, message, source, metadata)"
            " VALUES ('dev', 'log-eval-sentinel', NULL, 'svc-payment', ?, 'info', 'sentinel', 'eval', NULL)", (_TS,),
        )
    if empty("metrics"):
        db.execute(
            "INSERT INTO metrics (tenant_id, metric_id, incident_id, service_id, timestamp, metric_name, value, unit, source)"
            " VALUES ('dev', 'metric-eval-sentinel', NULL, 'svc-payment', ?, 'sentinel', 0, NULL, 'eval')", (_TS,),
        )
    if empty("deployments"):
        db.execute(
            "INSERT INTO services (tenant_id, service_id, service_name, owner_team, environment, repository_id, description,"
            " created_at) VALUES ('dev', 'svc-eval-sentinel', 'sentinel', 'eval', 'eval', NULL, NULL, ?)", (_TS,),
        )
        db.execute(
            "INSERT INTO deployments (tenant_id, deployment_id, service_id, version, commit_sha, environment, deployed_at,"
            " deployed_by, status) VALUES ('dev', 'deploy-eval-sentinel', 'svc-eval-sentinel', '0', NULL, 'eval', ?,"
            " 'eval', 'successful')", (_TS,),
        )


def build_eval_database(case: GoldenCase, directory: Path) -> str:
    """Create an isolated SQLite DB holding only this case's fixture (production seed rows removed)."""
    path = directory / f"{case.case_id}.db"
    url = "sqlite:" + path.as_posix()
    DatabaseManager(url)  # creates schema + the default service seed
    fixture = case.fixture
    with sqlite3.connect(path) as db:
        for table in ("logs", "metrics", "deployments", "incidents"):
            db.execute(f"DELETE FROM {table}")  # temp eval DB only
        if fixture.incident is not None:
            i = fixture.incident
            db.execute(
                "INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description, environment,"
                " started_at, resolved_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (_TENANT, i["incident_id"], i.get("service_id", "svc-payment"), i.get("severity", "high"),
                 i.get("status", "open"), i["title"], i.get("description", i["title"]),
                 i.get("environment", "production"), _TS, None, _TS, _TS),
            )
        for svc in fixture.services:
            db.execute(
                "INSERT INTO services (tenant_id, service_id, service_name, owner_team, environment, repository_id, description,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (_TENANT, svc["service_id"], svc.get("service_name", svc["service_id"]), "eval",
                 svc.get("environment", "production"), None, None, _TS),
            )
        for log in fixture.logs:
            db.execute(
                "INSERT INTO logs (tenant_id, log_id, incident_id, service_id, timestamp, level, message, source, metadata)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (_TENANT, log["log_id"], case.incident_id, "svc-payment", log.get("timestamp", _TS),
                 log.get("level", "error"), log["message"], "payment-service", None),
            )
        for m in fixture.metrics:
            db.execute(
                "INSERT INTO metrics (tenant_id, metric_id, incident_id, service_id, timestamp, metric_name, value, unit, source)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (_TENANT, m["metric_id"], case.incident_id, "svc-payment", m.get("timestamp", _TS), m["metric_name"],
                 m["value"], m.get("unit"), "synthetic-monitoring"),
            )
        for d in fixture.deployments:
            db.execute(
                "INSERT INTO deployments (tenant_id, deployment_id, service_id, version, commit_sha, environment, deployed_at,"
                " deployed_by, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (_TENANT, d["deployment_id"], "svc-payment", d["version"], d.get("commit_sha"), "production",
                 d.get("deployed_at", _TS), "release-bot", d.get("status", "successful")),
            )
        ensure_non_empty_tables(db)
    return url


async def _real_tool_text(database_url: str, tool: str, arguments: dict[str, Any]) -> str:
    server = build_mcp_server(database_url=database_url, tenant_id=_TENANT)
    result = await server.call_tool(tool.removeprefix("mcp__pulseops__"), arguments)
    if result.content:
        return result.content[0].text
    return json.dumps(result.structured_content)


async def build_messages(case: GoldenCase, database_url: str) -> tuple[list[Any], str]:
    script = case.script
    messages: list[Any] = [
        SystemMessage(subtype="init", data={"mcp_servers": [{"name": "pulseops", "status": script.mcp_status}]})
    ]
    corpus: list[str] = []
    for index, step in enumerate(script.steps, start=1):
        tool_id = f"t{index}"
        messages.append(
            AssistantMessage(content=[ToolUseBlock(id=tool_id, name=step.tool, input=step.arguments)], model="replay")
        )
        if step.result == "real":
            text = await _real_tool_text(database_url, step.tool, step.arguments)
            corpus.append(text)
            block = ToolResultBlock(tool_use_id=tool_id, content=text, is_error=False)
        elif step.result == "raw":
            corpus.append(step.text or "")
            block = ToolResultBlock(tool_use_id=tool_id, content=step.text or "", is_error=False)
        else:
            block = ToolResultBlock(tool_use_id=tool_id, content=step.text or "tool error", is_error=True)
        messages.append(UserMessage(content=[block]))
    final_text = script.final_text if script.final_text is not None else json.dumps(script.final_payload)
    messages.append(AssistantMessage(content=[TextBlock(text=final_text)], model="replay"))
    messages.append(
        ResultMessage(
            subtype="success", duration_ms=0, duration_api_ms=0, is_error=False, num_turns=len(script.steps) + 1,
            session_id="eval-replay", result=final_text, structured_output=script.final_payload,
        )
    )
    return messages, "\n".join(corpus)


def _scripted_client(messages: list[Any], sdk_error: str | None = None) -> type:
    class ScriptedSDKClient:
        def __init__(self, options: Any) -> None:
            self.options = options

        async def __aenter__(self) -> "ScriptedSDKClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self):
            if sdk_error is not None:
                raise RuntimeError(sdk_error)  # e.g. a model timeout surfacing from the SDK
            for message in messages:
                yield message

    return ScriptedSDKClient


async def run_replay_case(case: GoldenCase, directory: Path) -> CaseRun:
    database_url = build_eval_database(case, directory)
    messages, corpus = await build_messages(case, database_url)
    agent = IncidentInvestigationAgent(
        database_url=database_url, api_key="replay-no-key-needed", client_factory=_scripted_client(messages, case.script.sdk_error)
    )
    run = CaseRun(case=case, corpus=corpus)
    started = time.perf_counter()
    try:
        run.result = await agent.investigate(case.incident_id, case.objective, identity_context=_IDENTITY)
    except Exception as exc:  # the scorers decide whether failing closed was the expected behaviour
        run.exception = exc
    run.timings["investigation_ms"] = (time.perf_counter() - started) * 1000
    run.telemetry = agent.last_telemetry
    return run


RETRIEVAL_TOOLS = (
    ("mcp__pulseops__get_incident_context", lambda case: {"incident_id": case.incident_id}),
    ("mcp__pulseops__get_related_incidents", lambda case: {"service_id": "svc-payment"}),
    ("mcp__pulseops__get_service_repository", lambda case: {"service_id": "svc-payment"}),
    ("mcp__pulseops__get_service_dependencies", lambda case: {"service_id": "svc-payment"}),
)


async def run_live_case(
    case: GoldenCase,
    *,
    model: str | None,
    directory: Path,
    agent_factory: Callable[..., Any] | None = None,
) -> CaseRun:
    """Real agent, real Claude, over the case's own eval database.

    Gate 8: the application database is configurable and propagated to the MCP subprocess, so fixtures work live.
    The 'retrieved corpus' the grounding/fabrication scorers use is obtained independently by calling the same four
    real retrieval tools over the same database (not taken from the agent's own output).
    """
    database_url = build_eval_database(case, directory)
    factory = agent_factory or IncidentInvestigationAgent
    agent = factory(database_url=database_url, model=model) if model else factory(database_url=database_url)
    run = CaseRun(case=case)
    started = time.perf_counter()
    try:
        run.result = await agent.investigate(case.incident_id, case.objective, identity_context=_IDENTITY)
    except Exception as exc:
        run.exception = exc
    run.timings["investigation_ms"] = (time.perf_counter() - started) * 1000
    run.telemetry = getattr(agent, "last_telemetry", None)
    texts: list[str] = []
    for tool, arguments in RETRIEVAL_TOOLS:
        try:
            texts.append(await _real_tool_text(database_url, tool, arguments(case)))
        except Exception:  # e.g. unknown incident: the tool reports not-found; that is not corpus
            continue
    run.corpus = "\n".join(texts)
    return run


def live_all(
    cases: list[GoldenCase], *, model: str | None, agent_factory: Callable[..., Any] | None = None
) -> list[CaseRun]:
    async def go(directory: Path) -> list[CaseRun]:
        return [
            await run_live_case(case, model=model, directory=directory, agent_factory=agent_factory) for case in cases
        ]

    with tempfile.TemporaryDirectory(prefix="pulseops-eval-live-", ignore_cleanup_errors=True) as tmp:
        return asyncio.run(go(Path(tmp)))


def replay_all(cases: list[GoldenCase]) -> list[CaseRun]:
    async def go(directory: Path) -> list[CaseRun]:
        return [await run_replay_case(case, directory) for case in cases]

    with tempfile.TemporaryDirectory(prefix="pulseops-eval-", ignore_cleanup_errors=True) as tmp:
        return asyncio.run(go(Path(tmp)))
