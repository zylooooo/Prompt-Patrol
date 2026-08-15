import { Loader2 } from "lucide-react";

export type LoadingStateSize = "page" | "card" | "inline";

const SIZE = {
  page: "flex min-h-[18rem] flex-1 items-center justify-center gap-3 px-6 py-16 text-sm",
  card: "flex items-center justify-center gap-2 px-6 py-12 text-sm",
  inline: "flex items-center gap-2.5 px-1 py-3 text-xs",
} as const satisfies Record<LoadingStateSize, string>;

const SPINNER = {
  page: "h-5 w-5",
  card: "h-5 w-5",
  inline: "h-4 w-4",
} as const satisfies Record<LoadingStateSize, string>;

export default function LoadingState({
  size = "card",
  label = "Loading…",
  className = "",
}: {
  size?: LoadingStateSize;
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      className={`${SIZE[size]} text-muted-foreground ${className}`.trimEnd()}
    >
      <Loader2
        className={`${SPINNER[size]} shrink-0 animate-spin text-disabled-foreground`}
        aria-hidden="true"
      />
      {label}
    </div>
  );
}
