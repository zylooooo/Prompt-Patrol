import type { UserRole } from "../types";

export interface NavItem {
  to: string;
  label: string;
  roles?: readonly UserRole[];
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/check", label: "Check answers" },
  { to: "/history", label: "Check history" },
  {
    to: "/teaching-assistants",
    label: "My teaching assistants",
    roles: ["instructor"],
  },
  { to: "/users", label: "All accounts", roles: ["root_admin"] },
];
