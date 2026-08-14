import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export type TextTone = "primary" | "muted";

const TEXT_BASE =
  "rounded-sm underline-offset-2 transition-colors hover:underline focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30";

const TONE: Record<TextTone, string> = {
  primary: "text-primary",
  muted: "text-muted-foreground hover:text-foreground",
};

export default function TextButton({
  onClick,
  tone = "primary",
  className,
  children,
}: {
  onClick: () => void;
  tone?: TextTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${TEXT_BASE} ${TONE[tone]} ${className ?? ""}`.trim()}
    >
      {children}
    </button>
  );
}

export function TextLink({
  to,
  tone = "primary",
  className,
  children,
}: {
  to: string;
  tone?: TextTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className={`${TEXT_BASE} ${TONE[tone]} ${className ?? ""}`.trim()}
    >
      {children}
    </Link>
  );
}
