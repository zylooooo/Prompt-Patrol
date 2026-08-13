import {
  buttonClasses,
  type ButtonSize,
  type ButtonVariant,
} from "./button-classes";
import type { ButtonHTMLAttributes, ReactNode } from "react";

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
