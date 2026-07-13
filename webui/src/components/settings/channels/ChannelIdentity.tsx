import { useMemo, type ReactNode } from "react";
import type { useTranslation } from "react-i18next";

import {
  CHANNEL_PRESENTATION,
  type ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type { NanobotFeatureInfo } from "@/lib/types";

export type ChannelFilter = "all" | "on" | "off";

export function channelSetup(feature: NanobotFeatureInfo): ChannelSetupPresentation {
  return CHANNEL_PRESENTATION[feature.name]?.setup ?? {
    summary:
      "Enable turns on this channel in nanobot, but this integration still needs platform-specific setup before it can receive messages.",
    steps: [
      `Open ~/.nanobot/config.json and find channels.${feature.name}.`,
      "Add the credentials required by that platform, using the channel documentation as the source of truth.",
      "Restart nanobot, then send a small test message from that platform.",
    ],
  };
}

export function ChannelLogo({
  feature,
  showBrandLogos,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
}) {
  const presentation = CHANNEL_PRESENTATION[feature.name];
  const initials = presentation?.initials ?? feature.display_name.slice(0, 2).toUpperCase();
  const color = presentation?.color ?? "#6B7280";
  const Icon = presentation?.icon;
  const logoUrls = useMemo(() => logoFallbackUrls(presentation?.logoUrl), [presentation?.logoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  if (showBrandLogos && logoUrl) {
    return (
      <span
        className="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] border border-border/45 bg-background"
        style={{ boxShadow: `inset 0 0 0 1px ${color}22` }}
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-5.5 w-5.5 max-h-6 max-w-6 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }

  if (Icon) {
    return (
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-border/45 bg-background"
        style={{ color, boxShadow: `inset 0 0 0 1px ${color}18` }}
        aria-hidden
      >
        <Icon className="h-5 w-5" strokeWidth={2.25} />
      </span>
    );
  }

  return (
    <span
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] border border-border/45 bg-background text-[11px] font-bold"
      style={{ color, boxShadow: `inset 0 0 0 1px ${color}18` }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

export function channelDisplayName(feature: NanobotFeatureInfo): string {
  return CHANNEL_PRESENTATION[feature.name]?.displayName ?? feature.display_name;
}

export function channelDescription(feature: NanobotFeatureInfo, t: ReturnType<typeof useTranslation>["t"]): string {
  const fallback =
    CHANNEL_PRESENTATION[feature.name]?.description ??
    `Use nanobot from ${channelDisplayName(feature)}.`;
  return t(`settings.channels.items.${feature.name}.description`, { defaultValue: fallback });
}

export function channelRequirements(feature: NanobotFeatureInfo, t: ReturnType<typeof useTranslation>["t"]): string {
  const fallback =
    CHANNEL_PRESENTATION[feature.name]?.requirements ??
    "Channel credentials and gateway settings";
  return t(`settings.channels.items.${feature.name}.requirements`, { defaultValue: fallback });
}

export function channelMatchesFilter(feature: NanobotFeatureInfo, filter: ChannelFilter): boolean {
  if (filter === "on") return feature.enabled;
  if (filter === "off") return !feature.enabled;
  return true;
}

export function channelStatusLabel(
  feature: NanobotFeatureInfo,
  tx: (key: string, fallback: string) => string,
): string {
  if (feature.enabled) return tx("settings.values.on", "On");
  return tx("settings.values.off", "Off");
}

export function channelSearchText(feature: NanobotFeatureInfo): string {
  return [
    channelDisplayName(feature),
    feature.display_name,
    feature.name,
    feature.status,
    CHANNEL_PRESENTATION[feature.name]?.description,
    CHANNEL_PRESENTATION[feature.name]?.requirements,
  ]
    .join(" ")
    .toLowerCase();
}


export function ChannelStatusBadge({ children }: { children: ReactNode }) {
  return (
    <span className="shrink-0 rounded-full bg-muted/75 px-2 py-0.5 text-[11px] font-medium leading-4 text-muted-foreground">
      {children}
    </span>
  );
}
