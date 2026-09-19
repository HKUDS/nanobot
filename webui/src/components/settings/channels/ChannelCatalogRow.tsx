import { useEffect, useRef, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ChannelFeatureAction } from "@/channel-plugins/types";
import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  ChannelLogo,
  ChannelStatusBadge,
  channelStatusLabel,
  channelToggleChecked,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import { Button } from "@/components/ui/button";
import type { NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChannelCatalogRow({
  feature,
  showBrandLogos,
  onSelect,
  actionKey,
  actionsDisabled = false,
  onAction,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  onSelect: (connect?: boolean) => void;
  actionKey: string | null;
  actionsDisabled?: boolean;
  onAction: ChannelFeatureAction;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const alwaysEnabled = feature.capabilities?.includes("always_enabled") ?? false;
  const pendingChecked = actionKey === `enable:${feature.name}` ? true
    : actionKey === `disable:${feature.name}` ? false : null;
  const ownActionBusy = pendingChecked !== null || actionKey === `install:${feature.name}`;
  const checked = alwaysEnabled || (pendingChecked ?? channelToggleChecked(feature));
  const anyActionBusy = Boolean(actionKey);
  const installButtonRef = useRef<HTMLButtonElement | null>(null);
  const [installHint, setInstallHint] = useState(false);

  useEffect(() => {
    if (!installHint) return;
    const timeout = window.setTimeout(() => setInstallHint(false), 1400);
    return () => window.clearTimeout(timeout);
  }, [installHint]);

  const pointToInstall = () => {
    setInstallHint(true);
    installButtonRef.current?.focus();
  };
  const channelIdentity = (
    <>
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
          {displayName}
        </h3>
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
          aria-haspopup="dialog"
          disabled={actionsDisabled}
          onClick={() => feature.installed ? onSelect() : pointToInstall()}
          className="group flex min-w-0 flex-1 select-none items-center gap-3 rounded-control text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border/80"
        >
          {channelIdentity}
        </button>
      )}
      {feature.runtime_status === "failed" ? (
        <div className="min-w-0 shrink truncate">
          <ChannelStatusBadge status={feature.runtime_status}>
            {channelStatusLabel(feature, tx)}
          </ChannelStatusBadge>
        </div>
      ) : null}
      <div className="flex w-16 shrink-0 items-center justify-center">
        {!feature.installed ? (
          <Button ref={installButtonRef} type="button" variant="outline" size="icon"
            className={cn(
              "h-[22px] w-[38px] min-w-0 shrink-0 rounded-full border-border/70 bg-background p-0 shadow-sm settings-hover active:scale-[0.96]",
              installHint && "border-[#2997FF]/60 bg-[#2997FF]/10 text-[#087FE7] ring-2 ring-[#2997FF]/25 ring-offset-2",
            )}
            disabled={actionsDisabled || anyActionBusy || !feature.install_supported}
            aria-label={t("settings.channels.installChannel", { name: displayName })}
            onClick={() => {
              setInstallHint(false);
              onAction("enable", feature.name, { installOnly: true, confirmed: true });
            }}>
            {ownActionBusy
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              : <Download className="h-3.5 w-3.5" aria-hidden />}
            <span className="sr-only">{tx("settings.channels.install", "Install")}</span>
          </Button>
        ) : (
          <ToggleButton checked={checked}
            label={checked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            disabled={alwaysEnabled || actionsDisabled || anyActionBusy}
            ariaLabel={t("settings.channels.toggleChannel", { name: displayName, defaultValue: "{{name}} channel" })}
            onChange={(enabled) => {
              if (enabled && feature.configured === false) onSelect(true);
              else onAction(enabled ? "enable" : "disable", feature.name);
            }} />
        )}
      </div>
    </div>
  );
}
