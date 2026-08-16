import type { ReactNode } from "react";
import { useAuth } from "../hooks/useAuth";
import { hadSignedInSession } from "../api/auth";
import { Navigate, useSearchParams } from "react-router-dom";

interface GuestRouteProps {
  children: ReactNode;
}

export function GuestRoute({ children }: GuestRouteProps) {
  const { user, isPending } = useAuth();
  const [searchParams] = useSearchParams();

  if (isPending) {
    return hadSignedInSession() ? null : <>{children}</>;
  }
  if (!user) return <>{children}</>;
  if (searchParams.has("error")) return <>{children}</>;

  return <Navigate to="/" replace />;
}
