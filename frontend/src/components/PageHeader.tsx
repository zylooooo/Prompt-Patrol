interface PageHeaderProps {
  title: string
  subtitle?: string
  // only screens that show scores get the model pill, it means nothing on the account pages
  showModelStatus?: boolean
}

export default function PageHeader({ title, subtitle, showModelStatus = true }: PageHeaderProps) {
  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <h1 className="font-display text-[26px] font-bold text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {showModelStatus && (
        // TODO(PP): read this from GET /api/detector once it exists
        <span className="flex shrink-0 items-center gap-2 self-start rounded-full border border-line bg-surface px-3 py-1.5 font-mono text-xs whitespace-nowrap text-ink-muted">
          <span aria-hidden className="h-[7px] w-[7px] rounded-full bg-gold-500" />
          demo detector · scores uncalibrated
        </span>
      )}
    </header>
  )
}
