import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode, type Ref } from "react";

import { cn } from "@/lib/utils";

interface ThinkingReasoningShellProps {
  active: boolean;
  expanded: boolean;
  contextual?: boolean;
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
  contextual = false,
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
  const contentId = useId();
  const [hasExpanded, setHasExpanded] = useState(expanded);
  if (expanded && !hasExpanded) setHasExpanded(true);
  return (
    <div
      className={cn(
        "flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none",
        contextual && "completed-activity-block",
      )}
      data-state={active ? "thinking" : "done"}
      data-contextual-activity={contextual || undefined}
    >
      {hasDetails ? (
        <button
          type="button"
          data-thread-disclosure=""
          data-contextual-activity-disclosure={contextual || undefined}
          className={cn(
            "touch-target group -ms-1 inline-flex min-h-7 items-center self-start gap-1 rounded-md px-1",
            "bg-transparent text-muted-foreground/70 transition-[background-color,color,opacity,transform]",
            "duration-150 ease-out hover:bg-muted/55 hover:text-muted-foreground",
            "active:scale-[0.96] motion-reduce:active:scale-100 motion-reduce:transition-none",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={contentId}
          aria-live={active ? "polite" : undefined}
        >
          <span
            className={cn(
              "inline-flex shrink-0 transition-transform duration-150 ease-out",
              "motion-reduce:transition-none",
              expanded ? "rotate-90" : "rtl:rotate-180",
            )}
          >
            <ChevronRight
              className="h-3.5 w-3.5"
              strokeWidth={1.5}
              aria-hidden
            />
          </span>
          <span
            className={cn(
              "min-w-0 truncate text-[12px] font-normal leading-5 tabular-nums",
              active && "animate-pulse motion-reduce:animate-none",
            )}
          >
            {label}
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
          id={contentId}
          {...(!expanded ? { inert: "" } : {})}
          aria-hidden={!expanded}
          className={cn(
            "grid transition-[grid-template-rows,opacity] duration-150 ease-out motion-reduce:transition-none",
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
              className="mt-1 max-h-[180px] overflow-y-auto pe-1 ps-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              <div ref={contentRef} className="flex flex-col gap-0.5">
                {hasExpanded ? children : null}
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
