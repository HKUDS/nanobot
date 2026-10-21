import { useId } from "react";
import { ArrowUpCircle, Check, ExternalLink, Loader2 } from "lucide-react";
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
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <SettingsGroup>
      <SettingsRow title={<>
        <span>
          {tx("settings.about.version", "Version")}
        </span>
        <div className="mt-1 break-all text-[13px] font-normal leading-5 tabular-nums text-muted-foreground">
          {currentVersion ? `v${currentVersion}` : "nanobot"}
          {currentCommit && (
            <>
              <span aria-hidden> (</span>
              <a href={`https://github.com/HKUDS/nanobot/commit/${currentCommit}`}
                target="_blank" rel="noopener noreferrer" title={currentCommit}
                className="font-mono hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {currentCommit.slice(0, 7)}
              </a>
              <span aria-hidden>)</span>
            </>
          )}
        </div>
      </>}>
        <Button
          size="sm"
          variant="outline"
          onClick={onCheck}
          disabled={checking || changingChannel}
          aria-busy={checking}
        >
          {checking ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
          ) : (
            <ArrowUpCircle className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {checking
            ? tx("settings.about.checking", "Checking...")
            : tx("settings.about.checkForUpdates", "Check for updates")}
        </Button>
      </SettingsRow>
      <div role="status" aria-live="polite" aria-atomic="true" className="settings-list-inset text-[13px] leading-5">
          {checking ? <span className="sr-only">{tx("settings.about.checking", "Checking...")}</span> : result?.type === "up-to-date" ? (
            <span className="inline-flex items-center gap-1.5 pb-3 text-muted-foreground">
              <Check className="h-3 w-3" aria-hidden />
              {tx("settings.about.upToDate", "You're up to date")}
            </span>
          ) : result?.type === "release-status" ? <span className="block pb-3 text-muted-foreground">{t(`updates.channel.${result.state}`)}</span>
            : result?.type === "error" ? <span className="block break-words pb-3 text-destructive">{result.message}</span> : null}
      </div>
        {!checking && releaseStatus?.state === "withdrawn" && result?.type === "update" &&
          <p role="alert" className="settings-list-inset pb-3 text-[13px] leading-5 text-destructive">{t("updates.channel.withdrawn")}</p>}
        {hasPendingUpdate && onRequestUpdate ? (
          <div className="settings-list-inset pb-4">
          <Button size="sm" variant="outline" onClick={onRequestUpdate}>
            {t("settings.about.viewUpdateDetails")}
          </Button>
          </div>
        ) : result?.type === "update" ? (
          <div className="settings-list-inset border-t border-border/50 py-3 text-start">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1" role="status">
                <span className="text-[14px] font-medium leading-5">
                  {t("settings.about.updateNotice")}
                </span>
                <span className="break-all text-[13px] leading-5 tabular-nums text-muted-foreground">v{result.latestVersion}</span>
              </div>
              {onRequestUpdate ? <Button size="sm" variant="outline" className="h-auto min-h-9 max-w-full whitespace-normal break-words text-start" onClick={onRequestUpdate}>
                {installationMethod && installationMethod !== "managed"
                  ? t("updates.guide.entry", { method: t(`updates.guide.methods.${installationMethod}`) })
                  : t("settings.about.updateNow")}</Button> :
                <Button size="sm" variant="outline" className="h-auto min-h-9 max-w-full whitespace-normal text-start" asChild><a href="https://github.com/HKUDS/nanobot#-install"
                  target="_blank" rel="noopener noreferrer">{t("settings.about.installationGuide")}<ExternalLink className="ms-1.5 h-3 w-3 shrink-0" aria-hidden /></a></Button>}
              {result.releaseUrl || result.pypiUrl ? (
                <a href={result.releaseUrl || result.pypiUrl} target="_blank" rel="noopener noreferrer"
                  className="inline-flex min-h-9 items-center gap-1 rounded-control text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {result.releaseUrl ? t("updates.channel.releaseNotes") : "PyPI"}
                  <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                </a>
              ) : null}
            </div>
            {!onRequestUpdate && <p className="mt-2 text-[13px] leading-5 text-muted-foreground">{t("settings.about.updateInstructions")}</p>}
          </div>
        ) : null}
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
