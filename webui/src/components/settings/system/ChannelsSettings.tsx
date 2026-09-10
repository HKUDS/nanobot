import { useRef, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SETTINGS_SEARCH_INPUT_CLASS } from "@/components/settings/shared/SettingsControls";
import type { ChannelFeatureAction } from "@/channel-plugins/types";
import { localizedChannelDisplayName } from "@/components/settings/channels/ChannelIdentity";
import { ChannelHelpMenu } from "@/components/settings/channels/ChannelHelpMenu";
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
  onAction: ChannelFeatureAction;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onDismissStatus: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const [selectedChannelName, setSelectedChannelName] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [connectRequestId, setConnectRequestId] = useState(0);
  const triggerRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const channels = (nanobotFeatures?.features ?? [])
    .filter((feature) => feature.type === "channel" && feature.settings_visible !== false)
    .sort((left, right) => Number(!left.ready) - Number(!right.ready)
      || localizedChannelDisplayName(left, t).localeCompare(localizedChannelDisplayName(right, t)));
  const visibleChannels = channels.filter((feature) =>
    (filter === "all" || feature.enabled)
    && `${feature.name} ${localizedChannelDisplayName(feature, t)}`.toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()));
  const channelGroups = [
    {
      key: "builtin",
      label: t("settings.channels.noInstallNeeded"),
      channels: visibleChannels.filter((feature) => !feature.requires_dependencies),
    },
    {
      key: "dependencies",
      label: t("settings.channels.installNeeded"),
      channels: visibleChannels.filter((feature) => feature.requires_dependencies),
    },
  ].filter((group) => group.channels.length);
  const selectedChannel = channels.find((feature) => feature.name === selectedChannelName);

  return (
    <div className="settings-stack">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
            aria-label={t("settings.channels.search")}
            placeholder={t("settings.channels.search")}
            className={`h-12 ps-11 text-[15px] ${SETTINGS_SEARCH_INPUT_CLASS}`} />
        </div>
        <SegmentedControl value={filter} onChange={setFilter} options={[
          { value: "all", label: t("settings.channels.filterAll") },
          { value: "enabled", label: t("settings.channels.filterEnabled") },
        ]} />
      </div>
      {error && !selectedChannel ? <DismissibleStatusMessage message={error} isError onDismiss={onDismissStatus} /> : null}
      {requiresRestartPending ? (
        <RestartRequiredNotice message={t("settings.channels.restartRequired")}
          onRestart={onRestart} isRestarting={isRestarting} />
      ) : null}
      {loading && !nanobotFeatures ? (
        <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          {t("settings.channels.loading")}
        </div>
      ) : visibleChannels.length ? (
        channelGroups.map((group) => (
        <section key={group.key} aria-labelledby={`channel-group-${group.key}`} className="space-y-2">
          <h2 id={`channel-group-${group.key}`} className="px-4 text-[12px] font-medium text-muted-foreground">{group.label}</h2>
          <SettingsGroup>
          <div className="grid grid-cols-1 gap-x-4 gap-y-1 min-[640px]:grid-cols-2">
          {group.channels.map((feature) => (
            <ChannelCatalogRow key={feature.name} feature={feature} showBrandLogos={showBrandLogos}
              actionKey={actionKey} onAction={onAction}
              onSelect={(connect = false) => {
                triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
                setConnectRequestId(connect ? 1 : 0);
                setSelectedChannelName(feature.name);
              }} />
          ))}
          </div>
          </SettingsGroup>
        </section>
        ))
      ) : (
        <div className="px-3 py-12 text-center text-sm text-muted-foreground">
          {t(channels.length ? "settings.channels.noResults" : "settings.channels.empty")}
        </div>
      )}
      <Dialog open={Boolean(selectedChannel)} onOpenChange={(open) => { if (!open) setSelectedChannelName(null); }}>
        <DialogContent ref={dialogRef} aria-describedby={undefined} className="max-h-[85dvh] w-[min(calc(100vw-2rem),40rem)] max-w-none overflow-hidden p-0 outline-none"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            dialogRef.current?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(event) => { event.preventDefault(); triggerRef.current?.focus(); }}>
          <DialogTitle className="sr-only">{t("settings.nav.channels")}</DialogTitle>
          {selectedChannel ? <ChannelHelpMenu feature={selectedChannel} chatAppsDocsUrl={chatAppsDocsUrl} /> : null}
          <div className="max-h-[85dvh] min-h-0 overflow-y-auto overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {error ? <DismissibleStatusMessage message={error} isError onDismiss={onDismissStatus} /> : null}
            {selectedChannel ? <ChannelSetupPanel token={token} feature={selectedChannel} actionKey={actionKey}
              showBrandLogos={showBrandLogos}
              onAction={onAction} onFeaturesUpdate={onFeaturesUpdate} connectRequestId={connectRequestId} /> : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
