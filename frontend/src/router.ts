import { useEffect, useState } from "react";

// Hash routing: the server only ever serves /ui/ itself, so there is no history fallback to configure.
export type Route =
  | { view: "incidents" }
  | { view: "incident"; incidentId: string }
  | { view: "approvals" };

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, "");
  const detail = /^incidents\/([^/?#]+)$/.exec(path);
  if (detail) {
    try {
      return { view: "incident", incidentId: decodeURIComponent(detail[1]) };
    } catch {
      return { view: "incidents" };
    }
  }
  if (path === "approvals") return { view: "approvals" };
  return { view: "incidents" };
}

export function incidentHref(incidentId: string): string {
  return `#/incidents/${encodeURIComponent(incidentId)}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
