import { useEffect, useId, useRef, useState } from "react";
import { Download, Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ChannelFeatureAction } from "@/channel-plugins/types";
import { ToggleButton } from "@/components/ui/toggle-button";
import { HoverHint } from "@/components/ui/hover-hint";
import {
  ChannelLogo,
  ChannelStatusBadge,
  channelStatusLabel,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import { Button } from "@/components/ui/button";
import type { NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHANNEL_ACTION_CLASS = "relative h-7 w-[38px] min-w-0 shrink-0 rounded-full border-border/70 bg-background p-0 after:absolute after:left-1/2 after:top-1/2 after:h-11 after:w-11 after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']";

export function ChannelCatalogRow({
  feature,
  showBrandLogos,
  onSelect,
  actionKey,
  restartRequired = false,
  onAction,
  onRestart,
  isRestarting = false,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  onSelect: (trigger: HTMLButtonElement | null, connect?: boolean) => void;
  actionKey: string | null;
  restartRequired?: boolean;
  onAction: ChannelFeatureAction;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const alwaysEnabled = feature.capabilities?.includes("always_enabled") ?? false;
  const pendingChecked = actionKey === `enable:${feature.name}` ? true
    : actionKey === `disable:${feature.name}` ? false : null;
  const installing = actionKey === `install:${feature.name}`;
  const checked = alwaysEnabled || (pendingChecked ?? feature.enabled);
  const anyActionBusy = Boolean(actionKey);
  const actionsDisabled = restartRequired || isRestarting;
  const showInstallRestartHint = feature.install_supported && actionsDisabled;
  const installButtonRef = useRef<HTMLButtonElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const statusId = useId();
  const failed = feature.runtime_status === "failed";
  const [installHint, setInstallHint] = useState(false);

  useEffect(() => {
    if (!installHint) return;
    const timeout = window.setTimeout(() => setInstallHint(false), 1400);
    return () => window.clearTimeout(timeout);
  }, [installHint]);

  const channelIdentity = (
    <>
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <h3 className="text-[14px] font-semibold leading-5 text-foreground [overflow-wrap:anywhere]">
          {displayName}
        </h3>
        {failed ? (
          <div id={statusId} className="mt-0.5">
            <ChannelStatusBadge status="failed">{channelStatusLabel(feature, tx)}</ChannelStatusBadge>
          </div>
        ) : null}
      </div>
    </>
  );

  return (
    <div className={cn(
      "settings-list-row flex min-w-0 items-center gap-3 py-2.5 transition-colors",
      !alwaysEnabled && "settings-hover",
    )}>
      {alwaysEnabled ? (
        <div className="flex min-w-0 flex-1 select-none items-center gap-3">
          {channelIdentity}
        </div>
      ) : (
        <button
          type="button"
          aria-label={t("settings.channels.selectChannel", {
            name: displayName,
            defaultValue: "View {{name}} settings",
          })}
          aria-haspopup={feature.installed ? "dialog" : undefined}
          aria-describedby={failed ? statusId : undefined}
          disabled={actionsDisabled}
          onClick={(event) => {
            if (feature.installed) {
              onSelect(event.currentTarget);
            } else {
              setInstallHint(true);
              if (event.detail === 0) installButtonRef.current?.focus({ preventScroll: true });
            }
          }}
          className="group flex min-w-0 flex-1 select-none items-center gap-3 rounded-control text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border/80"
        >
          {channelIdentity}
        </button>
      )}
      <div className="flex min-w-11 shrink-0 items-center justify-center gap-3">
        {!feature.installed ? (
          <HoverHint enabled={showInstallRestartHint}
            content={t(isRestarting ? "app.system.restarting" : "settings.channels.restartBeforeInstall")}>
            <span role={showInstallRestartHint ? "group" : undefined}
              tabIndex={showInstallRestartHint ? 0 : undefined}
              aria-label={showInstallRestartHint ? t("settings.channels.installChannel", { name: displayName }) : undefined}
              className="inline-flex rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              <Button ref={installButtonRef} type="button" variant="outline" size="icon"
                className={cn(
                  CHANNEL_ACTION_CLASS,
                  installHint && "border-[#2997FF]/60 bg-[#2997FF]/10 text-[#087FE7] ring-2 ring-[#2997FF]/25 ring-offset-2",
                )}
                disabled={actionsDisabled || anyActionBusy || !feature.install_supported}
                aria-label={t("settings.channels.installChannel", { name: displayName })}
                onClick={() => {
                  setInstallHint(false);
                  onAction("enable", feature.name, { installOnly: true, confirmed: true });
                }}>
                {installing
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  : <Download className="h-3.5 w-3.5" aria-hidden />}
                <span className="sr-only">{tx("settings.channels.install", "Install")}</span>
              </Button>
            </span>
          </HoverHint>
        ) : feature.restart_pending ? (
          <HoverHint content={t("settings.channels.restartRequired")}>
            <Button type="button" variant="outline" size="icon"
              className={CHANNEL_ACTION_CLASS}
              aria-label={t("app.system.restart")}
              aria-busy={isRestarting}
              disabled={isRestarting || anyActionBusy || !onRestart}
              onClick={onRestart}>
              {isRestarting
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
            </Button>
          </HoverHint>
        ) : null}
        {!feature.restart_pending && (feature.installed || feature.enabled) ? (
          <ToggleButton ref={toggleRef} checked={checked}
            label={checked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            disabled={alwaysEnabled || actionsDisabled || anyActionBusy}
            ariaLabel={t("settings.channels.toggleChannel", { name: displayName, defaultValue: "{{name}} channel" })}
            onChange={(enabled) => {
              if (enabled && feature.configured === false) onSelect(toggleRef.current, true);
              else onAction(enabled ? "enable" : "disable", feature.name);
            }} />
        ) : null}
      </div>
    </div>
  );
}
