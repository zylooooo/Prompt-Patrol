import type { UserRole } from "../types";

export interface NavItem {
  to: string;
  label: string;
  minRole?: UserRole;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/check", label: "Screen New Answers" },
  { to: "/history", label: "Screening History" },
  {
    to: "/teaching-assistants",
    label: "Manage My Assistants",
    minRole: "instructor",
  },
  { to: "/users", label: "Manage All Accounts", minRole: "root_admin" },
];
