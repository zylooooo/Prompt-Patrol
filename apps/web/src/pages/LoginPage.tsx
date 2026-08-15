import {
  authKeys,
  devLogin,
  getDevAuthInfo,
  type DevAuthInfo,
} from "../api/auth";
import { useState } from "react";
import { ApiError } from "../api/client";
import Button from "../components/ui/Button";
import { LOGIN_HINT_KEY } from "../hooks/useAuth";
import { useMutation, useQuery } from "@tanstack/react-query";

const DEV_BUILD = import.meta.env.DEV;

const HERO_IMAGE_URL =
  "https://images.unsplash.com/photo-1541339907198-e08756dedf3f?q=75&w=2000&auto=format&fit=crop";

const INPUT_CLASS =
  "w-full rounded-lg border border-transparent bg-surface-muted px-3.5 py-3 text-sm text-foreground placeholder:text-disabled-foreground transition-all outline-hidden focus-visible:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-60";

const LABEL_CLASS =
  "mb-2.5 block text-xs font-bold uppercase tracking-wide text-muted-foreground";

function useDevAuth() {
  return useQuery({
    queryKey: authKeys.devAuth(),
    queryFn: ({ signal }) => getDevAuthInfo(signal),
    enabled: DEV_BUILD,
  });
}

function devLoginErrorMessage(error: unknown, email: string): string {
  if (error instanceof ApiError) {
    return error.status === 403
      ? `${email} isn't provisioned. Add them with scripts/provision_user.py.`
      : `Dev login failed (${error.status}).`;
  }
  return "Could not reach the API.";
}

function DevLoginPanel({ info }: { info: DevAuthInfo }) {
  const [email, setEmail] = useState(info.users[0]?.email ?? "");

  const signIn = useMutation({
    mutationFn: devLogin,
    onSuccess: () => window.location.assign("/"),
  });

  const error = signIn.isError
    ? devLoginErrorMessage(signIn.error, email)
    : null;

  return (
    <div className="mt-6 space-y-3 rounded-lg border border-dashed border-warning-border bg-warning-soft p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Development Only (No Authentication)
      </p>

      {info.users.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No accounts provisioned yet. Run{" "}
          <code className="rounded-sm bg-surface-muted px-1 py-0.5">
            python -m scripts.provision_user add you@smu.edu.sg root_admin
          </code>{" "}
          in the API container first.
        </p>
      ) : (
        <>
          <input
            type="email"
            aria-label="Account to sign in as"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@smu.edu.sg"
            autoComplete="email"
            className={INPUT_CLASS}
          />
          <Button
            type="button"
            variant="secondary"
            fullWidth
            onClick={() => signIn.mutate(email)}
            disabled={signIn.isPending || !email}
          >
            {signIn.isPending ? "Signing in…" : "Sign in as this user"}
          </Button>
        </>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-danger-border bg-danger-soft px-3 py-2 text-sm leading-5 text-danger"
        >
          {error}
        </div>
      )}
    </div>
  );
}

function LoginHero() {
  return (
    <div
      className="relative hidden bg-cover bg-center lg:flex lg:w-2/3 xl:w-3/4"
      style={{ backgroundImage: `url("${HERO_IMAGE_URL}")` }}
    >
      <div className="absolute inset-0 bg-foreground/55" />
      <div className="relative z-10 flex max-w-2xl flex-col justify-end p-12 text-disabled-foreground">
        <h1 className="text-5xl font-bold tracking-normal">Prompt Patrol</h1>
      </div>
    </div>
  );
}

export default function LoginPage() {
  const cachedHint = localStorage.getItem(LOGIN_HINT_KEY) ?? "";
  const devAuthInfo = useDevAuth().data ?? null;
  const entraUnavailable =
    devAuthInfo !== null && !devAuthInfo.entra_configured;
  const [entraError, setEntraError] = useState<string | null>(null);

  return (
    <div className="flex min-h-screen bg-background">
      <LoginHero />

      <div className="flex w-full items-center justify-center px-6 py-10 lg:w-1/3 lg:px-8 xl:w-1/4">
        <div className="w-full max-w-sm">
          <header className="mb-8">
            <p className="mb-3 text-xs font-bold uppercase tracking-wider text-accent">
              AI-Answer Triage for Instructors
            </p>
            <h2 className="text-3xl font-bold leading-tight tracking-tight text-foreground">
              Sign in to Prompt Patrol
            </h2>
          </header>

          <form
            method="get"
            action="/api/auth/login"
            className="space-y-5"
            onSubmit={(event) => {
              if (!entraUnavailable) return;
              event.preventDefault();
              setEntraError("Microsoft sign-in is unavailable.");
            }}
          >
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
            {entraError && (
              <div
                role="alert"
                className="rounded-lg border border-danger-border bg-danger-soft px-3 py-2 text-sm leading-5 text-danger"
              >
                {entraError}
              </div>
            )}
          </form>

          {DEV_BUILD && devAuthInfo !== null && (
            <DevLoginPanel info={devAuthInfo} />
          )}
        </div>
      </div>
    </div>
  );
}
