import { useEffect, useRef, useState } from 'react'

export interface Choice {
  value: string
  label: string
}

interface TokenMultiSelectProps {
  choices: Choice[]
  selected: string[]
  onChange: (next: string[]) => void
  placeholder: string
  width?: string
}

// Selected values sit in the field as removable tokens. The dropdown is a checklist
export default function TokenMultiSelect({
  choices,
  selected,
  onChange,
  placeholder,
  width = 'w-64',
}: TokenMultiSelectProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])

  return (
    <div ref={root} className={`relative ${width}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`flex min-h-11 w-full items-center justify-between gap-1.5 rounded-md border bg-surface px-2 py-1.5 text-left ${
          open ? 'border-navy-800' : 'border-line'
        }`}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          {selected.length === 0 && <span className="px-1.5 text-sm text-hint">{placeholder}</span>}
          {selected.map((value) => (
            <span
              key={value}
              className="flex items-center gap-1.5 rounded border border-line bg-navy-50 py-1 pr-1.5 pl-2 text-xs font-medium text-navy-800"
            >
              {choices.find((c) => c.value === value)?.label ?? value}
              <span
                role="button"
                tabIndex={0}
                aria-label={`Remove ${choices.find((c) => c.value === value)?.label ?? value}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(selected.filter((v) => v !== value))
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    e.stopPropagation()
                    onChange(selected.filter((v) => v !== value))
                  }
                }}
                className="cursor-pointer text-ink-faint hover:text-ink"
              >
                ×
              </span>
            </span>
          ))}
        </span>
        <span aria-hidden className="pr-1 text-xs text-ink-faint">
          {open ? '⌃' : '⌄'}
        </span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1.5 w-full rounded-lg border border-line bg-surface py-1.5 shadow-lg">
          {choices.length === 0 && (
            <p className="px-3 py-2 text-sm text-ink-faint">Nobody available.</p>
          )}
          {choices.map((choice) => (
            <label
              key={choice.value}
              className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm ${
                selected.includes(choice.value) ? 'bg-navy-50 font-medium text-ink' : 'text-ink'
              }`}
            >
              <input
                type="checkbox"
                checked={selected.includes(choice.value)}
                onChange={() => toggle(choice.value)}
                className="h-3.5 w-3.5 accent-navy-800"
              />
              {choice.label}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
