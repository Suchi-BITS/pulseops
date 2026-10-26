from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CONTEXT_TOOL = "mcp__pulseops__get_incident_context"

# Metric -> report section. Deliberately two sections, never collapsed into one overall score.
SYSTEM_METRICS = (
    "evidence_grounding",
    "retrieval_correctness",
    "tenant_isolation",
    "fabrication_detection",
    "tool_boundary",
    "policy_boundary",
    "failure_behavior",
    "injection_resistance",
    "field_separation",
)
QUALITY_METRICS = (
    "tool_selection",
    "evidence_recall",
    "relevance",
    "completeness",
    "hypothesis_quality",
)


class Fixture(BaseModel):
    """Rows loaded into a temporary evaluation database (never the production seed)."""

    incident: dict[str, Any] | None = None
    services: list[dict[str, Any]] = Field(default_factory=list)  # extra services (same eval DB)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    deployments: list[dict[str, Any]] = Field(default_factory=list)


class ToolStep(BaseModel):
    """One scripted tool call. ``real`` results come from the real PulseOps MCP server on the eval DB."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Literal["real", "error", "raw"] = "real"
    text: str | None = None  # error message (result=error) or raw tool output (result=raw)


class AgentScript(BaseModel):
    """What the scripted 'model' does. Used only by replay mode."""

    mcp_status: str = "connected"
    sdk_error: str | None = None  # the scripted SDK raises this (e.g. a model timeout) instead of returning messages
    steps: list[ToolStep] = Field(default_factory=list)
    final_payload: dict[str, Any] | None = None
    final_text: str | None = None


class PolicyProbe(BaseModel):
    requested_action: str | None = None
    expected_decision: str
    expect_investigation_failed: bool = False  # FAILED: investigation raised -> investigation_failed, never DENY
    expect_investigation_degraded: bool = False  # DEGRADED: ungrounded -> investigation_degraded, never DENY
    event_metadata: dict[str, Any] = Field(default_factory=dict)


class Expected(BaseModel):
    evidence_must_include: list[str] = Field(default_factory=list)  # case-insensitive substrings
    evidence_must_not_include: list[str] = Field(default_factory=list)
    acceptable_causes: list[list[str]] = Field(default_factory=list)  # rubric: each group = keywords (any-of)
    required_missing_info: list[str] = Field(default_factory=list)  # keyword that must appear in missing_information
    min_confidence: float | None = None
    max_confidence: float | None = None
    allowed_tools: list[str] | None = None  # None -> the agent's MCP allowlist
    # Tool selection: tools this incident legitimately needs, tools that are acceptable but not required, and
    # nothing else. None -> not evaluated. Calling every tool is never rewarded.
    expected_tools: list[str] | None = None
    optional_tools: list[str] = Field(default_factory=list)
    expect_failure: Literal["none", "degraded", "raises"] = "none"
    expected_exceptions: list[str] = Field(default_factory=list)
    # P8.3: causes the retrieved evidence does not support. Each group is a set of keywords (stem-matched); a summary,
    # hypothesis or recommendation containing ALL keywords of a group asserts that cause. It is a fabrication unless
    # the retrieved data itself contains all of them.
    unsupported_claims: list[list[str]] = Field(default_factory=list)
    # P8.3: rubric synonyms. A keyword in ``acceptable_causes`` also matches any listed alternative.
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    fabricated_strings: list[str] = Field(default_factory=list)  # model claims that must not leak into summary/evidence/hypotheses
    advisory_strings: list[str] = Field(default_factory=list)  # model recommendations: observed and reported, not failed
    expect_unauthorized_attempt: bool = False
    injection_markers: list[str] = Field(default_factory=list)  # hostile operational text


class GoldenCase(BaseModel):
    case_id: str
    category: str
    description: str
    expected_behavior: str = ""  # required (non-empty) for every case added after golden-v1
    incident_id: str
    objective: str | None = None
    fixture: Fixture = Field(default_factory=Fixture)
    script: AgentScript
    expected: Expected = Field(default_factory=Expected)
    policy_probes: list[PolicyProbe] = Field(default_factory=list)
    # Live mode uses the unmodified P6 MCP subprocess, which reads the configured DB, not the eval fixture.
    live_eligible: bool = False


class MetricScore(BaseModel):
    metric: str
    group: Literal["system", "quality"]
    applicable: bool = True
    score: float | None = None  # 0.0-1.0, None when not applicable
    passed: bool | None = None
    details: list[str] = Field(default_factory=list)


class CaseTelemetry(BaseModel):
    """P8.0: per-case observability. Informational only; ``None`` means unknown (never estimated or defaulted)."""

    latency_kind: Literal["harness_replay", "live_model_inclusive"]
    model: str | None = None
    investigation_ms: float | None = None  # wall clock of the investigation as run by the harness
    agent_duration_ms: int | None = None  # agent-recorded duration (live)
    api_duration_ms: int | None = None  # SDK API time, when the SDK provides it
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None  # input + output, only when both were reported
    usage: dict[str, int] | None = None  # raw numeric SDK usage
    total_cost_usd: float | None = None  # as reported by the SDK; never computed from pricing
    telemetry_available: bool = False


class TelemetryTotals(BaseModel):
    """P8.0: run-level totals. A total is ``None`` when no case reported the quantity (unknown, not zero)."""

    mode: str
    latency_kind: Literal["harness_replay", "live_model_inclusive"]
    model: str | None = None
    models_observed: list[str] = Field(default_factory=list)
    cases: int = 0
    cases_with_telemetry: int = 0
    cases_with_tokens: int = 0
    cases_with_cost: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None
    note: str = ""


class CaseScore(BaseModel):
    case_id: str
    category: str
    outcome: str  # "result" | "raised:<ExceptionType>"
    scores: list[MetricScore]
    timings_ms: dict[str, float] = Field(default_factory=dict)  # informational, never gated
    telemetry: CaseTelemetry | None = None  # P8.0, informational, never gated


class RetrievalCheckResult(BaseModel):
    check_id: str
    tool: str
    score: float
    passed: bool
    details: list[str] = Field(default_factory=list)


class TimingSummary(BaseModel):
    count: int
    mean_ms: float
    p50_ms: float
    max_ms: float


class MetricAggregate(BaseModel):
    metric: str
    applicable_cases: int
    mean_score: float | None
    pass_rate: float | None
    failed_cases: list[str] = Field(default_factory=list)


class RegressionFinding(BaseModel):
    metric: str
    baseline: float
    current: float | None
    tolerance: float
    message: str


class RegressionResult(BaseModel):
    baseline_version: int | None = None
    baseline_path: str | None = None
    compared: bool = False
    regressions: list[RegressionFinding] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.regressions)


class EvalReport(BaseModel):
    run_id: str
    timestamp: str
    mode: Literal["replay", "live"]
    status: Literal["COMPLETED", "SKIPPED"]
    banner: str
    live_model_quality_measured: bool
    model: str | None = None
    prompt_version: str | None = None
    dataset_version: str
    case_count: int
    skipped_reason: str | None = None
    notes: list[str] = Field(default_factory=list)
    dataset_sha256: str | None = None
    retrieval_dataset_sha256: str | None = None
    timings: dict[str, TimingSummary] = Field(default_factory=dict)  # informational, never gated
    telemetry: TelemetryTotals | None = None  # P8.0 run-level tokens/cost/latency kind, informational, never gated
    retrieval_checks: list[RetrievalCheckResult] = Field(default_factory=list)
    tenant_checks: list[RetrievalCheckResult] = Field(default_factory=list)  # P8.1 tenant-isolation checks
    cases: list[CaseScore] = Field(default_factory=list)
    system_correctness_safety: dict[str, MetricAggregate] = Field(default_factory=dict)
    ai_quality: dict[str, MetricAggregate] = Field(default_factory=dict)
    regression: RegressionResult | None = None
    passed: bool = True
