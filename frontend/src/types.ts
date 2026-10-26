// Wire types of the PulseOps API (see docs/phase-9.md). Everything under Investigation* is AI-generated, untrusted text.

export interface Me {
  principal_id: string;
  user_id: string;
  display_name: string;
  principal_type: string;
  is_human: boolean;
  tenant_id: string;
  tenant_name: string | null;
  roles: string[];
  permissions: string[];
  auth_method: string;
}

export interface IncidentListItem {
  incident_id: string;
  service_id: string;
  severity: string;
  status: string;
  title: string;
  environment: string;
  started_at: string;
}

export interface Incident extends IncidentListItem {
  description: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvestigationRecord {
  investigation_id: string;
  tenant_id: string;
  incident_id: string;
  workflow_id: string;
  service_id: string;
  summary: string;
  evidence: string[];
  hypotheses: string[];
  missing_information: string[];
  recommendations: string[];
  confidence: number;
  tool_calls: string[];
  source: string;
  created_at: string;
}

export interface Workflow {
  workflow_id: string;
  incident_id: string;
  action: string;
  requested_by: string;
  risk_level: string;
  requires_approval: boolean;
  status: string;
  policy_decision: string | null;
  policy_reason: string | null;
  investigation_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowSummary {
  workflow_id: string;
  incident_id: string;
  action: string;
  requested_by: string;
  risk_level: string;
  requires_approval: boolean;
  status: string;
  policy_decision: string | null;
  decision: string | null;
  reviewer: string | null;
  investigation_id: string | null;
  investigation_summary: string | null;
  investigation_confidence: number | null;
  can_decide: boolean;
  decision_blocked_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowList {
  items: WorkflowSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditEntry {
  audit_id: string | null;
  event_type: string;
  description: string;
  actor: string | null;
  actor_type: string | null;
  timestamp: string;
}

export type InvestigationStatus = "completed" | "degraded" | "failed" | "pending" | "unavailable";

export interface HitlState {
  required: boolean;
  state: "not_required" | "awaiting_decision" | "approved" | "rejected";
  decision: string | null;
  reviewer: string | null;
  can_decide: boolean;
  decision_blocked_reason: string | null;
}

export interface IncidentDetail {
  incident: Incident;
  workflow: Workflow | null;
  investigation_status: InvestigationStatus;
  investigation: InvestigationRecord | null;
  hitl: HitlState;
  audit_timeline: AuditEntry[];
}

export interface IncidentQuery {
  status?: string;
  severity?: string;
  service_id?: string;
  sort: string;
  order: "asc" | "desc";
  limit: number;
  offset: number;
}
