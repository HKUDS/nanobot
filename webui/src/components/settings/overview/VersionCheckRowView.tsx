import { useId } from "react";
import { Check, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { SettingsGroup, SettingsRow } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import type { ReleaseStatus, UpdateChannel, UpdateMethod } from "@/lib/api";
import type { VersionResult } from "@/providers/VersionCheckProvider";

export type VersionInfoProps = {
  currentVersion?: string;
  currentCommit?: string | null;
  onRequestUpdate?: () => void;
  hasPendingUpdate?: boolean;
  installationMethod?: UpdateMethod | null;
};
export type VersionCheckState = VersionResult;

export function VersionCheckRowView({
  currentVersion, currentCommit, checking, result, onCheck,
  onRequestUpdate, hasPendingUpdate, installationMethod,
  releaseStatus, canChangeChannel, changingChannel, channelError, onChangeChannel,
}: VersionInfoProps & {
  checking: boolean;
  result: VersionCheckState;
  onCheck: () => void;
  releaseStatus?: ReleaseStatus | null;
  canChangeChannel?: boolean;
  changingChannel?: boolean;
  channelError?: string;
  onChangeChannel?: (channel: UpdateChannel) => Promise<void>;
}) {
  const { t } = useTranslation();
  const previewHelp = useId();
  const previewToggle = useId();
  const available = result?.type === "update" ? result : null;
  const actionClass = "h-auto min-h-9 max-w-full whitespace-normal break-words text-start";
  return (
    <SettingsGroup>
      <SettingsRow title={<>
        <span>{t("settings.about.version")}</span>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-[13px] font-normal leading-5 tabular-nums text-muted-foreground">
          <span className="min-w-0 break-all">
            {currentVersion ? `v${currentVersion}` : "nanobot"}
            {currentCommit && <>
              <span aria-hidden> (</span>
              <a href={`https://github.com/HKUDS/nanobot/commit/${currentCommit}`}
                target="_blank" rel="noopener noreferrer" title={currentCommit}
                className="font-mono hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {currentCommit.slice(0, 7)}
              </a>
              <span aria-hidden>)</span>
            </>}
          </span>
          {available && !checking && <span className="min-w-0 break-all" role="status">
            <span aria-hidden>→ </span><span className="sr-only">{t("settings.about.updateNotice")} </span>
            <span>v{available.latestVersion}</span>
          </span>}
        </div>
        {!checking && available && releaseStatus?.state === "withdrawn" &&
          <p role="alert" className="mt-1 text-[13px] font-normal leading-5 text-destructive">{t("updates.channel.withdrawn")}</p>}
        {available && !checking && !onRequestUpdate &&
          <p className="mt-1 text-[13px] font-normal leading-5 text-muted-foreground">{t("settings.about.updateInstructions")}</p>}
      </>}>
        <div className="settings-version-actions flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {(checking || (result && !available)) && <span role="status" aria-atomic="true" className={`min-w-0 text-[13px] leading-5 [overflow-wrap:anywhere] ${result?.type === "error" && !checking ? "text-destructive" : "text-muted-foreground"}`}>
            {checking ? <span className="inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
              {t("settings.about.checking")}
            </span> : result?.type === "up-to-date" ? <span className="inline-flex items-center gap-1.5">
              <Check className="h-3 w-3 shrink-0" aria-hidden />{t("settings.about.upToDate")}
            </span> : result?.type === "release-status" ? t(`updates.channel.${result.state}`)
              : result?.type === "error" ? result.message : null}
          </span>}
          {hasPendingUpdate && onRequestUpdate ? (
            <Button size="sm" variant="outline" className={actionClass} onClick={onRequestUpdate}>
              {t("settings.about.viewUpdateDetails")}
            </Button>
          ) : checking ? null : available ? <>
            {onRequestUpdate ? <Button size="sm" variant="outline" className={actionClass} onClick={onRequestUpdate} disabled={changingChannel}>
              {installationMethod && installationMethod !== "managed"
                ? t("updates.guide.entry", { method: t(`updates.guide.methods.${installationMethod}`) })
                : t("settings.about.updateNow")}
            </Button> : <Button size="sm" variant="outline" className={actionClass} asChild>
              <a href="https://github.com/HKUDS/nanobot#-install" target="_blank" rel="noopener noreferrer">
                {t("settings.about.installationGuide")}<ExternalLink className="ms-1.5 h-3 w-3 shrink-0" aria-hidden />
              </a>
            </Button>}
            {available.releaseUrl || available.pypiUrl ? (
              <a href={available.releaseUrl || available.pypiUrl} target="_blank" rel="noopener noreferrer"
                className="inline-flex min-h-9 items-center gap-1 rounded-control text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {available.releaseUrl ? t("updates.channel.releaseNotes") : "PyPI"}
                <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
              </a>
            ) : null}
          </> : <Button size="sm" variant="ghost" className={`${actionClass} px-2 text-muted-foreground`} onClick={onCheck} disabled={changingChannel}>
            {result?.type === "error" ? t("common.retry") : result ? t("updates.checkAgain") : t("settings.about.checkForUpdates")}
          </Button>}
        </div>
      </SettingsRow>
      {releaseStatus && onChangeChannel && <div className="border-t border-border/50">
        <SettingsRow title={<>
          <label htmlFor={previewToggle}>{t("updates.channel.receivePreview")}</label>
          <p id={previewHelp} className="mt-1 text-[13px] font-normal leading-5 text-muted-foreground">
            {t("updates.channel.hint")}
            {!canChangeChannel && <span className="mt-2 block">{t("updates.blocked.permission")}</span>}
          </p>
        </>}>
          <ToggleButton id={previewToggle} checked={releaseStatus.channel === "preview"}
            onChange={enabled => { void onChangeChannel(enabled ? "preview" : "stable"); }}
            disabled={!canChangeChannel || changingChannel || checking}
            label={t("updates.channel.receivePreview")} aria-describedby={previewHelp} />
        </SettingsRow>
        <p role="status" className={`settings-list-inset text-[13px] leading-5 ${channelError ? "text-destructive" : "text-muted-foreground"}`}>
          <span className={changingChannel || channelError ? "block pb-3" : undefined}>
          {changingChannel ? t("updates.channel.saving") : channelError}
          </span>
        </p>
      </div>}
    </SettingsGroup>
  );
}
