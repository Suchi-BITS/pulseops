import { useEffect, useState } from "react";
import { listIncidents } from "../api";
import { Badge, ErrorBanner, formatTime, Pagination } from "../components/common";
import { incidentHref } from "../router";
import type { IncidentListItem, IncidentQuery } from "../types";

const PAGE_SIZE = 20;

export function IncidentList() {
  const [filters, setFilters] = useState({ status: "", severity: "", service_id: "" });
  const [sort, setSort] = useState<{ sort: string; order: "asc" | "desc" }>({ sort: "started_at", order: "desc" });
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<IncidentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const query: IncidentQuery = {
      ...sort,
      status: filters.status || undefined,
      severity: filters.severity || undefined,
      service_id: filters.service_id.trim() || undefined,
      limit: PAGE_SIZE,
      offset,
    };
    setLoading(true);
    listIncidents(query)
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
  }, [filters, sort, offset]);

  function changeFilter(name: keyof typeof filters, value: string) {
    setFilters((current) => ({ ...current, [name]: value }));
    setOffset(0);
  }

  return (
    <section>
      <h2>Incidents</h2>
      <div className="filters">
        <label>
          Status
          <select value={filters.status} onChange={(event) => changeFilter("status", event.target.value)}>
            <option value="">Any</option>
            {["open", "investigating", "mitigated", "resolved", "closed"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Severity
          <select value={filters.severity} onChange={(event) => changeFilter("severity", event.target.value)}>
            <option value="">Any</option>
            {["low", "medium", "high", "critical"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Service
          <input
            type="text"
            placeholder="e.g. svc-payment"
            value={filters.service_id}
            onChange={(event) => changeFilter("service_id", event.target.value)}
          />
        </label>
        <label>
          Sort by
          <select
            value={`${sort.sort}:${sort.order}`}
            onChange={(event) => {
              const [key, order] = event.target.value.split(":");
              setSort({ sort: key, order: order as "asc" | "desc" });
              setOffset(0);
            }}
          >
            <option value="started_at:desc">Newest first</option>
            <option value="started_at:asc">Oldest first</option>
            <option value="severity:desc">Severity (high to low)</option>
            <option value="severity:asc">Severity (low to high)</option>
            <option value="incident_id:asc">Incident ID</option>
          </select>
        </label>
      </div>
      <ErrorBanner error={error} />
      {loading && <p className="muted">Loading…</p>}
      {!loading && !error && items.length === 0 && <p className="muted">No incidents match.</p>}
      {items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Incident</th>
              <th>Title</th>
              <th>Service</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {items.map((incident) => (
              <tr key={incident.incident_id}>
                <td>
                  <a href={incidentHref(incident.incident_id)}>{incident.incident_id}</a>
                </td>
                <td>{incident.title}</td>
                <td>{incident.service_id}</td>
                <td>
                  <Badge kind="severity" value={incident.severity} />
                </td>
                <td>
                  <Badge kind="status" value={incident.status} />
                </td>
                <td>{formatTime(incident.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Pagination total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
    </section>
  );
}
