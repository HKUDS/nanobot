import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { PresetProviderIcon } from "@/components/thread/ModelPresetBadge";

/** A live fallback is informative, not a failed message or a changed preset. */
export function ModelFallbackNotice({ model, reauthProvider, reauthProviderLabel, onDismiss, onOpenSettings }: {
  model: string;
  reauthProvider?: string;
  reauthProviderLabel?: string;
  onDismiss: () => void;
  onOpenSettings?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="mx-auto mb-2 flex w-full max-w-[49.5rem] items-center gap-2 rounded-control border border-border/60 bg-muted/40 px-3 py-2 text-xs text-foreground/80 animate-in fade-in-0 slide-in-from-bottom-1 motion-reduce:animate-none"
    >
      <PresetProviderIcon
        provider={reauthProvider}
        label={reauthProviderLabel || model}
        testId="model-fallback-notice-logo"
        isHero={false}
      />
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 leading-5">
        <span className="min-w-0 break-words [overflow-wrap:anywhere]">
          {reauthProviderLabel ? <>
            <span className="font-medium text-foreground">{t("thread.composer.reauthNotice", {
              provider: reauthProviderLabel,
              defaultValue: "{{provider}} authorization expired. Please sign in again.",
            })}</span>
            <span className="ml-1.5 text-muted-foreground">{t("thread.composer.reauthFallback", {
              defaultValue: "A fallback model handled this response.",
            })}</span>
          </> : t("thread.composer.fallbackNotice", {
            model,
            defaultValue: "This response used a fallback model: {{model}}.",
          })}
        </span>
        {onOpenSettings ? (
          <button type="button" onClick={onOpenSettings} className="shrink-0 rounded-sm font-medium text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {reauthProviderLabel
              ? t("thread.composer.reauthSettings", { defaultValue: "Open model settings" })
              : t("thread.composer.checkModelSettings", { defaultValue: "Check model settings" })}
          </button>
        ) : null}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0 rounded-full"
        aria-label={t("common.dismiss")}
        onClick={onDismiss}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </div>
  );
}
