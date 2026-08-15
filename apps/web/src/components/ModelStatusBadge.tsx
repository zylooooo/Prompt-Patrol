export default function ModelStatusBadge() {
  return (
    <span className="flex shrink-0 items-center gap-2 self-start rounded-full border border-border bg-surface px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted-foreground">
      <span aria-hidden className="h-[7px] w-[7px] rounded-full bg-accent" />
      demo detector · scores uncalibrated
    </span>
  );
}
