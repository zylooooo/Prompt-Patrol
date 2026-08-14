import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const ROW_ACTION_CLASS =
  "cursor-pointer rounded-md px-2.5 py-[5px] text-[13px] text-primary transition-colors hover:bg-primary-soft focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 disabled:pointer-events-none disabled:opacity-45";

interface RowActionProps {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}

export default function RowAction({
  onClick,
  disabled,
  children,
}: RowActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={ROW_ACTION_CLASS}
    >
      {children}
    </button>
  );
}

export function RowActionLink({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link to={to} className={ROW_ACTION_CLASS}>
      {children}
    </Link>
  );
}
