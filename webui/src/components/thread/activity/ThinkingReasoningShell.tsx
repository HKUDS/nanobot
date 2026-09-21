import { History } from "lucide-react";
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
  actions?: ReactNode;
  contextPinned?: boolean;
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
  actions,
  contextPinned = false,
  onToggle,
  onScroll,
}: ThinkingReasoningShellProps) {
  const contentId = useId();
  const [hasExpanded, setHasExpanded] = useState(expanded);
  if (expanded && !hasExpanded) setHasExpanded(true);
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
      data-contextual-activity={contextual || undefined}
      data-turn-context-rail={contextual || undefined}
      data-turn-context-expanded={contextual && expanded ? true : undefined}
      data-turn-context-pinned={contextual && contextPinned ? true : undefined}
    >
      <div className="flex min-h-5 items-center gap-1.5">
        {hasDetails ? (
          <button
            type="button"
            data-thread-disclosure=""
            data-contextual-activity-disclosure={contextual || undefined}
            className={cn(
              "group inline-flex h-5 min-w-0 items-center gap-1 bg-transparent p-0",
              "rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={contentId}
            aria-label={label}
            aria-live={active ? "polite" : undefined}
          >
            <History
              className="h-3 w-3 shrink-0 text-muted-foreground/60 transition-colors duration-200 group-hover:text-muted-foreground motion-reduce:transition-none"
              strokeWidth={1.8}
              aria-hidden
            />
            <span
              className={cn(
                "min-w-0 truncate text-[13px] font-medium leading-[18px] text-muted-foreground/70",
                active && "animate-pulse motion-reduce:animate-none",
              )}
            >
              {label}
            </span>
          </button>
        ) : (
          <div
            className="inline-flex h-5 min-w-0 items-center"
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
        {actions ? <div className="min-w-0">{actions}</div> : null}
      </div>

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
