import { useCallback, useEffect, useState } from "react";
import { getIncidentDetail } from "../api";
import { ApprovalControls } from "../components/ApprovalControls";
import { Badge, ErrorBanner, formatTime } from "../components/common";
import { InvestigationPanel } from "../components/InvestigationPanel";
import type { IncidentDetail as Detail } from "../types";

const HITL_TEXT: Record<Detail["hitl"]["state"], string> = {
  not_required: "No human approval is pending for this incident.",
  awaiting_decision: "Awaiting a human decision.",
  approved: "Approved by a human reviewer. PulseOps did not execute the action.",
  rejected: "Rejected by a human reviewer.",
};

export function IncidentDetail({ incidentId }: { incidentId: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    getIncidentDetail(incidentId)
      .then((value) => {
        if (cancelled) return;
        setDetail(value);
        setError(null);
      })
      .catch((caught) => {
        if (cancelled) return;
        setDetail(null);
        setError(caught);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  useEffect(() => load(), [load]);

  return (
    <section>
      <p>
        <a href="#/incidents">← Incidents</a>
      </p>
      <ErrorBanner error={error} />
      {loading && !detail && <p className="muted">Loading…</p>}
      {detail && (
        <>
          <div className="panel">
            <h2>
              {detail.incident.incident_id}: {detail.incident.title}
            </h2>
            <p>
              <Badge kind="severity" value={detail.incident.severity} /> <Badge kind="status" value={detail.incident.status} />{" "}
              <span className="muted">
                {detail.incident.service_id} · {detail.incident.environment} · started {formatTime(detail.incident.started_at)}
              </span>
            </p>
            <p>{detail.incident.description}</p>
          </div>

          <InvestigationPanel status={detail.investigation_status} investigation={detail.investigation} />

          <div className="panel">
            <h3>Workflow and approval</h3>
            {detail.workflow ? (
              <dl>
                <dt>Workflow</dt>
                <dd>{detail.workflow.workflow_id}</dd>
                <dt>Requested action</dt>
                <dd>
                  {detail.workflow.action} <span className="muted">(requested by {detail.workflow.requested_by})</span>
                </dd>
                <dt>Risk</dt>
                <dd>{detail.workflow.risk_level}</dd>
                <dt>Status</dt>
                <dd data-testid="workflow-status">{detail.workflow.status}</dd>
                <dt>Policy decision</dt>
                <dd>{detail.workflow.policy_decision ?? "—"}</dd>
              </dl>
            ) : (
              <p className="muted">No workflow has been created for this incident.</p>
            )}
            <p data-testid="hitl-state">
              <strong>Human approval:</strong> {HITL_TEXT[detail.hitl.state]}
              {detail.hitl.reviewer && <> Reviewer: {detail.hitl.reviewer}.</>}
            </p>
            {detail.workflow && detail.hitl.state === "awaiting_decision" &&
              (detail.hitl.can_decide ? (
                <ApprovalControls workflow={detail.workflow} onDecided={load} />
              ) : (
                <p className="muted" data-testid="cannot-decide">
                  You cannot decide this workflow{detail.hitl.decision_blocked_reason ? `: ${detail.hitl.decision_blocked_reason}` : "."}
                </p>
              ))}
          </div>

          <div className="panel">
            <h3>Audit timeline</h3>
            {detail.audit_timeline.length === 0 ? (
              <p className="muted">No audit events.</p>
            ) : (
              <ol className="timeline">
                {detail.audit_timeline.map((entry, index) => (
                  <li key={entry.audit_id ?? index}>
                    <span className="muted small">{formatTime(entry.timestamp)}</span> <code>{entry.event_type}</code>{" "}
                    {entry.description}
                    {entry.actor && <span className="muted"> — {entry.actor}</span>}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </>
      )}
    </section>
  );
}
