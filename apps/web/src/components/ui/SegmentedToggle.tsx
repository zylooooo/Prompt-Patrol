import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

export interface SegmentedToggleOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

const SIZE = {
  sm: {
    height: "h-7",
    pad: "p-0.5",
    inset: "top-0.5 bottom-0.5",
    option: "px-2",
    text: "text-xs",
  },
  md: {
    height: "h-9",
    pad: "p-1",
    inset: "top-1 bottom-1",
    option: "px-3",
    text: "text-sm",
  },
  lg: {
    height: "h-11",
    pad: "p-1",
    inset: "top-1 bottom-1",
    option: "px-4",
    text: "text-sm",
  },
} as const;

export type SegmentedToggleSize = keyof typeof SIZE;

interface SegmentedToggleProps<T extends string> {
  value: T;
  options: readonly SegmentedToggleOption<T>[];
  onChange: (next: T) => void;
  ariaLabel: string;
  size?: SegmentedToggleSize;
  fullWidth?: boolean;
  indicatorClassName?: string;
}

export default function SegmentedToggle<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  size = "md",
  fullWidth = false,
  indicatorClassName,
}: SegmentedToggleProps<T>) {
  const {
    height: heightClass,
    pad: padClass,
    inset: indicatorInset,
    option: optionPad,
    text: textSize,
  } = SIZE[size];

  const groupRef = useRef<HTMLDivElement | null>(null);
  const buttonRefs = useRef<Map<T, HTMLButtonElement>>(new Map());
  const [indicatorStyle, setIndicatorStyle] = useState({
    transform: "translateX(0px)",
    width: 0,
  });

  useLayoutEffect(() => {
    const update = () => {
      const button = buttonRefs.current.get(value);
      if (!button) return;
      setIndicatorStyle({
        transform: `translateX(${button.offsetLeft}px)`,
        width: button.offsetWidth,
      });
    };

    update();

    const observer = new ResizeObserver(update);
    if (groupRef.current) observer.observe(groupRef.current);
    for (const option of options) {
      const button = buttonRefs.current.get(option.value);
      if (button) observer.observe(button);
    }

    return () => observer.disconnect();
  }, [value, options]);

  const moveTo = (start: number, step: number) => {
    for (let i = 1; i <= options.length; i += 1) {
      const index =
        (((start + step * i) % options.length) + options.length) %
        options.length;
      const option = options[index];
      if (option.disabled) continue;
      onChange(option.value);
      buttonRefs.current.get(option.value)?.focus();
      return;
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const index = options.findIndex((option) => option.value === value);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      moveTo(index, 1);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      moveTo(index, -1);
    } else if (e.key === "Home") {
      e.preventDefault();
      moveTo(-1, 1);
    } else if (e.key === "End") {
      e.preventDefault();
      moveTo(options.length, -1);
    }
  };

  return (
    <div
      ref={groupRef}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={`relative ${
        fullWidth ? "flex w-full" : "inline-flex max-w-full self-start"
      } ${heightClass} overflow-x-auto rounded-lg border border-border bg-surface ${padClass}`}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute ${indicatorInset} left-0 rounded-md transition-all duration-200 ease-out ${
          indicatorClassName ?? "bg-surface-muted/60 shadow-xs"
        }`}
        style={indicatorStyle}
      />

      {options.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              if (node) buttonRefs.current.set(option.value, node);
              else buttonRefs.current.delete(option.value);
            }}
            type="button"
            role="radio"
            aria-checked={isActive}
            tabIndex={isActive ? 0 : -1}
            disabled={option.disabled}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={`relative z-10 inline-flex items-center rounded-md focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 ${
              fullWidth ? "flex-1 justify-center" : ""
            } ${optionPad} ${textSize} font-medium transition-colors duration-200 ${
              isActive
                ? "text-foreground"
                : "border-none text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:text-disabled-foreground disabled:hover:text-disabled-foreground"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
