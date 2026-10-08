import type { ReactNode } from "react";
import { Link } from "react-router-dom";

// inline-flex so the <a> variant boxes its padding like the <button> does —
// a bare inline <a> ignores vertical padding for layout and sits taller/lower.
const ROW_ACTION_CLASS =
  "inline-flex cursor-pointer items-center rounded-md px-2.5 py-[5px] text-[13px] text-primary transition-colors hover:bg-primary-soft focus-visible:bg-primary-soft disabled:pointer-events-none disabled:opacity-45";

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
