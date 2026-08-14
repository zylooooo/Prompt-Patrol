import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonSize = "xs" | "sm" | "md" | "lg" | "xl" | "icon" | "iconSm";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "destructive"
  | "destructiveOutline"
  | "ghost";

const SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "px-2.5 py-1.5 text-xs rounded-md",
  sm: "px-3 py-2 text-sm rounded-md",
  md: "px-3.5 py-2.5 text-sm rounded-lg",
  lg: "px-4 py-3 text-sm rounded-xl",
  xl: "px-4 py-3 text-xl rounded-xl",
  icon: "h-8 w-8 rounded-lg",
  iconSm: "h-6 w-6 rounded-md",
};

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "font-medium text-primary-foreground bg-primary hover:bg-primary-hover focus:ring-focus-ring/30 border border-transparent",
  secondary:
    "font-medium text-foreground bg-surface hover:bg-surface-muted focus:ring-focus-ring/30 border border-border shadow-xs",
  destructive:
    "font-medium text-danger-foreground bg-danger hover:bg-danger-hover focus:ring-danger/30 border border-transparent",
  destructiveOutline:
    "font-medium text-danger bg-surface hover:bg-danger-soft focus:ring-danger/30 border border-danger/40 shadow-xs",
  ghost:
    "text-muted-foreground hover:bg-surface-strong hover:text-foreground focus:ring-focus-ring/30 border border-transparent",
};

const BASE_CLASSES =
  "inline-flex items-center justify-center gap-2 transition focus:outline-hidden focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60";

function buttonClasses(
  variant: ButtonVariant,
  size: ButtonSize,
  extra?: string,
): string {
  return [BASE_CLASSES, SIZE_CLASSES[size], VARIANT_CLASSES[variant], extra]
    .filter(Boolean)
    .join(" ");
}

interface ButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "type"
> {
  size?: ButtonSize;
  variant?: ButtonVariant;
  fullWidth?: boolean;
  type?: "button" | "submit" | "reset";
  children: ReactNode;
}

export default function Button({
  size = "md",
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
