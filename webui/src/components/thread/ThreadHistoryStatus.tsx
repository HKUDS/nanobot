import { forwardRef, type CSSProperties } from "react";
import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/hover-hint";
import { HISTORY_PULL_LIMIT_PX } from "@/components/thread/thread-history-spring";

interface ThreadHistoryStatusProps {
  loading: boolean;
  error: string | null;
  exhausted?: boolean;
  armed?: boolean;
  pullDistance?: number;
  onRetry: () => void;
}

export const ThreadHistoryStatus = forwardRef<HTMLDivElement, ThreadHistoryStatusProps>(function ThreadHistoryStatus({ loading, error, exhausted = false, armed = false, onRetry, pullDistance }, ref) {
  const { t } = useTranslation();
  const state = loading ? "loading" : error ? "error" : exhausted ? "exhausted" : armed ? "armed" : "available";
  const label = t(`thread.history.${state}`);
  // Blocks adapted from loading.dev (MIT); see THIRD_PARTY_NOTICES.md.
  const line = loading ? <span aria-hidden="true" className="thread-history-blocks">
    {Array.from({ length: 9 }, (_, index) => <span key={index}
      style={{ animationDelay: `${(index % 3 + Math.floor(index / 3) - 5) * 260}ms` }} />)}
  </span> : <svg aria-hidden="true" viewBox="0 0 120 32" className="thread-history-line" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {exhausted ? (
      <path d="M36 12v5h48v-5" />
    ) : (
      <g transform="translate(60 12)"><path className="thread-history-elastic" d="M-18 0Q0 20 18 0" vectorEffect="non-scaling-stroke" /></g>
    )}
  </svg>;

  return (
    <div
      ref={ref}
      className="thread-history-status thread-message-row pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-center"
      data-state={state}
      style={pullDistance === undefined ? undefined : {
        "--history-pull": `${pullDistance}px`,
        "--history-tension": String(pullDistance / HISTORY_PULL_LIMIT_PX),
      } as CSSProperties}
    >
      <div role="status" aria-live="polite" aria-atomic="true">
        {state === "error" ? (
          <div className="pointer-events-auto flex items-center gap-1 text-xs text-muted-foreground">
            <span>{t("thread.history.error")}</span>
            <HoverHint content={t("thread.history.retry")} side="bottom">
              <Button type="button" variant="ghost" size="sm" className="h-11 w-11 shrink-0 p-0 sm:h-8 sm:w-8"
                aria-label={t("thread.history.retry")} onClick={onRetry}>
                <RotateCcw aria-hidden="true" className="h-4 w-4" />
              </Button>
            </HoverHint>
          </div>
        ) : (
          <HoverHint content={label} side="bottom">
            {loading || exhausted ? (
              <div tabIndex={0} aria-label={label} className="thread-history-control pointer-events-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {line}<span className="sr-only">{label}</span>
              </div>
            ) : (
              <button type="button" aria-label={t("thread.loadEarlier")} onClick={onRetry}
                className="thread-history-control pointer-events-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {line}<span className="sr-only">{label}</span>
              </button>
            )}
          </HoverHint>
        )}
      </div>
    </div>
  );
});
