import { useState, type ReactNode } from "react";
import Button from "./ui/Button";
import FormNotice from "./ui/FormNotice";
import Wordmark from "./ui/Wordmark";
import SignOutForm from "./SignOutForm";
import { useAuth } from "../hooks/useAuth";
import { useUpdateDisplayName } from "../hooks/useUsers";
import { usePageTitle } from "../hooks/usePageTitle";

const FIELD =
  "h-11 w-full rounded-md border border-input-border bg-input-bg px-3.5 text-sm text-foreground placeholder:text-input-placeholder transition focus-visible:bg-accent-soft";

/**
 * Nobody types a name for someone else any more ([0.21.0] DISPLAY NAME): the
 * person picks it on their first sign-in. A courtesy, not a control - the
 * server gates nothing on a missing name, and the app renders emails until
 * there is one.
 */
export default function ChooseNameGate({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!user || user.name !== null) return <>{children}</>;
  return <ChooseName id={user.id} email={user.email} />;
}

function ChooseName({ id, email }: { id: string; email: string }) {
  usePageTitle("Choose your name");
  const rename = useUpdateDisplayName();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    setError(null);
    try {
      // The session refetch this triggers is what lifts the gate.
      await rename.mutateAsync({ id, name: name.trim() });
    } catch {
      setError("Couldn't save your name. Try again.");
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md rounded-xl bg-surface p-7 shadow-md">
        <Wordmark className="h-7 w-auto" />
        <h1 className="mt-7 text-lg font-semibold text-foreground">
          What should we call you?
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          This is the name other people see in Prompt Patrol. You can change it
          later.
        </p>

        <form
          className="mt-6 flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void onSubmit();
          }}
        >
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">Your name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              autoComplete="name"
              autoFocus
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "choose-name-error" : undefined}
              className={FIELD}
            />
          </label>
          {error && (
            <FormNotice tone="error" id="choose-name-error" role="alert">
              {error}
            </FormNotice>
          )}
          <Button
            type="submit"
            fullWidth
            disabled={!name.trim() || rename.isPending}
          >
            {rename.isPending ? "Saving…" : "Continue"}
          </Button>
        </form>

        <div className="mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border pt-4 text-[13px] text-muted-foreground">
          <span>
            Signed in as <span className="font-mono text-xs">{email}</span>.
          </span>
          <SignOutForm>
            <button
              type="submit"
              className="rounded px-1 text-primary underline-offset-2 hover:underline focus-visible:bg-accent-soft"
            >
              Not you? Sign out
            </button>
          </SignOutForm>
        </div>
      </div>
    </main>
  );
}
