import { ApiError } from "../api";

/** Shows a backend error exactly as the backend reported it (message, code, request id). */
export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  return (
    <div className="banner banner-error" role="alert">
      <strong>{api ? `Error ${api.status || ""}`.trim() : "Error"}:</strong>{" "}
      <span data-testid="error-detail">{error instanceof Error ? error.message : "Unexpected error"}</span>
      {api && (
        <div className="muted small">
          code <code>{api.code}</code>
          {api.requestId && (
            <>
              {" "}
              · request <code>{api.requestId}</code>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function Badge({ kind, value }: { kind: string; value: string }) {
  return <span className={`badge badge-${kind}-${value.replace(/[^a-z0-9_-]/gi, "")}`}>{value}</span>;
}

export function Pagination(props: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  const { total, limit, offset, onChange } = props;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <div className="pagination">
      <button type="button" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Previous
      </button>
      <span data-testid="page-range">
        {from}–{to} of {total}
      </span>
      <button type="button" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Next
      </button>
    </div>
  );
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
