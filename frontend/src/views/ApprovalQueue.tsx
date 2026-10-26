import { useCallback, useEffect, useState } from "react";
import { listPendingApprovals } from "../api";
import { ApprovalControls } from "../components/ApprovalControls";
import { Badge, ErrorBanner, formatTime, Pagination } from "../components/common";
import { incidentHref } from "../router";
import type { WorkflowSummary } from "../types";

const PAGE_SIZE = 10;

export function ApprovalQueue() {
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<WorkflowSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    listPendingApprovals(PAGE_SIZE, offset)
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setError(null);
      })
      .catch((caught) => !cancelled && setError(caught))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [offset]);

  useEffect(() => load(), [load]);

  return (
    <section>
      <h2>Pending approvals</h2>
      <p className="muted">
        Workflows waiting for a human decision. Approve and Reject appear only where the backend reports you may decide, and the
        backend re-checks every decision.
      </p>
      <ErrorBanner error={error} />
      {loading && <p className="muted">Loading…</p>}
      {!loading && !error && items.length === 0 && <p className="muted">Nothing is waiting for approval.</p>}
      {items.map((item) => (
        <article className="panel" key={item.workflow_id} data-testid="approval-item">
          <h3>
            <a href={incidentHref(item.incident_id)}>{item.incident_id}</a>: {item.action}
          </h3>
          <p>
            Risk <Badge kind="risk" value={item.risk_level} /> · workflow status <strong>{item.status}</strong> · approval state{" "}
            <strong>awaiting decision</strong>
          </p>
          <p className="muted small">
            Workflow {item.workflow_id} · requested by {item.requested_by} · {formatTime(item.created_at)}
          </p>
          {item.investigation_summary ? (
            <div className="block">
              <span className="ai-label">AI-generated</span> investigation summary
              {item.investigation_confidence !== null && <> (confidence {Math.round(item.investigation_confidence * 100)}%)</>}:
              <p>{item.investigation_summary}</p>
            </div>
          ) : (
            <p className="muted">No grounded investigation is stored for this workflow.</p>
          )}
          {item.can_decide ? (
            <ApprovalControls workflow={item} onDecided={load} />
          ) : (
            <p className="muted" data-testid="cannot-decide">
              You cannot decide this workflow{item.decision_blocked_reason ? `: ${item.decision_blocked_reason}` : "."}
            </p>
          )}
        </article>
      ))}
      <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
    </section>
  );
}
