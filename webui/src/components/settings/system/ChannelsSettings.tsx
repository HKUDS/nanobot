import { useEffect, useRef, useState } from "react";
import { ChevronLeft, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  channelIsRunning,
  channelMatchesFilter,
  channelSearchText,
  localizedChannelDisplayName,
  type ChannelFilter,
} from "@/components/settings/channels/ChannelIdentity";
import { ChannelCatalogRow, ChannelSetupPanel } from "@/components/settings/channels/ChannelSetupPanel";
import {
  DismissibleStatusMessage,
  RestartRequiredNotice,
  SETTINGS_SEARCH_INPUT_CLASS,
} from "@/components/settings/shared/SettingsControls";
import { Input } from "@/components/ui/input";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { NanobotFeaturesPayload } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChannelsSettings({
  token,
  nanobotFeatures,
  loading,
  query,
  actionKey,
  chatAppsDocsUrl,
  showBrandLogos,
  error,
  requiresRestartPending,
  onQueryChange,
  onAction,
  onFeaturesUpdate,
  onDismissStatus,
  onRestart,
  isRestarting,
}: {
  token: string;
  nanobotFeatures: NanobotFeaturesPayload | null;
  loading: boolean;
  query: string;
  actionKey: string | null;
  chatAppsDocsUrl?: string;
  showBrandLogos: boolean;
  error: string | null;
  requiresRestartPending: boolean;
  onQueryChange: (value: string) => void;
  onAction: (action: "enable" | "disable", name: string) => void;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onDismissStatus: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const normalizedQuery = query.trim().toLowerCase();
  const [filter, setFilter] = useState<ChannelFilter>("all");
  const splitLayout = useMediaQuery("(min-width: 1280px)");
  const containerRef = useRef<HTMLDivElement>(null);
  const compactDetailTopRef = useRef<HTMLButtonElement>(null);
  const [compactDetailOpen, setCompactDetailOpen] = useState(false);
  const allChannels = (nanobotFeatures?.features ?? [])
    .filter((feature) => feature.type === "channel")
    .filter((feature) => feature.settings_visible !== false)
    .filter((feature) => !normalizedQuery || channelSearchText(feature, t).includes(normalizedQuery))
    .sort((left, right) => {
      const rank = Number(!left.ready) - Number(!right.ready);
      return rank || localizedChannelDisplayName(left, t).localeCompare(
        localizedChannelDisplayName(right, t),
      );
    });
  const channels = allChannels.filter((feature) => channelMatchesFilter(feature, filter));
  const [selectedChannelName, setSelectedChannelName] = useState<string | null>(null);
  const selectedChannel =
    channels.find((feature) => feature.name === selectedChannelName) ?? channels[0] ?? null;
  const enabledCount = allChannels.filter(channelIsRunning).length;
  const offCount = Math.max(0, allChannels.length - enabledCount);
  const filterOptions: Array<{ value: ChannelFilter; label: string; count: number }> = [
    { value: "all", label: tx("settings.channels.filterAll", "All"), count: allChannels.length },
    { value: "on", label: tx("settings.channels.filterOn", "On"), count: enabledCount },
    { value: "off", label: tx("settings.channels.filterOff", "Off"), count: offCount },
  ];
  const statusMessage = error;
  const statusIsError = true;

  useEffect(() => {
    if (!channels.length) {
      if (selectedChannelName !== null) setSelectedChannelName(null);
      setCompactDetailOpen(false);
      return;
    }
    if (!selectedChannelName || !channels.some((feature) => feature.name === selectedChannelName)) {
      setSelectedChannelName(channels[0].name);
      setCompactDetailOpen(false);
    }
  }, [channels, selectedChannelName]);

  useEffect(() => {
    if (splitLayout) return;
    const resetScroll = () => {
      let node = containerRef.current?.parentElement ?? null;
      while (node) {
        node.scrollTop = 0;
        node = node.parentElement;
      }
      if (compactDetailOpen) {
        compactDetailTopRef.current?.scrollIntoView?.({ block: "start" });
      }
    };
    resetScroll();
    const frame = window.requestAnimationFrame(resetScroll);
    return () => window.cancelAnimationFrame(frame);
  }, [compactDetailOpen, selectedChannelName, splitLayout]);

  const openChannel = (name: string) => {
    setSelectedChannelName(name);
    if (!splitLayout) setCompactDetailOpen(true);
  };

  const setupPanel = selectedChannel ? (
    <ChannelSetupPanel
      token={token}
      feature={selectedChannel}
      actionKey={actionKey}
      chatAppsDocsUrl={chatAppsDocsUrl}
      showBrandLogos={showBrandLogos}
      onAction={onAction}
      onFeaturesUpdate={onFeaturesUpdate}
    />
  ) : null;
  const showingCompactDetail = !splitLayout && compactDetailOpen && selectedChannel !== null;

  return (
    <div
      ref={containerRef}
      className="flex min-h-full flex-1 flex-col xl:min-h-0 xl:overflow-hidden"
    >
      {!showingCompactDetail ? (
        <section className="shrink-0 space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder={tx("settings.channels.searchPlaceholder", "Search channels")}
                className={cn(
                  "h-12 rounded-control pl-11 text-[15px]",
                  SETTINGS_SEARCH_INPUT_CLASS,
                )}
              />
            </div>
            <div className="flex shrink-0 flex-wrap gap-1.5 rounded-control bg-muted/55 p-1">
              {filterOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFilter(option.value)}
                  className={cn(
                    "rounded-control px-3 py-1.5 text-[12px] font-medium transition-colors",
                    filter === option.value
                      ? "bg-background text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {option.label}
                  <span className="ml-1 text-[11px] text-muted-foreground">{option.count}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {statusMessage ? (
        <div className="mt-3 shrink-0">
          <DismissibleStatusMessage
            message={statusMessage}
            isError={statusIsError}
            onDismiss={onDismissStatus}
          />
        </div>
      ) : null}

      {requiresRestartPending ? (
        <div className="mt-3 shrink-0">
          <RestartRequiredNotice
            message={tx("settings.channels.restartRequired", "Restart nanobot to apply updated channel support.")}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </div>
      ) : null}

      <section
        className={cn(
          "flex flex-1 flex-col",
          showingCompactDetail ? "mt-1" : "mt-5",
          splitLayout && "min-h-0 overflow-hidden",
        )}
      >
        {loading && !nanobotFeatures ? (
          <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
            {tx("settings.channels.loading", "Loading Channels...")}
          </div>
        ) : channels.length ? splitLayout ? (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(400px,460px)] gap-6 overflow-hidden">
            <div className="min-h-0 space-y-1 overflow-y-auto overscroll-contain pr-1">
              {channels.map((feature) => (
                <ChannelCatalogRow
                  key={feature.name}
                  feature={feature}
                  selected={selectedChannel?.name === feature.name}
                  showBrandLogos={showBrandLogos}
                  onSelect={() => openChannel(feature.name)}
                />
              ))}
            </div>
            <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">{setupPanel}</div>
          </div>
        ) : showingCompactDetail ? (
          <div className="pb-6">
            <button
              ref={compactDetailTopRef}
              type="button"
              onClick={() => setCompactDetailOpen(false)}
              className="mb-4 inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
              {tx("settings.channels.backToChannels", "All channels")}
            </button>
            {setupPanel}
          </div>
        ) : (
          <div className="space-y-1 pb-6">
            {channels.map((feature) => (
              <ChannelCatalogRow
                key={feature.name}
                feature={feature}
                selected={false}
                showBrandLogos={showBrandLogos}
                onSelect={() => openChannel(feature.name)}
              />
            ))}
          </div>
        ) : (
          <div className="min-h-0 flex-1 px-3 py-12 text-center text-sm text-muted-foreground">
            {tx("settings.channels.empty", "No channels match this filter.")}
          </div>
        )}
      </section>
    </div>
  );
}
