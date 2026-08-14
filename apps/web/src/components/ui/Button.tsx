import type { ComponentPropsWithRef, ReactNode } from "react";

export type ButtonSize = "xs" | "sm" | "md" | "lg" | "xl" | "icon" | "iconSm";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "destructive"
  | "destructiveOutline"
  | "ghost";

const SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "px-2.5 py-1.5 text-xs",
  sm: "px-3 py-2 text-sm",
  md: "px-3.5 py-2.5 text-sm",
  lg: "px-4 py-3 text-sm",
  xl: "px-4 py-3 text-xl",
  icon: "h-8 w-8",
  iconSm: "h-6 w-6",
};

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "font-medium text-primary-foreground bg-primary enabled:hover:bg-primary-hover focus-visible:ring-focus-ring/30 border border-transparent",
  secondary:
    "font-medium text-foreground bg-surface enabled:hover:bg-surface-muted focus-visible:ring-focus-ring/30 border border-border shadow-xs",
  destructive:
    "font-medium text-danger-foreground bg-danger enabled:hover:bg-danger-hover focus-visible:ring-danger/30 border border-transparent",
  destructiveOutline:
    "font-medium text-danger bg-surface enabled:hover:bg-danger-soft focus-visible:ring-danger/30 border border-danger/40 shadow-xs",
  ghost:
    "text-muted-foreground enabled:hover:bg-surface-strong enabled:hover:text-foreground focus-visible:ring-focus-ring/30 border border-transparent",
};

const BASE_CLASSES =
  "inline-flex items-center justify-center gap-2 rounded-lg transition focus:outline-hidden focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60";

function buttonClasses(
  variant: ButtonVariant,
  size: ButtonSize,
  extra?: string,
): string {
  return [BASE_CLASSES, SIZE_CLASSES[size], VARIANT_CLASSES[variant], extra]
    .filter(Boolean)
    .join(" ");
}

interface ButtonProps extends Omit<ComponentPropsWithRef<"button">, "type"> {
  size?: ButtonSize;
  variant?: ButtonVariant;
  fullWidth?: boolean;
  type?: "button" | "submit" | "reset";
  children: ReactNode;
}

export default function Button({
  size = "lg",
  variant = "primary",
  fullWidth = false,
  type = "button",
  className,
  children,
  ...rest
}: ButtonProps) {
  const classes = buttonClasses(
    variant,
    size,
    [fullWidth ? "w-full" : "", className ?? ""].filter(Boolean).join(" "),
  );

  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
