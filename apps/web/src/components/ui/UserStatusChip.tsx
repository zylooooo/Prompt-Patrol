import { Clock } from "lucide-react";
import {
  isPending,
  userStatusLabel,
  type AppUser,
  type UserStatus,
} from "../../types";

// Account state is chrome, not a verdict: indigo/neutral tokens only, and the
// dot shape (filled / hollow / none), the clock icon and the label carry the state
// without color. Deleted is the one danger-colored state: it is terminal.
type ChipKind = UserStatus | "pending";

const CHIP_CLASS: Record<ChipKind, string> = {
  active: "border border-transparent bg-primary-soft text-primary",
  pending: "border border-primary-border bg-surface text-primary",
  deactivated:
    "border border-transparent bg-surface-muted text-muted-foreground",
  deleted: "border border-transparent bg-danger-soft text-danger",
};

const DOT_CLASS: Record<Exclude<ChipKind, "pending">, string> = {
  active: "bg-current",
  deactivated: "border border-current",
  deleted: "hidden",
};

export default function UserStatusChip({ user }: { user: AppUser }) {
  const kind: ChipKind = isPending(user) ? "pending" : user.status;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${CHIP_CLASS[kind]}`}
    >
      {kind === "pending" ? (
        <Clock aria-hidden="true" className="h-3 w-3 shrink-0" />
      ) : (
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT_CLASS[kind]}`}
        />
      )}
      {userStatusLabel(user)}
    </span>
  );
}
