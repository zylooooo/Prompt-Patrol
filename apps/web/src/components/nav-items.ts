import type { UserRole } from "../api/types";

export interface NavItem {
  to: string;
  label: string;
  minRole?: UserRole;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/check", label: "Check answers" },
  { to: "/history", label: "History" },
  {
    to: "/teaching-assistants",
    label: "Teaching assistants",
    minRole: "instructor",
  },
  { to: "/users", label: "Users", minRole: "root_admin" },
];
