import { USER_STATUS_TEXT, type UserStatus } from "../../types";

const CHIP_CLASS: Record<UserStatus, string> = {
  active: "bg-human-soft text-human",
  deactivated: "bg-unsure-soft text-unsure",
  deleted: "bg-surface-muted text-disabled-foreground",
};

export default function UserStatusChip({ status }: { status: UserStatus }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-medium ${CHIP_CLASS[status]}`}
    >
      {USER_STATUS_TEXT[status]}
    </span>
  );
}
