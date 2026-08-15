import { useEffect, useRef, type ReactNode } from "react";

interface ModalProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
  busy?: boolean;
}

export default function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  busy,
}: ModalProps) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-foreground/50 px-4"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[540px] rounded-xl bg-surface-modal p-8 shadow-xl outline-none"
      >
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {subtitle && (
          <p className="mt-1 font-mono text-xs text-disabled-foreground">
            {subtitle}
          </p>
        )}
        <div className="mt-5">{children}</div>
        <div className="mt-6 flex justify-end gap-3">{footer}</div>
      </div>
    </div>
  );
}
