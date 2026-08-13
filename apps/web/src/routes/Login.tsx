import { useEffect, useState } from "react";
import { LOGIN_HINT_KEY } from "../hooks/useAuth";

type DevUser = { email: string; role: string };
type DevAuthInfo = { entra_configured: boolean; users: DevUser[] };
type DevAuthState =
  | { status: "loading" }
  | { status: "off" }
  | { status: "on"; info: DevAuthInfo };

const DEV_BUILD = import.meta.env.DEV;

function useDevAuth(): DevAuthState {
  const [state, setState] = useState<DevAuthState>(
    DEV_BUILD ? { status: "loading" } : { status: "off" },
  );

  useEffect(() => {
    if (!DEV_BUILD) return;
    fetch("/api/auth/dev/users", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((info: DevAuthInfo | null) =>
        setState(info ? { status: "on", info } : { status: "off" }),
      )
      .catch(() => setState({ status: "off" }));
  }, []);

  return state;
}

function DevLoginPanel({ info }: { info: DevAuthInfo }) {
  const [email, setEmail] = useState(info.users[0]?.email ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn() {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/dev/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        setError(
          res.status === 403
            ? `${email} isn't provisioned. Add them with scripts/provision_user.py.`
            : `Dev login failed (${res.status}).`,
        );
        return;
      }
      window.location.assign("/");
    } catch {
      setError("Could not reach the API.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 border-t border-dashed border-amber-300 pt-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
        Local development only
      </p>
      <p className="text-xs text-slate-500 mt-1">
        Signs in without verifying identity. Only provisioned accounts work, and
        roles still come from the database.
      </p>

      {info.users.length === 0 ? (
        <p className="mt-3 text-xs text-slate-600">
          No accounts provisioned yet. Run{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5">
            python -m scripts.provision_user add you@smu.edu.sg root_admin
          </code>{" "}
          in the API container first.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <select
            aria-label="Account to sign in as"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
          >
            {info.users.map((u) => (
              <option key={u.email} value={u.email}>
                {u.email} — {u.role}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={signIn}
            disabled={busy || !email}
            className="block w-full rounded-lg border border-amber-400 bg-amber-50 py-2.5 text-sm font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in as this user"}
          </button>
        </div>
      )}

      {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
    </div>
  );
}

export function Login() {
  const cachedHint = localStorage.getItem(LOGIN_HINT_KEY) ?? "";
  const devAuth = useDevAuth();
  const showEntra = devAuth.status !== "on" || devAuth.info.entra_configured;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Prompt Patrol</h1>
        <p className="text-xs tracking-wide text-slate-500 mt-1">
          AI-ANSWER TRIAGE FOR INSTRUCTORS
        </p>
      </div>
      <div className="bg-white rounded-xl shadow-sm p-9 w-[400px]">
        <h2 className="text-xl font-semibold text-slate-900 mb-6">Sign in</h2>
        {showEntra && (
          <form method="get" action="/api/auth/login" className="space-y-4">
            <div>
              <label
                htmlFor="login_hint"
                className="block text-sm font-medium text-slate-700 mb-1"
              >
                Email
              </label>
              <input
                id="login_hint"
                name="login_hint"
                type="email"
                defaultValue={cachedHint}
                placeholder="you@smu.edu.sg"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
              />
            </div>
            <button
              type="submit"
              className="block w-full text-center rounded-lg bg-slate-900 text-white font-medium py-3 hover:bg-slate-800"
            >
              Sign in with Microsoft
            </button>
          </form>
        )}
        {DEV_BUILD && devAuth.status === "on" && (
          <DevLoginPanel info={devAuth.info} />
        )}
      </div>
    </div>
  );
}
