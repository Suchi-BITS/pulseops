import { vi } from "vitest";
import type { IncidentDetail, Me, WorkflowSummary } from "../types";

export const ME: Me = {
  principal_id: "rita",
  user_id: "rita",
  display_name: "Rita Reviewer",
  principal_type: "human",
  is_human: true,
  tenant_id: "tenant-a",
  tenant_name: "Tenant A",
  roles: ["reviewer", "sre"],
  permissions: ["incident:read", "workflow:approve"],
  auth_method: "api_key",
};

export const INCIDENT = {
  incident_id: "INC-1001",
  service_id: "svc-payment",
  severity: "high",
  status: "open",
  title: "Payment latency",
  description: "p99 latency above threshold",
  environment: "production",
  started_at: "2026-01-01T10:00:00Z",
  resolved_at: null,
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
};

export function detail(overrides: Partial<IncidentDetail> = {}): IncidentDetail {
  return {
    incident: INCIDENT,
    workflow: {
      workflow_id: "WF-1",
      incident_id: "INC-1001",
      action: "restart_service",
      requested_by: "svc-n8n",
      risk_level: "high",
      requires_approval: true,
      status: "pending",
      policy_decision: "hitl_required",
      policy_reason: null,
      investigation_id: "INV-1",
      created_at: "2026-01-01T10:00:00Z",
      updated_at: "2026-01-01T10:00:00Z",
    },
    investigation_status: "completed",
    investigation: {
      investigation_id: "INV-1",
      tenant_id: "tenant-a",
      incident_id: "INC-1001",
      workflow_id: "WF-1",
      service_id: "svc-payment",
      summary: "Connection pool exhaustion is likely.",
      evidence: ["Error rate rose at 10:02"],
      hypotheses: ["Pool size too small after deploy"],
      missing_information: ["No database metrics"],
      recommendations: ["consider restarting the service"],
      confidence: 0.72,
      tool_calls: ["mcp__pulseops__get_incident_context"],
      source: "workflow",
      created_at: "2026-01-01T10:05:00Z",
    },
    hitl: { required: true, state: "awaiting_decision", decision: null, reviewer: null, can_decide: true, decision_blocked_reason: null },
    audit_timeline: [
      { audit_id: "A1", event_type: "INCIDENT_RECEIVED", description: "Received", actor: "svc-n8n", actor_type: "service", timestamp: "2026-01-01T10:00:00Z" },
    ],
    ...overrides,
  };
}

export function queueItem(overrides: Partial<WorkflowSummary> = {}): WorkflowSummary {
  return {
    workflow_id: "WF-1",
    incident_id: "INC-1001",
    action: "restart_service",
    requested_by: "svc-n8n",
    risk_level: "high",
    requires_approval: true,
    status: "pending",
    policy_decision: "hitl_required",
    decision: null,
    reviewer: null,
    investigation_id: "INV-1",
    investigation_summary: "Connection pool exhaustion is likely.",
    investigation_confidence: 0.72,
    can_decide: true,
    decision_blocked_reason: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

type Handler = (url: URL, init: RequestInit) => { status?: number; body: unknown; headers?: Record<string, string> };

/** Replaces fetch with a router keyed by "METHOD /path". Returns the mock so tests can inspect the calls. */
export function mockApi(routes: Record<string, Handler | { status?: number; body: unknown; headers?: Record<string, string> }>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${(init.method ?? "GET").toUpperCase()} ${url.pathname}`;
    const route = routes[key];
    if (!route) return new Response(JSON.stringify({ detail: `no mock for ${key}`, code: "not_found", request_id: "req-mock" }), { status: 404 });
    const result = typeof route === "function" ? route(url, init) : route;
    return new Response(JSON.stringify(result.body), {
      status: result.status ?? 200,
      headers: { "Content-Type": "application/json", ...(result.headers ?? {}) },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

export function envelope(status: number, detail: string, code: string) {
  return { status, body: { detail, code, request_id: "req-abc12345" } };
}
