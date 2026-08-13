import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ToastContext } from './toastContext'

const TOAST_MS = 3500

// One toast at a time, a new message replaces the old. Confirmations only,
// errors stay inline next to whatever caused them
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const showToast = useCallback((msg: string) => {
    setMessage(msg)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setMessage(null), TOAST_MS)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const value = useMemo(() => ({ showToast }), [showToast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* the wrapper stays mounted even when empty. Screen readers only
          announce changes inside a live region that already exists, so moving
          this div inside the conditional would silence every toast */}
      <div role="status" aria-live="polite" className="fixed right-6 bottom-6 z-50">
        {message && (
          <button
            type="button"
            onClick={() => setMessage(null)}
            className="toast-enter flex items-center gap-3 rounded-lg bg-navy-800 py-3 pr-5 pl-4 text-sm text-white shadow-lg"
          >
            <span aria-hidden className="h-4 w-[3px] rounded-full bg-gold-500" />
            {message}
          </button>
        )}
      </div>
    </ToastContext.Provider>
  )
}
