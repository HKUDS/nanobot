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
  fadeTop: boolean;
  fadeBottom: boolean;
  hasDetails?: boolean;
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
  fadeTop,
  fadeBottom,
  hasDetails = true,
  onToggle,
  onScroll,
}: ThinkingReasoningShellProps) {
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
    >
      {hasDetails ? (
        <button
          type="button"
          data-thread-disclosure=""
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
          <span
            className={cn(
              "inline-flex shrink-0 transition-transform [transition-duration:220ms] ease-out",
              "motion-reduce:transition-none",
              expanded && "rotate-180",
            )}
          >
            <ChevronDown
              className={cn(
                "h-3 w-3 text-muted-foreground/60 transition-colors duration-200",
                "group-hover:text-muted-foreground motion-reduce:transition-none",
              )}
              strokeWidth={1.8}
              aria-hidden
            />
          </span>
        </button>
      ) : (
        <div
          className="inline-flex min-h-5 items-center self-start"
          role="status"
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
        </div>
      )}

      {hasDetails ? (
        <div
          {...(!expanded ? { inert: "" } : {})}
          aria-hidden={!expanded}
          className={cn(
            "grid transition-[grid-template-rows,opacity] [transition-duration:220ms] ease-out motion-reduce:transition-none",
            expanded
              ? "grid-rows-[1fr] opacity-100"
              : "pointer-events-none grid-rows-[0fr] opacity-0",
          )}
        >
          <div className="relative min-h-0 overflow-hidden">
            <div
              ref={viewportRef}
              data-testid={expanded ? "agent-activity-scroll" : undefined}
              data-fade-top={fadeTop}
              data-fade-bottom={fadeBottom}
              onScroll={onScroll}
              className="mt-1.5 max-h-[180px] overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              <div ref={contentRef} className="flex flex-col gap-0.5">
                {children}
              </div>
            </div>
            {fadeTop ? (
              <span
                data-testid="activity-scroll-fade-top"
                className="pointer-events-none absolute inset-x-0 top-1.5 z-10 h-3.5 bg-gradient-to-b from-background to-transparent"
                aria-hidden
              />
            ) : null}
            {fadeBottom ? (
              <span
                data-testid="activity-scroll-fade-bottom"
                className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-3.5 bg-gradient-to-t from-background to-transparent"
                aria-hidden
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
