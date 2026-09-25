import { createContext, useContext } from "react";

export interface ToastOptions {
  /** `error` toasts are announced assertively and stay up longer. */
  tone?: "error";
  /** One follow-up the person can take from the toast itself, e.g. Undo. */
  action?: { label: string; onClick: () => void };
}

export interface ToastContextValue {
  showToast: (message: string, options?: ToastOptions) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
