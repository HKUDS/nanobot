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
        "inline-flex min-h-8 max-w-full items-center gap-1 overflow-x-auto rounded-full bg-muted/65 p-1 text-[12px] font-medium text-muted-foreground",
        "scrollbar-thin scrollbar-track-transparent",
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
              "shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-muted-foreground transition-colors",
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
