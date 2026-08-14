import type { HTMLAttributes, ReactNode } from "react";

export default function Page({ children }: { children: ReactNode }) {
  return <div className="flex h-full min-h-0 flex-col">{children}</div>;
}

export function PageScroll({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      {...rest}
      className={`min-h-0 flex-1 overflow-y-auto ${className ?? ""}`.trim()}
    >
      {children}
    </div>
  );
}

export function PageFill({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div
      {...rest}
      className={`flex min-h-0 flex-1 flex-col ${className ?? ""}`.trim()}
    >
      {children}
    </div>
  );
}
