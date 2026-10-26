import type { IncidentDetail, IncidentListItem, IncidentQuery, Me, WorkflowList } from "./types";

// The bearer token lives in this module variable ONLY: never in localStorage, sessionStorage, cookies, IndexedDB,
// the URL or the bundle. A page reload forgets it, by design (P9 decision; SSO is a P10 topic).
let bearerToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setToken(token: string | null): void {
  bearerToken = token && token.trim() ? token.trim() : null;
}

export function hasToken(): boolean {
  return bearerToken !== null;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** A failed API call in the backend error envelope: {detail, code, request_id}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, detail: string, code: string, requestId: string | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<{ data: T; headers: Headers }> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (bearerToken) headers.set("Authorization", `Bearer ${bearerToken}`);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: "omit", cache: "no-store" });
  } catch {
    throw new ApiError(0, "The PulseOps API could not be reached.", "network_error", null);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    let code = `http_${response.status}`;
    let requestId = response.headers.get("X-Request-ID");
    try {
      const body = (await response.json()) as { detail?: unknown; code?: unknown; request_id?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      if (typeof body.code === "string") code = body.code;
      if (typeof body.request_id === "string") requestId = body.request_id;
    } catch {
      /* not an envelope: keep the generic message */
    }
    if (response.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(response.status, detail, code, requestId);
  }
  return { data: (await response.json()) as T, headers: response.headers };
}

export async function getMe(): Promise<Me> {
  return (await request<Me>("/me")).data;
}

export async function listIncidents(query: IncidentQuery): Promise<{ items: IncidentListItem[]; total: number }> {
  const params = new URLSearchParams({
    sort: query.sort,
    order: query.order,
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.status) params.set("status", query.status);
  if (query.severity) params.set("severity", query.severity);
  if (query.service_id) params.set("service_id", query.service_id);
  const { data, headers } = await request<IncidentListItem[]>(`/incidents?${params}`);
  const total = Number(headers.get("X-Total-Count"));
  return { items: data, total: Number.isFinite(total) ? total : data.length };
}

export async function getIncidentDetail(incidentId: string): Promise<IncidentDetail> {
  return (await request<IncidentDetail>(`/incidents/${encodeURIComponent(incidentId)}/detail`)).data;
}

export async function listPendingApprovals(limit: number, offset: number): Promise<WorkflowList> {
  const params = new URLSearchParams({
    status: "pending",
    requires_approval: "true",
    sort: "created_at",
    order: "asc",
    limit: String(limit),
    offset: String(offset),
  });
  return (await request<WorkflowList>(`/workflow?${params}`)).data;
}

/**
 * Sends the human decision. The server decides whether it is allowed (role, tenant, policy, no self-approval,
 * human principals only): any refusal arrives as an ApiError and is shown as is. The reviewer is never sent: the
 * backend uses the authenticated principal.
 */
export async function decideWorkflow(
  workflow: { workflow_id: string; incident_id: string; action: string },
  decision: "approve" | "reject",
  rationale: string,
): Promise<void> {
  await request(`/workflow/${encodeURIComponent(workflow.workflow_id)}/decision`, {
    method: "POST",
    body: JSON.stringify({
      decision,
      incident_id: workflow.incident_id,
      action: workflow.action,
      rationale: rationale.trim() || null,
      timestamp: new Date().toISOString(),
    }),
  });
}
