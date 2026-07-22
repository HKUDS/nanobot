import { ChevronDown } from "lucide-react";
import type { ReactNode, Ref } from "react";

import { cn } from "@/lib/utils";

interface ThinkingReasoningShellProps {
  active: boolean;
  expanded: boolean;
  label: string;
  children: ReactNode;
  viewportRef: Ref<HTMLDivElement>;
  contentRef: Ref<HTMLDivElement>;
  onToggle: () => void;
  onScroll: () => void;
}

export function ThinkingReasoningShell({
  active,
  expanded,
  label,
  children,
  viewportRef,
  contentRef,
  onToggle,
  onScroll,
}: ThinkingReasoningShellProps) {
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
    >
      <button
        type="button"
        className="group inline-flex min-h-5 items-center self-start gap-1.5 bg-transparent p-0"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-label={label}
        aria-live={active ? "polite" : undefined}
      >
        <span
          className={cn(
            "min-w-0 truncate text-[13px] font-medium leading-[18px] text-muted-foreground/70",
            active && "animate-pulse motion-reduce:animate-none",
          )}
        >
          {label}
        </span>
        <ChevronDown
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground/60 transition-[transform,color] duration-200",
            "group-hover:text-muted-foreground motion-reduce:transition-none",
            expanded && "rotate-180",
          )}
          strokeWidth={1.8}
          aria-hidden
        />
      </button>

      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-300 motion-reduce:transition-none",
          expanded
            ? "grid-rows-[1fr] opacity-100"
            : "pointer-events-none grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div
            ref={viewportRef}
            data-testid={expanded ? "agent-activity-scroll" : undefined}
            onScroll={onScroll}
            className="mt-1.5 max-h-[180px] overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            aria-hidden={!expanded}
          >
            <div ref={contentRef} className="flex flex-col gap-0.5">
              {children}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
