import Button from "../components/ui/Button";
import { LOGIN_HINT_KEY } from "../api/auth";
import Wordmark from "../components/ui/Wordmark";
import { useSearchParams } from "react-router-dom";

const HERO_IMAGE_URL =
  "https://images.unsplash.com/photo-1541339907198-e08756dedf3f?q=75&w=2000&auto=format&fit=crop";

const INPUT_CLASS =
  "w-full rounded-lg border border-transparent bg-surface-muted px-3.5 py-3 text-sm text-foreground placeholder:text-disabled-foreground transition-all outline-hidden focus-visible:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-60";

const LABEL_CLASS =
  "mb-2.5 block text-xs font-bold uppercase tracking-wide text-muted-foreground";

const REDIRECT_ERROR_MESSAGES: Record<string, string> = {
  not_provisioned:
    "Your Microsoft account isn't set up for Prompt Patrol yet. Ask an admin to provision your account, then try again.",
  sign_in_cancelled:
    "Sign-in was cancelled, so you aren't signed in. Use the button below when you're ready to try again.",
  sign_in_failed:
    "We couldn't complete sign-in with Microsoft. This usually means the sign-in page was left open too long. Start again below.",
  session_expired:
    "You were signed out because your session timed out. Sign in again to continue.",
};

function LoginHero() {
  return (
    <div
      className="relative hidden bg-cover bg-center lg:flex lg:w-2/3 xl:w-3/4"
      style={{ backgroundImage: `url("${HERO_IMAGE_URL}")` }}
    >
      <div className="absolute inset-0 bg-foreground/55" />
      <div className="relative z-10 flex max-w-2xl flex-col justify-end p-12 text-primary-foreground">
        <Wordmark
          role="heading"
          aria-level={1}
          className="[&_.logo-accent]:fill-accent-border h-24 w-auto"
        />
      </div>
    </div>
  );
}

export default function LoginPage() {
  const cachedHint = localStorage.getItem(LOGIN_HINT_KEY) ?? "";

  const [searchParams] = useSearchParams();
  const redirectError = searchParams.get("error");
  const redirectErrorMessage = redirectError
    ? (REDIRECT_ERROR_MESSAGES[redirectError] ??
      "Sign-in failed. Please try again.")
    : null;

  return (
    <div className="flex min-h-screen">
      <LoginHero />

      <div className="flex w-full items-center justify-center px-6 py-10 lg:w-1/3 lg:px-8 xl:w-1/4">
        <div className="w-full max-w-sm">
          <header className="mb-8">
            <Wordmark className="mb-6 h-14 w-auto text-foreground lg:hidden" />
            <p className="mb-3 text-xs font-bold tracking-wider text-accent uppercase">
              AI-Answer Triage for Instructors
            </p>
            <h2 className="text-3xl leading-tight font-bold tracking-tight text-foreground">
              Sign in to Prompt Patrol
            </h2>
          </header>

          {redirectErrorMessage && (
            <div
              role="alert"
              className="mb-5 rounded-lg border border-danger-border bg-danger-soft px-3 py-2 text-sm leading-5 text-danger"
            >
              {redirectErrorMessage}
            </div>
          )}

          <form method="get" action="/api/auth/login" className="space-y-5">
            <div>
              <label htmlFor="login_hint" className={LABEL_CLASS}>
                Email
              </label>
              <input
                id="login_hint"
                name="login_hint"
                type="email"
                defaultValue={cachedHint}
                placeholder="you@smu.edu.sg"
                autoComplete="email"
                className={INPUT_CLASS}
              />
            </div>
            <Button type="submit" fullWidth>
              Sign in with Microsoft
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
