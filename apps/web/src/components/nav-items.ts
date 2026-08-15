import type { UserRole } from "../types";

export interface NavItem {
  to: string;
  label: string;
  minRole?: UserRole;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/check", label: "Check answers" },
  { to: "/history", label: "Past checks" },
  {
    to: "/teaching-assistants",
    label: "My teaching assistants",
    minRole: "instructor",
  },
  { to: "/users", label: "All accounts", minRole: "root_admin" },
];
