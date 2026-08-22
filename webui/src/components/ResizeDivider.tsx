import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";

interface ResizeDividerProps {
  ariaLabel: string;
  ariaControls?: string;
  ariaValueMin?: number;
  ariaValueMax?: number;
  ariaValueNow?: number;
  ariaValueText?: string;
  className?: string;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  title?: string;
  testId?: string;
}

export function ResizeDivider({
  ariaLabel,
  ariaControls,
  ariaValueMin,
  ariaValueMax,
  ariaValueNow,
  ariaValueText,
  className,
  onKeyDown,
  onPointerDown,
  title,
  testId,
}: ResizeDividerProps) {
  return (
    <button
      type="button"
      role="separator"
      aria-orientation="vertical"
      aria-label={ariaLabel}
      aria-controls={ariaControls}
      aria-valuemin={ariaValueMin}
      aria-valuemax={ariaValueMax}
      aria-valuenow={ariaValueNow}
      aria-valuetext={ariaValueText}
      data-testid={testId}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
      title={title}
      className={cn(
        "group z-20 flex w-3 cursor-col-resize touch-none items-center justify-center border-x border-border bg-muted/25 text-muted-foreground/75 transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring host-no-drag",
        className,
      )}
    >
      <span className="absolute inset-y-0 w-px bg-border transition-colors group-hover:bg-primary/70" aria-hidden />
      <GripVertical className="relative h-5 w-4 rounded-sm bg-background text-muted-foreground group-hover:text-foreground" aria-hidden />
    </button>
  );
}
