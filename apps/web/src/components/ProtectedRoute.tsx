import type { ReactNode } from "react";
import ErrorState from "./ui/ErrorState";
import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";
import LoadingState from "./ui/LoadingState";
import { canAccess, type UserRole } from "../types";
import { useShowAfter } from "../hooks/useShowAfter";

interface ProtectedRouteProps {
  children: ReactNode;
  roles?: readonly UserRole[];
}

const SPINNER_DELAY_MS = 250;

export function ProtectedRoute({ children, roles }: ProtectedRouteProps) {
  const { user, reason, isPending, isError, error, refetch } = useAuth();
  const showSpinner = useShowAfter(isPending, SPINNER_DELAY_MS);

  if (isPending) {
    if (!showSpinner) return null;
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState size="page" label="Checking your session…" />
      </div>
    );
  }

  if (isError) {
    const unreachable = error instanceof ApiError && error.isUnreachable;
    return (
      <ErrorState
        size="page"
        title={
          unreachable
            ? "Can't reach Prompt Patrol"
            : "Prompt Patrol is having a problem"
        }
        description={
          unreachable
            ? "We couldn't check your sign-in because the server didn't answer. You have not been signed out - check your connection, then try again."
            : "The server answered with an error, so we couldn't check your sign-in. This is on our side, not yours, and you have not been signed out. Try again in a moment, and tell your administrator if it keeps happening."
        }
        onRetry={() => void refetch()}
      />
    );
  }

  if (!user) {
    const explained = reason && reason !== "not_signed_in";
    return (
      <Navigate to={explained ? `/login?error=${reason}` : "/login"} replace />
    );
  }

  if (!canAccess(user.role, roles)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
