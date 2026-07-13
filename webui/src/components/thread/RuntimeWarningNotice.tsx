import { AlertTriangle, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface RuntimeWarningNoticeProps {
  message: string;
  onDismiss: () => void;
}

/** Dismissible runtime warning kept outside the persisted conversation. */
export function RuntimeWarningNotice({ message, onDismiss }: RuntimeWarningNoticeProps) {
  const { t } = useTranslation();

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "mb-2 flex items-start gap-2 rounded-lg border border-amber-500/30",
        "bg-amber-500/10 px-3 py-2 text-[12px] leading-5 text-amber-800 dark:text-amber-200",
        "animate-in fade-in-0 slide-in-from-bottom-1",
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">
          {t("settings.oauth.expiresSoon", { defaultValue: "OAuth token expires soon" })}
        </p>
        <p className="mt-0.5 text-amber-800/80 dark:text-amber-200/80">{message}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        aria-label={t("common.dismiss")}
        className="h-6 w-6 shrink-0 text-amber-800 hover:bg-amber-500/15 hover:text-amber-900 dark:text-amber-200 dark:hover:text-amber-100"
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
