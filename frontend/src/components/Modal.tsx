import { useEffect, useRef, type ReactNode } from 'react'

interface ModalProps {
  title: string
  subtitle?: string
  onClose: () => void
  children: ReactNode
  footer: ReactNode
  // blocks closing while a save is in progress, so it cannot be left half done
  busy?: boolean
}

// Shared dialog shell. Backdrop click and Escape close it, and focus moves in on open
export default function Modal({ title, subtitle, onClose, children, footer, busy }: ModalProps) {
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    panel.current?.focus()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, busy])

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-navy-950/50 px-4"
      onClick={() => {
        if (!busy) onClose()
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[540px] rounded-xl bg-surface p-8 shadow-xl outline-none"
      >
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {subtitle && <p className="mt-1 font-mono text-xs text-ink-faint">{subtitle}</p>}
        <div className="mt-5">{children}</div>
        <div className="mt-6 flex justify-end gap-3">{footer}</div>
      </div>
    </div>
  )
}

export function DialogButton({
  onClick,
  variant = 'secondary',
  disabled,
  children,
}: {
  onClick: () => void
  variant?: 'primary' | 'secondary'
  disabled?: boolean
  children: ReactNode
}) {
  const base = 'h-11 rounded-lg px-5 text-sm transition-colors disabled:opacity-50'
  const style =
    variant === 'primary'
      ? 'bg-navy-800 font-semibold text-white hover:bg-navy-700'
      : 'border border-line text-ink-muted hover:text-ink'
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${style}`}>
      {children}
    </button>
  )
}
