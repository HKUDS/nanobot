import { useMemo, type ReactNode } from "react";
import type { useTranslation } from "react-i18next";

import {
  channelFieldMessageKey,
  channelTranslator,
} from "@/channel-plugins/i18n";
import { channelLocaleMessages } from "@/channel-plugins/locale-registry";
import {
  channelUiOwner,
  channelUiPresentation,
} from "@/channel-plugins/registry";
import type {
  ChannelConfigField,
  ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { normalizeLocale } from "@/i18n/config";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type { ChannelRuntimeStatus, NanobotFeatureInfo } from "@/lib/types";

export type ChannelFilter = "all" | "on" | "off";

export function channelSetup(
  feature: NanobotFeatureInfo,
  locale = "en",
): ChannelSetupPresentation {
  const definition = channelUiPresentation(feature.name, feature.webui)?.setup;
  const owner = channelUiOwner(feature.name);
  const messages = channelLocaleMessages(owner, normalizeLocale(locale));
  const setupMessages = messages?.setup;
  const localizeField = (key: string): ChannelConfigField => {
    const copy = setupMessages?.fields?.[channelFieldMessageKey(feature.name, key)];
    return {
      key,
      label: copy?.label ?? fieldLabel(key.split(".").at(-1) ?? key),
      placeholder: copy?.placeholder,
      help: copy?.help,
    };
  };
  const presentation: ChannelSetupPresentation = {
    ...definition,
    primaryActionLabel: setupMessages?.primaryAction,
    docsLabel: setupMessages?.docsLabel,
    officialLabel: setupMessages?.officialLabel,
    summary:
      setupMessages?.summary
      ?? "Enable turns on this channel in nanobot, but this integration still needs platform-specific setup before it can receive messages.",
    tryIt: setupMessages?.tryIt,
    steps: setupMessages?.steps ?? [
      `Open ~/.nanobot/config.json and find channels.${feature.name}.`,
      "Add the credentials required by that platform, using the channel documentation as the source of truth.",
      "Restart nanobot, then send a small test message from that platform.",
    ],
    fields: definition?.fields?.map((field) => localizeField(field.key)),
    manualFields: definition?.manualFields?.map((field) => localizeField(field.key)),
    actions: definition?.actions?.map((action) => ({
      ...action,
      label: setupMessages?.actions?.[action.id] ?? fieldLabel(action.id),
    })),
    presets: definition?.presets?.map((preset) => ({
      ...preset,
      label: setupMessages?.presets?.[preset.id] ?? fieldLabel(preset.id),
    })),
  };
  const contract = feature.setup;
  if (!contract) return presentation;

  const primaryFields = new Map(
    (presentation.fields ?? []).map((field) => [field.key, field]),
  );
  const manualFields = new Map(
    (presentation.manualFields ?? []).map((field) => [field.key, field]),
  );
  const authoritativeFields = contract.fields.map((field): ChannelConfigField => {
    const local = primaryFields.get(field.key) ?? manualFields.get(field.key);
    const copy = local ?? localizeField(field.key);
    const choiceLabels = setupMessages?.fields?.[
      channelFieldMessageKey(feature.name, field.key)
    ]?.choices ?? {};
    const choices = field.kind === "bool" ? ["true", "false"] : field.choices;
    return {
      ...copy,
      key: field.key,
      label: copy.label,
      secret: field.kind === "secret",
      optional: !field.required,
      inputType: field.kind === "int" ? "number" : undefined,
      defaultValue: field.default_value,
      options:
        field.kind === "enum" || field.kind === "bool"
          ? choices.map((choice) => ({
              value: choice,
              label: choiceLabels[choice] ?? fieldLabel(choice),
            }))
          : undefined,
    };
  });
  const manualKeys = new Set(manualFields.keys());
  const fields = authoritativeFields.filter((field) => !manualKeys.has(field.key));
  const manual = authoritativeFields.filter((field) => manualKeys.has(field.key));

  return {
    ...presentation,
    officialUrl: contract.official_url,
    officialLabel:
      presentation.officialLabel
      ?? (contract.official_url ? "Open official setup" : undefined),
    fields: fields.length ? fields : undefined,
    manualFields: manual.length ? manual : undefined,
  };
}

function fieldLabel(value: string): string {
  const spaced = value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : value;
}

export function ChannelLogo({
  feature,
  showBrandLogos,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
}) {
  const presentation = channelUiPresentation(feature.name, feature.webui);
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
  return channelUiPresentation(feature.name, feature.webui)?.displayName ?? feature.display_name;
}

export function localizedChannelDisplayName(
  feature: NanobotFeatureInfo,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const fallback = channelDisplayName(feature);
  return channelTranslator(t, channelUiOwner(feature.name))("displayName", fallback);
}

export function channelDescription(feature: NanobotFeatureInfo, t: ReturnType<typeof useTranslation>["t"]): string {
  const fallback =
    `Use nanobot from ${channelDisplayName(feature)}.`;
  return channelTranslator(t, channelUiOwner(feature.name))("description", fallback);
}

export function channelRequirements(feature: NanobotFeatureInfo, t: ReturnType<typeof useTranslation>["t"]): string {
  const fallback =
    "Channel credentials and gateway settings";
  return channelTranslator(t, channelUiOwner(feature.name))("requirements", fallback);
}

export function channelMatchesFilter(feature: NanobotFeatureInfo, filter: ChannelFilter): boolean {
  if (filter === "on") return channelIsRunning(feature);
  if (filter === "off") return !channelIsRunning(feature);
  return true;
}

export function channelIsRunning(feature: NanobotFeatureInfo): boolean {
  return feature.runtime_status === "running";
}

export function channelToggleChecked(feature: NanobotFeatureInfo): boolean {
  return feature.runtime_status === "running" || feature.runtime_status === "starting";
}

export function channelStatusLabel(
  feature: NanobotFeatureInfo,
  tx: (key: string, fallback: string) => string,
): string {
  if (feature.runtime_status === "failed") {
    return tx("settings.channels.runtimeFailed", "Failed");
  }
  if (feature.runtime_status === "starting") {
    return tx("settings.channels.runtimeStarting", "Starting");
  }
  if (channelIsRunning(feature)) return tx("settings.values.on", "On");
  if (feature.enabled) return tx("settings.channels.runtimeStopped", "Not running");
  return tx("settings.values.off", "Off");
}

export function channelSearchText(
  feature: NanobotFeatureInfo,
  t?: ReturnType<typeof useTranslation>["t"],
): string {
  return [
    t ? localizedChannelDisplayName(feature, t) : undefined,
    channelDisplayName(feature),
    feature.display_name,
    feature.name,
    feature.status,
    t ? channelDescription(feature, t) : undefined,
    t ? channelRequirements(feature, t) : undefined,
  ]
    .join(" ")
    .toLowerCase();
}


export function ChannelStatusBadge({
  children,
  status,
}: {
  children: ReactNode;
  status?: ChannelRuntimeStatus;
}) {
  return (
    <span className={[
      "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4",
      status === "failed"
        ? "bg-destructive/10 text-destructive"
        : status === "running"
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-200"
          : "bg-muted/75 text-muted-foreground",
    ].join(" ")}>
      {children}
    </span>
  );
}

export function ChannelRuntimeError({
  message,
  className = "mt-3",
}: {
  message?: string;
  className?: string;
}) {
  if (!message) return null;
  return (
    <div className={`${className} rounded-[12px] border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] leading-5 text-destructive`}>
      {message}
    </div>
  );
}
