import { useCallback, useEffect, useState } from "react";
import { getMe, setToken, setUnauthorizedHandler } from "./api";
import { ErrorBanner } from "./components/common";
import { useRoute } from "./router";
import type { Me } from "./types";
import { ApprovalQueue } from "./views/ApprovalQueue";
import { IncidentDetail } from "./views/IncidentDetail";
import { IncidentList } from "./views/IncidentList";

function SignIn({ onSignedIn, notice }: { onSignedIn: (me: Me) => void; notice: string | null }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setToken(value);
    try {
      const me = await getMe();
      setValue("");
      onSignedIn(me);
    } catch (caught) {
      setToken(null);
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel signin" onSubmit={connect}>
      <h2>Connect to PulseOps</h2>
      <p className="muted">
        Paste an API bearer token. It is kept in this browser tab&apos;s memory only: it is never saved, and a reload signs you out.
        The tenant and your permissions come from the token, not from anything you choose here.
      </p>
      {notice && <p className="banner banner-warn">{notice}</p>}
      <label>
        Bearer token
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
      <button type="submit" className="primary" disabled={busy || value.trim() === ""}>
        Connect
      </button>
      <ErrorBanner error={error} />
    </form>
  );
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const route = useRoute();

  const signOut = useCallback(() => {
    setToken(null);
    setMe(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setMe(null);
      setNotice("The API rejected the token (401). Connect again with a valid token.");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  if (me === null) {
    return (
      <main>
        <h1>PulseOps</h1>
        <SignIn
          notice={notice}
          onSignedIn={(value) => {
            setNotice(null);
            setMe(value);
          }}
        />
      </main>
    );
  }

  return (
    <main>
      <header className="topbar">
        <h1>PulseOps</h1>
        <nav aria-label="Primary">
          <a href="#/incidents" aria-current={route.view !== "approvals" ? "page" : undefined}>
            Incidents
          </a>
          <a href="#/approvals" aria-current={route.view === "approvals" ? "page" : undefined}>
            Pending approvals
          </a>
        </nav>
        <div className="who">
          <span data-testid="who">
            {me.display_name || me.principal_id} · tenant {me.tenant_name ?? me.tenant_id} · {me.roles.join(", ") || "no roles"}
          </span>
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      {route.view === "incidents" && <IncidentList />}
      {route.view === "incident" && <IncidentDetail incidentId={route.incidentId} />}
      {route.view === "approvals" && <ApprovalQueue />}
    </main>
  );
}
