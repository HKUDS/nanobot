import { useId, useState, type ReactNode, type Ref } from "react";
import { Activity } from "lucide-react";

import { cn } from "@/lib/utils";

interface ThinkingReasoningShellProps {
  active: boolean;
  expanded: boolean;
  contextual?: boolean;
  showHeader?: boolean;
  inlineCollapse?: boolean;
  collapseLabel?: string;
  contentId?: string;
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
  showHeader = true,
  inlineCollapse = false,
  collapseLabel,
  contentId: providedContentId,
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
  const generatedContentId = useId();
  const contentId = providedContentId ?? generatedContentId;
  const [hasExpanded, setHasExpanded] = useState(expanded);
  if (expanded && !hasExpanded) setHasExpanded(true);
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
      data-contextual-activity={contextual || undefined}
      data-block-context-rail={contextual && showHeader || undefined}
      data-block-context-expanded={contextual && expanded ? true : undefined}
    >
      {showHeader ? <div className={cn(
        "flex items-center gap-1.5",
        inlineCollapse ? "min-h-7" : "min-h-5",
      )}>
        {hasDetails ? (
          <button
            type="button"
            data-thread-disclosure=""
            data-contextual-activity-disclosure={contextual || undefined}
            data-contextual-activity-collapse={inlineCollapse || undefined}
            className={cn(
              "touch-target inline-flex min-w-0 items-center bg-transparent",
              inlineCollapse
                ? "h-7 gap-1.5 rounded-md px-1.5 transition-colors hover:bg-muted/60 hover:text-foreground"
                : "h-5 rounded-sm p-0",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={contentId}
            aria-label={inlineCollapse ? collapseLabel ?? label : label}
            aria-live={active ? "polite" : undefined}
          >
            {inlineCollapse ? (
              <Activity className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} aria-hidden />
            ) : null}
            <span
              className={cn(
                "min-w-0 truncate text-[12px] font-normal leading-4 text-muted-foreground/65",
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
                "min-w-0 truncate text-[12px] font-normal leading-4 text-muted-foreground/65",
                active && "animate-pulse motion-reduce:animate-none",
              )}
            >
              {label}
            </span>
          </div>
        )}
      </div> : null}

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
            {inlineCollapse ? (
              <span
                data-contextual-activity-guide
                aria-hidden
                className="pointer-events-none absolute inset-y-1 start-[13px] w-px rounded-full bg-border"
              />
            ) : null}
            <div
              ref={viewportRef}
              data-testid={expanded ? "agent-activity-scroll" : undefined}
              data-fade-top={fadeTop}
              data-fade-bottom={fadeBottom}
              onScroll={onScroll}
              className={cn(
                "mt-1 max-h-[180px] overflow-y-auto pe-1",
                "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
                inlineCollapse ? "ps-6" : "ps-4",
              )}
            >
              <div ref={contentRef} className="flex flex-col gap-0.5">
                {hasExpanded ? children : null}
              </div>
            </div>
            {fadeTop ? (
              <span
                data-testid="activity-scroll-fade-top"
                className="pointer-events-none absolute inset-x-0 top-1 z-10 h-3.5 bg-gradient-to-b from-background to-transparent"
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
