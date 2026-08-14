import { useAuth } from "../hooks/useAuth";
import Button from "../components/ui/Button";
import { useNavigate } from "react-router-dom";
import TextButton from "../components/ui/TextButton";

export default function NotFoundPage() {
  const navigate = useNavigate();
  const { user, isPending } = useAuth();

  const destination = user
    ? { to: "/", label: "Back to the triage queue" }
    : { to: "/login", label: "Go to sign in" };

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-12">
      <section className="grid w-full max-w-4xl items-center gap-10 md:grid-cols-[auto_1fr] md:gap-16">
        <div className="flex justify-center text-foreground md:justify-end">
          <FourOhFour />
        </div>

        <div className="flex flex-col gap-5 text-center md:text-left">
          <p className="text-xs font-bold uppercase tracking-wider text-accent">
            Nothing to triage here
          </p>
          <h1 className="text-4xl font-bold leading-tight tracking-tight text-foreground md:text-5xl">
            We patrolled everywhere.
          </h1>
          <p className="max-w-md text-sm leading-relaxed text-muted-foreground md:text-base">
            This page isn't on our beat. The URL might be mistyped, or the route
            hasn't shipped yet. Either way, Prompt Patrol is one click away.
          </p>
          <div className="flex flex-col items-center gap-3 md:flex-row md:items-center">
            <Button
              size="md"
              disabled={isPending}
              onClick={() => void navigate(destination.to, { replace: true })}
            >
              {isPending ? "Checking your session…" : destination.label}
            </Button>
            <TextButton
              onClick={() => void navigate(-1)}
              tone="muted"
              className="text-sm"
            >
              or take a step back
            </TextButton>
          </div>
        </div>
      </section>
    </main>
  );
}

function FourOhFour() {
  return (
    <div
      aria-label="404"
      role="img"
      className="flex select-none items-center gap-2 leading-none"
    >
      <span className="text-[7rem] font-bold tracking-tight md:text-[10rem]">
        4
      </span>
      <svg
        viewBox="0 0 100 100"
        fill="none"
        aria-hidden="true"
        className="h-[6rem] w-[6rem] md:h-[8.5rem] md:w-[8.5rem]"
      >
        <circle cx="42" cy="46" r="30" stroke="currentColor" strokeWidth="7" />
        <line
          x1="64"
          y1="68"
          x2="89"
          y2="93"
          stroke="currentColor"
          strokeWidth="7"
          strokeLinecap="round"
        />
      </svg>
      <span className="text-[7rem] font-bold tracking-tight md:text-[10rem]">
        4
      </span>
    </div>
  );
}
