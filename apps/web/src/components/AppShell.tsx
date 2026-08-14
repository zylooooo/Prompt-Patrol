import { useEffect, useRef } from "react";
import { useAuth } from "../hooks/useAuth";
import { atLeastRole, ROLE_TEXT } from "../api/types";
import { NavLink, Outlet, useLocation } from "react-router-dom";

export default function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  const navItems = [
    { to: "/check", label: "Check answers" },
    { to: "/history", label: "History" },
    ...(user && atLeastRole(user.role, "instructor")
      ? [{ to: "/teaching-assistants", label: "Teaching assistants" }]
      : []),
    ...(user && atLeastRole(user.role, "root_admin")
      ? [{ to: "/users", label: "Users" }]
      : []),
  ];

  return (
    <div className="relative flex min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-10 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary"
      >
        Skip to main content
      </a>

      <aside className="flex w-60 shrink-0 flex-col justify-between bg-primary px-6 py-9">
        <div>
          <div className="inline-block">
            <p className="text-lg font-bold text-primary-foreground">
              Prompt Patrol
            </p>
            <div
              aria-hidden
              className="mt-2 h-[3px] w-full rounded-full bg-accent"
            />
          </div>

          <nav className="mt-9 flex flex-col gap-1.5" aria-label="Main">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-md py-2 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent/60 ${
                    isActive
                      ? "font-semibold text-primary-foreground"
                      : "text-primary-foreground/70 hover:text-primary-foreground"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      aria-hidden
                      className={`h-4 w-[3px] rounded-full ${isActive ? "bg-accent" : "bg-transparent"}`}
                    />
                    {item.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="border-t border-primary-foreground/10 pt-4">
          <p className="text-sm font-semibold break-all text-primary-foreground">
            {user?.email}
          </p>
          <div className="mt-1 flex items-center gap-3 text-[13px]">
            <span className="text-primary-foreground/60">
              {user ? ROLE_TEXT[user.role] : ""}
            </span>
            <form method="post" action="/api/auth/logout">
              <button
                type="submit"
                className="rounded-sm text-accent-soft transition-colors hover:text-primary-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                Sign out
              </button>
            </form>
          </div>
        </div>
      </aside>

      <main
        id="main-content"
        ref={mainRef}
        tabIndex={-1}
        className="min-w-0 flex-1 px-11 py-11 outline-none"
      >
        <Outlet />
      </main>
    </div>
  );
}
