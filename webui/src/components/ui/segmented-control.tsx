import {
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

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
  indicatorClassName?: string;
  animateIndicator?: boolean;
}

interface IndicatorGeometry {
  left: number;
  top: number;
  width: number;
  height: number;
  animate: boolean;
}

function sameGeometry(
  previous: IndicatorGeometry,
  next: Omit<IndicatorGeometry, "animate">,
): boolean {
  return previous.left === next.left
    && previous.top === next.top
    && previous.width === next.width
    && previous.height === next.height;
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  mode = "buttons",
  className,
  itemClassName,
  indicatorClassName,
  animateIndicator = true,
}: SegmentedControlProps<T>) {
  const tabs = mode === "tabs";
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const previousValueRef = useRef<T | undefined>(undefined);
  const [indicator, setIndicator] = useState<IndicatorGeometry | null>(null);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const optionValuesKey = options.map((option) => option.value).join("\u0000");

  useLayoutEffect(() => {
    const measure = (animate: boolean) => {
      const item = itemRefs.current[selectedIndex];
      if (!item) {
        setIndicator(null);
        return;
      }

      const next = {
        left: item.offsetLeft,
        top: item.offsetTop,
        width: item.offsetWidth,
        height: item.offsetHeight,
      };
      setIndicator((previous) => {
        if (previous && sameGeometry(previous, next)) return previous;
        return { ...next, animate: Boolean(previous) && animate };
      });
    };

    const valueChanged = previousValueRef.current !== undefined
      && previousValueRef.current !== value;
    measure(valueChanged);
    previousValueRef.current = value;

    const handleResize = () => measure(false);
    window.addEventListener("resize", handleResize);

    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(handleResize);
    if (observer) {
      if (rootRef.current) observer.observe(rootRef.current);
      itemRefs.current.forEach((item) => {
        if (item) observer.observe(item);
      });
    }

    return () => {
      window.removeEventListener("resize", handleResize);
      observer?.disconnect();
    };
  }, [optionValuesKey, selectedIndex, value]);

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!tabs) return;

    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % options.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + options.length) % options.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = options.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const next = options[nextIndex];
    if (!next) return;
    onChange(next.value);
    itemRefs.current[nextIndex]?.focus();
  };

  return (
    <div
      ref={rootRef}
      role={tabs ? "tablist" : ariaLabel ? "group" : undefined}
      aria-label={ariaLabel}
      className={cn(
        "segmented-control relative isolate inline-flex min-h-8 max-w-full flex-nowrap items-center gap-1 rounded-full bg-muted/65 p-1 text-[12px] font-medium text-muted-foreground",
        className,
      )}
    >
      {indicator ? (
        <span
          aria-hidden
          data-segmented-control-indicator
          data-animate={indicator.animate && animateIndicator ? "true" : "false"}
          className={cn(
            "segmented-control-indicator pointer-events-none absolute left-0 z-0 rounded-full bg-background shadow-[0_1px_2px_hsl(var(--foreground)/0.08)] ring-1 ring-inset ring-border/25",
            indicatorClassName,
          )}
          style={{
            top: indicator.top,
            width: indicator.width,
            height: indicator.height,
            transform: `translate3d(${indicator.left}px, 0, 0)`,
          }}
        />
      ) : null}
      {options.map((option, index) => {
        const selected = value === option.value;
        return (
          <button
            ref={(item) => {
              itemRefs.current[index] = item;
            }}
            key={option.value}
            type="button"
            role={tabs ? "tab" : undefined}
            aria-selected={tabs ? selected : undefined}
            aria-pressed={tabs ? undefined : selected}
            tabIndex={tabs ? (selected || (selectedIndex < 0 && index === 0) ? 0 : -1) : undefined}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className={cn(
              "relative z-[1] min-w-0 truncate whitespace-nowrap rounded-full px-2 py-1 text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selected ? "text-foreground" : "hover:text-foreground",
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
