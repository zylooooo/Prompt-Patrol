import { useSearchParams } from "react-router-dom";
import { LOGIN_HINT_KEY } from "../hooks/useAuth";

const ERROR_MESSAGES: Record<string, string> = {
  not_provisioned:
    "Your Microsoft account isn't set up for Prompt Patrol yet. Ask an admin to provision your account, then try again.",
};

export function Login() {
  // Prefills from a prior login since useAuth caches the email on success,
  // but the field still lets a first-time visitor type theirs in. Using a
  // plain GET form means the browser builds the querystring itself, so we
  // don't need any JS to hit /api/auth/login.
  const cachedHint = localStorage.getItem(LOGIN_HINT_KEY) ?? "";
  const [searchParams] = useSearchParams();
  const error = searchParams.get("error");
  const errorMessage = error ? (ERROR_MESSAGES[error] ?? "Sign-in failed. Please try again.") : null;

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
        {errorMessage && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {errorMessage}
          </div>
        )}
        <form method="get" action="/api/auth/login" className="space-y-4">
          <div>
            <label htmlFor="login_hint" className="block text-sm font-medium text-slate-700 mb-1">
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
      </div>
    </div>
  );
}
