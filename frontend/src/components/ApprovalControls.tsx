import { useState } from "react";
import { decideWorkflow } from "../api";
import { ErrorBanner } from "./common";

interface Props {
  workflow: { workflow_id: string; incident_id: string; action: string };
  onDecided: () => void;
}

/**
 * Approve / Reject. Rendered only when the SERVER says the caller may decide (`can_decide`). That flag is a hint: the
 * decision endpoint re-checks authentication, tenant, role, policy and self-approval, and any refusal (403/404/409 ...)
 * is shown here unchanged. The UI holds no authorization logic of its own.
 */
export function ApprovalControls({ workflow, onDecided }: Props) {
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await decideWorkflow(workflow, decision, rationale);
      onDecided();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="approval">
      <label>
        Rationale (optional)
        <input type="text" maxLength={500} value={rationale} onChange={(event) => setRationale(event.target.value)} />
      </label>
      <div className="row">
        <button type="button" className="primary" disabled={busy} onClick={() => submit("approve")}>
          Approve
        </button>
        <button type="button" className="danger" disabled={busy} onClick={() => submit("reject")}>
          Reject
        </button>
      </div>
      <p className="muted small">
        Approving records a human decision. PulseOps does not execute the action; the backend decides whether you are allowed.
      </p>
      <ErrorBanner error={error} />
    </div>
  );
}
