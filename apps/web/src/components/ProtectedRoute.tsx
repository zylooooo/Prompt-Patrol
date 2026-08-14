import type { ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { Navigate } from "react-router-dom";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isPending } = useAuth();
  if (isPending) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
