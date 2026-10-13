import { useEffect, useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

interface ThreadHistoryStatusProps {
  loading: boolean;
  error: string | null;
  pullDistance?: number;
  onRetry: () => void;
}

export function ThreadHistoryStatus({ loading, error, onRetry, pullDistance = 0 }: ThreadHistoryStatusProps) {
  const { t } = useTranslation();
  const [showLoading, setShowLoading] = useState(false);

  useEffect(() => {
    if (!loading) {
      setShowLoading(false);
      return;
    }
    const timer = window.setTimeout(() => setShowLoading(true), 180);
    return () => window.clearTimeout(timer);
  }, [loading]);

  return (
    <div
      className="thread-message-row pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-center"
      style={{ height: 48 + pullDistance }}
    >
      <div role="status" aria-live="polite" aria-atomic="true">
        {(loading && showLoading) || pullDistance > 0 ? (
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-background/95 text-muted-foreground">
            <Loader2
              aria-hidden="true"
              className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`}
              style={!loading ? { transform: `rotate(${pullDistance * 6}deg)`, opacity: Math.min(1, pullDistance / 24) } : undefined}
            />
            {loading ? <span className="sr-only">{t("thread.history.loading")}</span> : null}
          </div>
        ) : !loading && error ? (
          <div className="pointer-events-auto flex items-center gap-1 rounded-control bg-background/95 pl-3 text-xs text-muted-foreground">
            <span>{t("thread.history.error")}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-11 w-11 shrink-0 p-0 sm:h-8 sm:w-8"
              aria-label={t("thread.history.retry")}
              title={t("thread.history.retry")}
              onClick={onRetry}
            >
              <RotateCcw aria-hidden="true" className="h-4 w-4" />
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
