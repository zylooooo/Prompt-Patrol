import Button from "./Button";
import type { ReactNode } from "react";

export type ErrorStateSize = "page" | "card";

const SIZE = {
  page: "flex min-h-screen items-center justify-center px-6 py-12 text-center",
  card: "rounded-xl border border-border bg-surface p-12 text-center",
} as const satisfies Record<ErrorStateSize, string>;

export default function ErrorState({
  title,
  description,
  onRetry,
  retryLabel = "Try again",
  size = "card",
  className = "",
  children,
}: {
  title: string;
  description?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  size?: ErrorStateSize;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <section role="alert" className={`${SIZE[size]} ${className}`.trimEnd()}>
      <div>
        <p className="text-lg font-medium text-foreground">{title}</p>
        {description && (
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            {description}
          </p>
        )}
        {onRetry && (
          <Button variant="secondary" className="mt-5" onClick={onRetry}>
            {retryLabel}
          </Button>
        )}
        {children}
      </div>
    </section>
  );
}
