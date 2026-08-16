import Sidebar from "./Sidebar";
import { useEffect, useRef } from "react";
import { useAuth } from "../hooks/useAuth";
import SessionSentinel from "./SessionSentinel";
import { Outlet, useLocation } from "react-router-dom";

export default function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const lastPath = useRef(location.pathname);

  useEffect(() => {
    if (lastPath.current === location.pathname) return;
    lastPath.current = location.pathname;
    mainRef.current?.focus();
  }, [location.pathname]);

  return (
    <div className="relative flex h-dvh overflow-hidden">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-60 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary"
      >
        Skip to main content
      </a>

      <Sidebar user={user ?? null} />

      <main
        id="main-content"
        ref={mainRef}
        tabIndex={-1}
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-6 pt-16 pb-6 outline-none md:px-11 md:py-9"
      >
        <Outlet />
      </main>

      <SessionSentinel />
    </div>
  );
}
