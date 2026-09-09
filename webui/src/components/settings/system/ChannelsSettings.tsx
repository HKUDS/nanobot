import { useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { localizedChannelDisplayName } from "@/components/settings/channels/ChannelIdentity";
import { ChannelCatalogRow, ChannelSetupPanel } from "@/components/settings/channels/ChannelSetupPanel";
import { DismissibleStatusMessage, RestartRequiredNotice, SettingsGroup } from "@/components/settings/shared/SettingsControls";
import type { NanobotFeaturesPayload } from "@/lib/types";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

export function ChannelsSettings({
  token, nanobotFeatures, loading, actionKey, chatAppsDocsUrl, showBrandLogos,
  error, requiresRestartPending, onAction, onFeaturesUpdate, onDismissStatus,
  onRestart, isRestarting,
}: {
  token: string;
  nanobotFeatures: NanobotFeaturesPayload | null;
  loading: boolean;
  actionKey: string | null;
  chatAppsDocsUrl?: string;
  showBrandLogos: boolean;
  error: string | null;
  requiresRestartPending: boolean;
  onAction: (action: "enable" | "disable", name: string) => void;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onDismissStatus: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const [selectedChannelName, setSelectedChannelName] = useState<string | null>(null);
  const [connectRequestId, setConnectRequestId] = useState(0);
  const triggerRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const channels = (nanobotFeatures?.features ?? [])
    .filter((feature) => feature.type === "channel" && feature.settings_visible !== false)
    .sort((left, right) => Number(!left.ready) - Number(!right.ready)
      || localizedChannelDisplayName(left, t).localeCompare(localizedChannelDisplayName(right, t)));
  const selectedChannel = channels.find((feature) => feature.name === selectedChannelName);

  return (
    <div className="settings-stack">
      {error ? <DismissibleStatusMessage message={error} isError onDismiss={onDismissStatus} /> : null}
      {requiresRestartPending ? (
        <RestartRequiredNotice message={t("settings.channels.restartRequired")}
          onRestart={onRestart} isRestarting={isRestarting} />
      ) : null}
      {loading && !nanobotFeatures ? (
        <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          {t("settings.channels.loading")}
        </div>
      ) : channels.length ? (
        <SettingsGroup>
          {channels.map((feature) => (
            <ChannelCatalogRow key={feature.name} feature={feature} showBrandLogos={showBrandLogos}
              actionKey={actionKey} onAction={onAction}
              onSelect={(connect = false) => {
                triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                setConnectRequestId(connect ? 1 : 0);
                setSelectedChannelName(feature.name);
              }} />
          ))}
        </SettingsGroup>
      ) : (
        <div className="px-3 py-12 text-center text-sm text-muted-foreground">
          {t("settings.channels.empty")}
        </div>
      )}
      <Dialog open={Boolean(selectedChannel)} onOpenChange={(open) => { if (!open) setSelectedChannelName(null); }}>
        <DialogContent ref={dialogRef} aria-describedby={undefined} className="max-h-[85dvh] w-[min(calc(100vw-2rem),40rem)] max-w-none overflow-y-auto p-0 outline-none"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            dialogRef.current?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(event) => { event.preventDefault(); triggerRef.current?.focus(); }}>
          <DialogTitle className="sr-only">{t("settings.nav.channels")}</DialogTitle>
          {selectedChannel ? <ChannelSetupPanel token={token} feature={selectedChannel} actionKey={actionKey}
            chatAppsDocsUrl={chatAppsDocsUrl} showBrandLogos={showBrandLogos}
            onAction={onAction} onFeaturesUpdate={onFeaturesUpdate} connectRequestId={connectRequestId} /> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
