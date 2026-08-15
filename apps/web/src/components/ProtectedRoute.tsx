import type { ReactNode } from "react";
import ErrorState from "./ui/ErrorState";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";
import LoadingState from "./ui/LoadingState";
import { hadSignedInSession } from "../api/auth";
import { useShowAfter } from "../hooks/useShowAfter";
import { atLeastRole, type UserRole } from "../types";

interface ProtectedRouteProps {
  children: ReactNode;
  minRole?: UserRole;
}

const SPINNER_DELAY_MS = 250;

export function ProtectedRoute({ children, minRole }: ProtectedRouteProps) {
  const { user, isPending, isError, refetch } = useAuth();
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
    return (
      <ErrorState
        size="page"
        title="Can't reach Prompt Patrol"
        description="We couldn't check your sign-in because the server didn't respond. You have not been signed out - this is usually temporary."
        onRetry={() => void refetch()}
      />
    );
  }

  if (!user) {
    const expired = hadSignedInSession();
    return (
      <Navigate
        to={expired ? "/login?error=session_expired" : "/login"}
        replace
      />
    );
  }

  if (minRole && !atLeastRole(user.role, minRole)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
