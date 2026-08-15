import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

export interface TabOption<T extends string> {
  value: T;
  label: string;
}

const SIZE = {
  sm: { option: "px-3 py-1.5 text-[13px]", gap: "gap-1", indicator: "h-0.5" },
  md: { option: "px-4 py-2.5 text-sm", gap: "gap-2", indicator: "h-0.5" },
  lg: { option: "px-5 py-3 text-base", gap: "gap-3", indicator: "h-[3px]" },
} as const;

export type TabsSize = keyof typeof SIZE;

interface TabsProps<T extends string> {
  tabs: readonly TabOption<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  size?: TabsSize;
}

export default function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  ariaLabel,
  size = "md",
}: TabsProps<T>) {
  const {
    option: optionClass,
    gap: gapClass,
    indicator: indicatorClass,
  } = SIZE[size];

  const groupRef = useRef<HTMLDivElement | null>(null);
  const buttonRefs = useRef<Map<T, HTMLButtonElement>>(new Map());
  const [indicator, setIndicator] = useState({
    transform: "translateX(0px)",
    width: 0,
  });

  useLayoutEffect(() => {
    const update = () => {
      const button = buttonRefs.current.get(value);
      if (!button) return;
      setIndicator({
        transform: `translateX(${button.offsetLeft}px)`,
        width: button.offsetWidth,
      });
    };

    update();

    const observer = new ResizeObserver(update);
    if (groupRef.current) observer.observe(groupRef.current);
    for (const tab of tabs) {
      const button = buttonRefs.current.get(tab.value);
      if (button) observer.observe(button);
    }

    return () => observer.disconnect();
  }, [value, tabs]);

  const moveTo = (index: number) => {
    const target = tabs[((index % tabs.length) + tabs.length) % tabs.length];
    onChange(target.value);
    buttonRefs.current.get(target.value)?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.findIndex((tab) => tab.value === value);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      moveTo(index + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      moveTo(index - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      moveTo(0);
    } else if (e.key === "End") {
      e.preventDefault();
      moveTo(tabs.length - 1);
    }
  };

  return (
    <div
      ref={groupRef}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className="relative overflow-x-auto border-b border-border"
    >
      <div className={`flex ${gapClass}`}>
        {tabs.map((tab) => {
          const isActive = tab.value === value;
          return (
            <button
              key={tab.value}
              ref={(node) => {
                if (node) buttonRefs.current.set(tab.value, node);
                else buttonRefs.current.delete(tab.value);
              }}
              type="button"
              role="tab"
              id={`tab-${tab.value}`}
              aria-selected={isActive}
              aria-controls={`panel-${tab.value}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onChange(tab.value)}
              className={`relative ${optionClass} font-medium transition-colors focus-visible:bg-accent-soft focus-visible:text-foreground ${
                isActive
                  ? "text-accent"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute -bottom-px left-0 ${indicatorClass} rounded-full bg-primary transition-[transform,width] duration-200 ease-out`}
        style={indicator}
      />
    </div>
  );
}
