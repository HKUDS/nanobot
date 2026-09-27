import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

interface ThreadHistoryStatusProps {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function ThreadHistoryStatus({ loading, error, onRetry }: ThreadHistoryStatusProps) {
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
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex min-h-12 items-center justify-center px-3">
      <div role="status" aria-live="polite" aria-atomic="true">
        {loading && showLoading ? (
          <div className="flex items-center gap-2 rounded-control bg-background/95 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 aria-hidden="true" className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" />
            {t("thread.history.loading")}
          </div>
        ) : !loading && error ? (
          <div className="pointer-events-auto flex items-center gap-1 rounded-control bg-background/95 pl-3 text-xs text-muted-foreground">
            <span>{t("thread.history.error")}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-11 shrink-0 px-3 text-xs sm:h-8"
              onClick={onRetry}
            >
              {t("thread.history.retry")}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
