import { useEffect, useRef } from "react";
import { Check, CircleAlert, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SettingsGroup } from "@/components/settings/shared/SettingsControls";
import type { RemoteProfile } from "@/lib/remote-instances";
import "./remote-layout.css";

/** Informational only: installing packages and restarting a host need explicit consent. */
export function HostCompatibilityDialog({ profile, clientVersion, onClose }: {
  profile: RemoteProfile | undefined;
  clientVersion?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  // Radix keeps closed content mounted until its exit animation finishes.
  const lastProfile = useRef(profile);
  useEffect(() => { if (profile) lastProfile.current = profile; }, [profile]);
  const displayedProfile = profile || lastProfile.current;
  const report = displayedProfile?.compatibility;
  const status = report?.status || "unchecked";
  const compatible = status === "compatible";
  return <Dialog open={!!profile} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="remote-dialog max-w-md overflow-y-auto outline-none">
      <DialogHeader className="pr-5 text-left">
        <DialogTitle className="text-balance leading-snug">{t("remote.compatibility.title")}</DialogTitle>
        <DialogDescription className="text-pretty [overflow-wrap:anywhere]">{displayedProfile?.name} · {displayedProfile?.host}</DialogDescription>
      </DialogHeader>
      <SettingsGroup>
        <dl className="space-y-3 px-4 py-3 text-[13px] leading-5">
          {[{ label: t("remote.compatibility.client"), version: report?.client_version || clientVersion },
            { label: t("remote.compatibility.host"), version: report?.host_version }].map(({ label, version }) =>
            <div key={label} className="grid grid-cols-[minmax(0,1fr)_fit-content(45%)] items-baseline gap-x-4">
              <dt className="min-w-0 text-pretty text-muted-foreground">{label}</dt>
              <dd className="min-w-0 text-pretty text-right tabular-nums [overflow-wrap:anywhere]">{version || t("remote.compatibility.unreported")}</dd>
            </div>)}
        </dl>
      </SettingsGroup>
      <div role="status" className="flex items-start gap-2 text-[13px] leading-5">
        {compatible ? <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          : <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
        <div className="min-w-0"><p className="text-pretty font-medium">{t(`remote.compatibility.${status}`)}</p>
          <p className="mt-1 text-pretty text-muted-foreground">{t(`remote.compatibility.${status}Hint`)}</p></div>
      </div>
      {report && !compatible && <details className="text-xs leading-5 text-muted-foreground">
        <summary className="cursor-pointer py-1">{t("remote.compatibility.preparation")}</summary>
        <p className="mt-2 text-pretty">{t(status === "update_client" ? "remote.compatibility.localUpdateHint" : "remote.compatibility.serverUpdateHint")}</p>
      </details>}
      <div className={report && !compatible ? "remote-dialog-actions" : "flex justify-end"}>
        <Button className="remote-action" variant="ghost" onClick={onClose}>{t("common.close")}</Button>
        {report && !compatible && <Button asChild className="remote-action gap-2">
          <a href="https://github.com/HKUDS/nanobot/blob/main/docs/quick-start.md#updating" target="_blank" rel="noopener noreferrer">
            {t("remote.compatibility.guide")}<ExternalLink aria-hidden className="h-3.5 w-3.5" />
          </a>
        </Button>}
      </div>
    </DialogContent>
  </Dialog>;
}
