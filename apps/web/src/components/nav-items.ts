import type { UserRole } from "../types";

export interface NavItem {
  to: string;
  label: string;
  roles?: readonly UserRole[];
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/check", label: "Screen New Answers" },
  { to: "/history", label: "Screening History" },
  {
    to: "/teaching-assistants",
    label: "Manage My Assistants",
    roles: ["instructor"],
  },
  { to: "/users", label: "Manage All Accounts", roles: ["root_admin"] },
];
