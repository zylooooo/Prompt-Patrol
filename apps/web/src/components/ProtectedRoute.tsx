import type { ReactNode } from "react";
import ErrorState from "./ui/ErrorState";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";
import { hadSignedInSession } from "../api/auth";
import { atLeastRole, type UserRole } from "../types";

interface ProtectedRouteProps {
  children: ReactNode;
  minRole?: UserRole;
}

export function ProtectedRoute({ children, minRole }: ProtectedRouteProps) {
  const { user, isPending, isError, refetch } = useAuth();
  if (isPending) return null;

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
