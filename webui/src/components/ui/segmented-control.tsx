import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface SegmentedControlOption<T extends string> {
  value: T;
  label: ReactNode;
}

interface SegmentedControlProps<T extends string> {
  value: T;
  options: Array<SegmentedControlOption<T>>;
  onChange: (value: T) => void;
  ariaLabel?: string;
  mode?: "buttons" | "tabs";
  className?: string;
  itemClassName?: string;
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  mode = "buttons",
  className,
  itemClassName,
}: SegmentedControlProps<T>) {
  const tabs = mode === "tabs";
  return (
    <div
      role={tabs ? "tablist" : undefined}
      aria-label={ariaLabel}
      className={cn(
        "segmented-control inline-flex min-h-8 max-w-full flex-nowrap items-center gap-1 rounded-full bg-muted/65 p-1 text-[12px] font-medium text-muted-foreground",
        className,
      )}
    >
      {options.map((option) => {
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role={tabs ? "tab" : undefined}
            aria-selected={tabs ? selected : undefined}
            aria-pressed={tabs ? undefined : selected}
            onClick={() => onChange(option.value)}
            className={cn(
              "min-w-0 truncate whitespace-nowrap rounded-full px-2 py-1 text-muted-foreground transition-colors",
              selected ? "bg-background text-foreground" : "hover:text-foreground",
              itemClassName,
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
