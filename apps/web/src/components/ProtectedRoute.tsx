import type { ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";
import { atLeastRole, type UserRole } from "../api/types";

interface ProtectedRouteProps {
  children: ReactNode;
  minRole?: UserRole;
}

export function ProtectedRoute({ children, minRole }: ProtectedRouteProps) {
  const { user, isPending } = useAuth();
  if (isPending) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (minRole && !atLeastRole(user.role, minRole)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
