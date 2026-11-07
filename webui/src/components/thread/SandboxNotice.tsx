import { ArrowRight, ShieldAlert, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

export type SandboxIssue = "missing" | "path" | "permissions" | "startup";

/** A command needs attention; the conversation itself is still usable. */
export function SandboxNotice({ issue, onOpenSettings, onDismiss }: {
  issue: SandboxIssue;
  onOpenSettings: () => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  return <div role="status" aria-live="polite" aria-atomic="true"
    className="thread-composer-notice mb-2 flex items-start gap-3 rounded-control border border-border/60 bg-muted/40 px-3 py-3 text-caption text-foreground animate-in fade-in-0 slide-in-from-bottom-1 motion-reduce:animate-none">
    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-2">
      <div className="min-w-0 flex-1 basis-64 leading-5">
        <p className="font-medium">{t("settings.sandbox.notice.title")}</p>
        <p className="mt-0.5 break-words text-muted-foreground">{t(`settings.sandbox.notice.${issue}`)}</p>
      </div>
      <Button variant="outline" size="sm" className="shrink-0 gap-1.5 rounded-full" onClick={onOpenSettings}>
        {t("settings.sandbox.notice.openSettings")}<ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </div>
    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 rounded-full text-muted-foreground"
      aria-label={t("common.dismiss")} onClick={onDismiss}><X className="h-3.5 w-3.5" aria-hidden /></Button>
  </div>;
}
