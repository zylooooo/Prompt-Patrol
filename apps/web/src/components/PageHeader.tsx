interface PageHeaderProps {
  title: string;
  subtitle?: string;
  showModelStatus?: boolean;
}

export default function PageHeader({
  title,
  subtitle,
  showModelStatus = true,
}: PageHeaderProps) {
  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <h1 className="text-[26px] font-bold text-foreground">{title}</h1>
        {subtitle && (
          <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {showModelStatus && (
        <span className="flex shrink-0 items-center gap-2 self-start rounded-full border border-border bg-surface px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted-foreground">
          <span
            aria-hidden
            className="h-[7px] w-[7px] rounded-full bg-accent"
          />
          demo detector · scores uncalibrated
        </span>
      )}
    </header>
  );
}
