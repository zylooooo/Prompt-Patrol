import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { X } from "lucide-react";
import { ToastContext, type ToastOptions } from "../hooks/useToast";

const TOAST_MS = 3500;
// Long enough to read a sentence and act on it: an error names a recovery, and
// an Undo is worthless if it is gone before the eye lands on it.
const TOAST_ACTIONABLE_MS = 8000;

interface ToastState extends ToastOptions {
  message: string;
}

const TONE = {
  default: {
    box: "bg-primary text-primary-foreground",
    bar: "bg-accent-soft",
    button:
      "hover:bg-primary-foreground/15 focus-visible:bg-primary-foreground/25",
  },
  error: {
    box: "bg-danger text-danger-foreground",
    bar: "bg-danger-soft",
    button:
      "hover:bg-danger-foreground/15 focus-visible:bg-danger-foreground/25",
  },
} as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const dismiss = useCallback(() => {
    window.clearTimeout(timer.current);
    setToast(null);
  }, []);

  const showToast = useCallback((message: string, options: ToastOptions = {}) => {
    setToast({ message, ...options });
    window.clearTimeout(timer.current);
    const actionable = options.tone === "error" || options.action;
    timer.current = window.setTimeout(
      () => setToast(null),
      actionable ? TOAST_ACTIONABLE_MS : TOAST_MS,
    );
  }, []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const value = useMemo(() => ({ showToast }), [showToast]);
  const tone = TONE[toast?.tone ?? "default"];

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed right-6 bottom-6 z-50"
      >
        {toast && (
          <div
            role={toast.tone === "error" ? "alert" : undefined}
            className={`animate-toastIn flex max-w-md items-center gap-3 rounded-lg py-2 pr-2 pl-4 text-sm shadow-lg ${tone.box}`}
          >
            <span
              aria-hidden
              className={`h-4 w-[3px] shrink-0 rounded-full ${tone.bar}`}
            />
            <span className="py-1">{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                onClick={() => {
                  const { onClick } = toast.action!;
                  dismiss();
                  onClick();
                }}
                className={`shrink-0 rounded-md px-2.5 py-1.5 font-semibold underline underline-offset-2 transition-colors ${tone.button}`}
              >
                {toast.action.label}
              </button>
            )}
            <button
              type="button"
              onClick={dismiss}
              aria-label="Dismiss"
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors ${tone.button}`}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
