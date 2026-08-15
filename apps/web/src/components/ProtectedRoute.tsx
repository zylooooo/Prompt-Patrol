import type { ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";
import { hadSignedInSession } from "../api/auth";
import { atLeastRole, type UserRole } from "../types";

interface ProtectedRouteProps {
  children: ReactNode;
  minRole?: UserRole;
}

export function ProtectedRoute({ children, minRole }: ProtectedRouteProps) {
  const { user, isPending, isError } = useAuth();
  if (isPending) return null;

  if (!user) {
    const expired = !isError && hadSignedInSession();
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
