import { Navigate } from 'react-router-dom'
import { LOGIN_HINT_KEY, useAuth } from '../lib/authContext'
import { usePageTitle } from '../lib/usePageTitle'

// No password here. Identity comes from Microsoft, so this is a plain GET
// form to /api/auth/login and the browser follows the redirects there and
// back. Fetch would choke on the opaque redirect, hence no onSubmit handler.
// login_hint only prefills the Microsoft sign-in box, the backend does not
// trust it for anything
export default function LoginPage() {
  usePageTitle('Sign in')
  const { user, loading } = useAuth()
  const cachedHint = localStorage.getItem(LOGIN_HINT_KEY) ?? ''

  if (loading) return null
  if (user) return <Navigate to="/check" replace />

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-bg px-4">
      <header className="flex flex-col items-center gap-2.5">
        <h1 className="font-display text-[32px] font-bold text-navy-800">Prompt Patrol</h1>
        <p className="text-[11px] font-semibold tracking-[0.09em] text-ink-faint uppercase">
          AI-answer triage for instructors
        </p>
        <div aria-hidden className="mt-1 h-[3px] w-7 rounded-full bg-gold-500" />
      </header>

      <main className="w-full max-w-[400px] rounded-xl border border-line bg-surface p-9">
        <h2 className="font-display text-xl font-medium text-ink">Sign in</h2>

        <form method="get" action="/api/auth/login" className="mt-5 flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <label
              htmlFor="login_hint"
              className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase"
            >
              SMU email
            </label>
            <input
              id="login_hint"
              name="login_hint"
              type="email"
              autoComplete="email"
              placeholder="name@smu.edu.sg"
              defaultValue={cachedHint}
              className="h-11 rounded-md border border-line bg-field px-3.5 text-sm text-ink placeholder:text-hint"
            />
          </div>

          <button
            type="submit"
            className="h-11 rounded-lg bg-navy-800 text-sm font-semibold text-white transition-colors hover:bg-navy-700"
          >
            Sign in with Microsoft
          </button>
        </form>

        <p className="mt-5 text-xs text-ink-muted">
          Accounts are created by an administrator. If sign in is refused, your account has not been
          set up yet.
        </p>
      </main>
    </div>
  )
}
