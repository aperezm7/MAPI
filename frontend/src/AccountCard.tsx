import { FormEvent, useEffect, useState } from "react";
import {
  connectGbif,
  disconnectGbif,
  fetchAccount,
  fetchAccountQueries,
  fetchAccountStatus,
  getApiKey,
  setApiKey,
  type Account,
  type AccountStatus,
  type StoredQuery,
} from "./api";

export default function AccountCard() {
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [queries, setQueries] = useState<StoredQuery[]>([]);
  const [keyDraft, setKeyDraft] = useState(getApiKey);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const nextStatus = await fetchAccountStatus();
      setStatus(nextStatus);
      if (nextStatus.authRequired && !getApiKey()) {
        setAccount(null);
        setQueries([]);
        return;
      }
      const next = await fetchAccount();
      setAccount(next);
      setUsername(next.gbif.username || "");
      setEmail(next.gbif.email || "");
      setQueries(await fetchAccountQueries());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Account unavailable");
    }
  }

  useEffect(() => {
    void refresh();
    const onChange = () => void refresh();
    window.addEventListener("mapi-account", onChange);
    window.addEventListener("mapi-usage", onChange);
    return () => {
      window.removeEventListener("mapi-account", onChange);
      window.removeEventListener("mapi-usage", onChange);
    };
  }, []);

  function saveKey(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setApiKey(keyDraft);
  }

  async function onConnect(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const next = await connectGbif(username, password, email);
      setAccount(next);
      setPassword("");
      setMessage(`GBIF account ${next.gbif.username} connected. Downloads use it.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "GBIF login failed");
    }
  }

  async function onDisconnect() {
    setError(null);
    setMessage(null);
    try {
      setAccount(await disconnectGbif());
      setPassword("");
      setMessage("GBIF account removed from this client.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the GBIF account");
    }
  }

  const needsKey = Boolean(status?.authRequired && !getApiKey());
  const budget = account && !account.unlimited && account.budget != null
    ? `${account.spent} / ${account.budget} credits in ${account.month}`
    : account?.unlimited
      ? "Open access — no credit limit"
      : null;

  return (
    <section className="card">
      <h2>Account</h2>
      {status ? (
        <div className={needsKey ? "warn" : "ok"}>
          {needsKey
            ? "This server requires an API key."
            : account
              ? `${account.name}${account.keyPrefix ? ` · ${account.keyPrefix}…` : ""}`
              : "Checking the account…"}
        </div>
      ) : null}
      <form onSubmit={saveKey}>
        <label className="field">
          API key
          <input
            type="password"
            value={keyDraft}
            autoComplete="off"
            placeholder="mapi_…"
            onChange={(event) => setKeyDraft(event.target.value)}
          />
        </label>
        <button type="submit" className="secondary">
          {keyDraft.trim() ? "Use this key" : "Clear key"}
        </button>
      </form>
      {budget ? <div className="footer-attr">{budget}</div> : null}
      {account && !account.unlimited ? (
        <div className="footer-attr">
          {account.mapsPerDay ?? "∞"} maps/day · {account.plansPerDay ?? "∞"} plans/day ·{" "}
          {account.requestsPerMinute ?? "∞"}/min
          {status ? ` · map ${status.prices.map} cr, plan ${status.prices.plan} cr` : ""}
        </div>
      ) : null}
      {account && !account.unlimited ? (
        <form onSubmit={(event) => void onConnect(event)}>
          <label className="field">
            GBIF username
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" />
          </label>
          <label className="field">
            GBIF password
            <input
              type="password"
              value={password}
              placeholder={account.gbif.connected ? "Saved on the server" : ""}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="field">
            Notification email
            <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="off" />
          </label>
          <div className="actions">
            <button type="submit" className="secondary" disabled={!username || !password}>
              {account.gbif.connected ? "Update GBIF account" : "Connect GBIF account"}
            </button>
            {account.gbif.connected ? (
              <button type="button" className="linkish" onClick={() => void onDisconnect()}>
                Disconnect
              </button>
            ) : null}
          </div>
        </form>
      ) : (
        <div className="footer-attr">A client API key can store its own GBIF download login.</div>
      )}
      {queries.length > 0 ? (
        <details>
          <summary className="footer-attr">Recent queries ({queries.length})</summary>
          <ul className="candidates">
            {queries.slice(0, 8).map((item) => (
              <li key={item.id}>
                <span>
                  {item.kind} · {item.summary || "—"}
                  <small>
                    {item.cost ? `${item.cost} cr · ` : ""}
                    {item.status} · {item.createdAt.replace("T", " ").replace("Z", " UTC")}
                  </small>
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {message ? <div className="ok">{message}</div> : null}
      {error ? <div className="warn">{error}</div> : null}
    </section>
  );
}
