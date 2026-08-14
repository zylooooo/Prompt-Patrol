interface TabsProps<T extends string> {
  tabs: { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
}

export default function Tabs<const T extends string>({
  tabs,
  active,
  onChange,
}: TabsProps<T>) {
  function moveTo(index: number) {
    const target = tabs[(index + tabs.length) % tabs.length];
    onChange(target.id);
    document.getElementById(`tab-${target.id}`)?.focus();
  }

  return (
    <div
      role="tablist"
      onKeyDown={(e) => {
        const idx = tabs.findIndex((tab) => tab.id === active);
        if (e.key === "ArrowRight") {
          e.preventDefault();
          moveTo(idx + 1);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          moveTo(idx - 1);
        } else if (e.key === "Home") {
          e.preventDefault();
          moveTo(0);
        } else if (e.key === "End") {
          e.preventDefault();
          moveTo(tabs.length - 1);
        }
      }}
      className="inline-flex gap-1 rounded-lg border border-border bg-surface-muted p-1"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          id={`tab-${tab.id}`}
          role="tab"
          aria-selected={active === tab.id}
          aria-controls={`panel-${tab.id}`}
          tabIndex={active === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          className={`rounded-md px-4 py-1.5 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 ${
            active === tab.id
              ? "bg-surface font-semibold text-primary shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
