import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export default function PageHeader({
  title,
  subtitle,
  actions,
}: PageHeaderProps) {
  return (
    <header className="flex shrink-0 items-start justify-between gap-6">
      <div>
        <h1 className="text-[26px] font-bold text-foreground">{title}</h1>
        {subtitle && (
          <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions}
    </header>
  );
}
