import { forwardRef } from "react";
import { useTranslation } from "react-i18next";

import { HoverHint } from "@/components/ui/hover-hint";
import { cn } from "@/lib/utils";

interface ThreadHistoryStatusProps {
  loading: boolean;
  error: string | null;
  exhausted?: boolean;
  preview?: boolean;
  onRetry: () => void;
  className?: string;
}

export const ThreadHistoryStatus = forwardRef<HTMLDivElement, ThreadHistoryStatusProps>(function ThreadHistoryStatus({ loading, error, exhausted = false, preview = false, onRetry, className }, ref) {
  const { t } = useTranslation();
  const state = loading ? "loading" : error ? "error" : exhausted ? "exhausted" : "ready";
  const hidden = state === "ready" && !preview;
  const label = state === "ready" ? undefined : t(state === "error" ? "thread.history.retryLabel" : `thread.history.${state}`);
  // Blocks adapted from loading.dev (MIT); see THIRD_PARTY_NOTICES.md.
  const blocks = <span aria-hidden="true" className="thread-history-blocks">
    {Array.from({ length: 9 }, (_, index) => <span key={index}
      style={{ animationDelay: `${(index % 3 + Math.floor(index / 3) - 5) * 260}ms` }} />)}
  </span>;

  return (
    <div
      ref={ref}
      className={cn("thread-history-status thread-message-row pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-center", hidden && "invisible", className)}
      aria-hidden={hidden || undefined}
      data-state={state}
    >
      <div role="status" aria-live="polite" aria-atomic="true">
        {state === "exhausted" ? (
          <span className="text-xs">{label}</span>
        ) : state === "ready" ? blocks : (
          <HoverHint content={state === "error" ? error : label} side="bottom">
            {loading ? (
              <div tabIndex={0} aria-label={label} className="thread-history-control pointer-events-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {blocks}<span className="sr-only">{label}</span>
              </div>
            ) : (
              <button type="button" aria-label={label} onClick={onRetry}
                className="thread-history-control pointer-events-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {blocks}<span className="sr-only">{label}</span>
              </button>
            )}
          </HoverHint>
        )}
      </div>
    </div>
  );
});
