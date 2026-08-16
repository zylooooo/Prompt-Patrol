import Wordmark from "./ui/Wordmark";
import SignOutForm from "./SignOutForm";
import type { User } from "../api/auth";
import { LogOut, Menu, X } from "lucide-react";
import { atLeastRole, ROLE_TEXT } from "../types";
import { NAV_ITEMS, type NavItem } from "./nav-items";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { NavLink, useLocation } from "react-router-dom";
import { useCallback, useEffect, useRef, useState } from "react";

const DESKTOP_QUERY = "(min-width: 48rem)";

function visibleTo(user: User | null, items: readonly NavItem[]): NavItem[] {
  if (!user) return [];
  return items.filter(
    (item) => !item.minRole || atLeastRole(user.role, item.minRole),
  );
}

interface SidebarProps {
  user: User | null;
  items?: readonly NavItem[];
}

export default function Sidebar({ user, items = NAV_ITEMS }: SidebarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const { pathname } = useLocation();
  const asideRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const closerRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setIsOpen(false), []);

  const [lastFrame, setLastFrame] = useState({ pathname, isDesktop });
  if (lastFrame.pathname !== pathname || lastFrame.isDesktop !== isDesktop) {
    setLastFrame({ pathname, isDesktop });
    setIsOpen(false);
  }

  const isDrawerOpen = isOpen && !isDesktop;

  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!isDrawerOpen) {
      if (wasOpenRef.current) {
        wasOpenRef.current = false;
        openerRef.current?.focus();
      }
      return;
    }

    wasOpenRef.current = true;
    closerRef.current?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };

    const onFocusIn = (e: FocusEvent) => {
      if (!asideRef.current?.contains(e.target as Node)) {
        closerRef.current?.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [isDrawerOpen]);

  const links = visibleTo(user, items);

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        onClick={() => setIsOpen(true)}
        aria-label="Open navigation"
        aria-expanded={isDrawerOpen}
        aria-controls={SIDEBAR_ID}
        className={`${
          isDrawerOpen ? "hidden" : "inline-flex"
        } fixed top-3 left-3 z-50 h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-md transition-colors hover:bg-primary-hover focus-visible:bg-primary-hover md:hidden`}
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      {isDrawerOpen && (
        <div
          aria-hidden="true"
          onClick={close}
          className="fixed inset-0 z-30 bg-foreground/50 md:hidden"
        />
      )}

      <aside
        ref={asideRef}
        id={SIDEBAR_ID}
        inert={!isDesktop && !isOpen}
        className={`fixed top-0 left-0 z-40 flex h-dvh w-60 shrink-0 flex-col bg-primary transition-transform duration-200 ease-out md:sticky md:z-auto md:translate-x-0 md:self-start ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex shrink-0 items-start justify-between px-6 pt-9">
          <Wordmark className="[&_.logo-accent]:fill-accent-border h-11 w-auto text-primary-foreground" />
          <button
            ref={closerRef}
            type="button"
            onClick={close}
            aria-label="Close navigation"
            className="-mr-2 inline-flex h-8 w-8 items-center justify-center rounded-md text-primary-foreground/70 transition-colors hover:text-primary-foreground focus-visible:bg-accent/30 focus-visible:text-primary-foreground md:hidden"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <nav
          aria-label="Primary"
          className="mt-9 min-h-0 flex-1 overflow-y-auto px-6"
        >
          <ul className="flex flex-col gap-1.5">
            {links.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-md py-2 text-sm transition-colors focus-visible:bg-accent/30 focus-visible:text-primary-foreground ${
                      isActive
                        ? "font-semibold text-primary-foreground"
                        : "text-primary-foreground/70 hover:text-primary-foreground"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span
                        aria-hidden="true"
                        className={`h-4 w-[3px] shrink-0 rounded-full ${
                          isActive ? "bg-accent" : "bg-transparent"
                        }`}
                      />
                      <span className="truncate">{item.label}</span>
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="mx-6 mt-4 shrink-0 border-t border-primary-foreground/10 pt-4 pb-9">
          <p className="text-sm font-semibold break-all text-primary-foreground">
            {user?.email}
          </p>
          <p className="mt-1 text-[13px] text-primary-foreground/60">
            {user ? ROLE_TEXT[user.role] : ""}
          </p>

          <SignOutForm className="mt-3">
            <button
              type="submit"
              className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-2.5 rounded-md bg-danger/20 px-3 py-2 text-sm font-medium text-danger-on-primary transition-colors hover:bg-danger hover:text-danger-foreground focus-visible:bg-danger focus-visible:text-danger-foreground"
            >
              <LogOut className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate text-left">Sign out</span>
            </button>
          </SignOutForm>
        </div>
      </aside>
    </>
  );
}

const SIDEBAR_ID = "primary-navigation";
