import { useId, useState, type ReactNode } from "react";
import { Activity } from "lucide-react";

import { cn } from "@/lib/utils";

interface ThinkingReasoningShellProps {
  active: boolean;
  expanded: boolean;
  contextual?: boolean;
  showHeader?: boolean;
  collapseLabel?: string;
  contentId?: string;
  label: string;
  children: ReactNode;
  hasDetails?: boolean;
  onToggle: () => void;
}

export function ThinkingReasoningShell({
  active,
  expanded,
  contextual = false,
  showHeader = true,
  collapseLabel,
  contentId: providedContentId,
  label,
  children,
  hasDetails = true,
  onToggle,
}: ThinkingReasoningShellProps) {
  const generatedContentId = useId();
  const contentId = providedContentId ?? generatedContentId;
  const [hasExpanded, setHasExpanded] = useState(expanded);
  if (expanded && !hasExpanded) setHasExpanded(true);
  const headerClassName = "touch-target inline-flex h-7 min-w-0 items-center gap-1.5 rounded-md px-1.5";
  const headerContent = (
    <>
      <Activity className={cn("h-3.5 w-3.5 shrink-0", active ? "activity-current" : "text-muted-foreground/65")} strokeWidth={1.5} aria-hidden>
        {active ? <path className="activity-current-trace" pathLength={100} d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2" /> : null}
      </Activity>
      <span
        className={cn(
          "min-w-0 truncate text-[12px] font-normal leading-4 text-muted-foreground/65",
        )}
      >
        {label}
      </span>
    </>
  );
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
      data-contextual-activity={contextual || undefined}
      data-block-context-rail={contextual && showHeader || undefined}
      data-block-context-expanded={contextual && expanded ? true : undefined}
    >
      {showHeader ? <div className="flex min-h-7 items-center gap-1.5">
        {hasDetails ? (
          <button
            type="button"
            data-thread-disclosure=""
            data-contextual-activity-disclosure
            data-contextual-activity-collapse={expanded || undefined}
            className={cn(
              headerClassName,
              "bg-transparent transition-colors hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
            onClick={onToggle}
            aria-expanded={expanded}
            aria-controls={contentId}
            aria-label={expanded && collapseLabel ? `${label}, ${collapseLabel}` : label}
            aria-live={active ? "polite" : undefined}
          >
            {headerContent}
          </button>
        ) : (
          <div
            className={headerClassName}
            role="status"
            aria-label={label}
            aria-live={active ? "polite" : undefined}
          >
            {headerContent}
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
            {expanded ? (
              <span
                data-contextual-activity-guide
                aria-hidden
                className="pointer-events-none absolute inset-y-1 start-[13px] w-px rounded-full bg-border"
              />
            ) : null}
            <div
              data-testid={expanded ? "agent-activity-content" : undefined}
              className="mt-1 flex flex-col gap-0.5 pe-1 ps-6"
            >
              {hasExpanded ? children : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
