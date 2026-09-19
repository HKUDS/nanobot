import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

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
  ChannelFieldPresentation,
  ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import { channelValidationMessage } from "@/components/settings/channels/validationMessages";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { normalizeLocale } from "@/i18n/config";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type { ChannelRuntimeStatus, NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export const CHANNEL_SETUP_PANEL_CLASS_NAME =
  "min-h-full rounded-panel bg-settings-surface p-6";

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
    };
  };
  const localizePresentedField = (
    field: ChannelFieldPresentation,
  ): ChannelConfigField => ({
    ...localizeField(field.key),
    section: field.section,
  });
  const presentation: ChannelSetupPresentation = {
    ...definition,
    primaryActionLabel: setupMessages?.primaryAction,
    docsLabel: setupMessages?.docsLabel,
    officialLabel: setupMessages?.officialLabel,
    presetLabel: setupMessages?.presetLabel,
    sectionLabels: setupMessages?.sections,
    fields: definition?.fields?.map(localizePresentedField),
    manualFields: definition?.manualFields?.map(localizePresentedField),
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
      section: copy.section ?? (field.required ? "credentials" : "advanced"),
      secret: field.kind === "secret",
      optional: !field.required,
      kind: field.kind,
      inputType: channelFieldInputType(field.field, field.kind),
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
    requirements: contract.requirements,
    fields: fields.length ? fields : undefined,
    manualFields: manual.length ? manual : undefined,
  };
}

function channelFieldInputType(
  field: string,
  kind: string,
): ChannelConfigField["inputType"] {
  if (kind === "int" || kind === "float") return "number";
  const normalized = field.toLowerCase();
  if (normalized.includes("url")) return "url";
  if (normalized.includes("email") || normalized.includes("address")) return "email";
  if (normalized.includes("phone")) return "tel";
  return undefined;
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
  const presentation = channelUiPresentation(feature.name, feature.webui)
    ?? channelUiPresentation(feature.name);
  const initials = presentation?.initials ?? feature.display_name.slice(0, 2).toUpperCase();
  const Icon = presentation?.icon;
  const logoUrls = useMemo(() => {
    const fallbackUrls = logoFallbackUrls(presentation?.logoFallbackUrl ?? presentation?.logoUrl);
    return presentation?.logoUrl && presentation.logoFallbackUrl
      ? [...new Set([presentation.logoUrl, ...fallbackUrls])]
      : fallbackUrls;
  }, [presentation?.logoUrl, presentation?.logoFallbackUrl]);
  const { logoUrl, logoLoaded, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);
  const showRemoteLogo = showBrandLogos && Boolean(logoUrl);
  const showLoadedLogo = showRemoteLogo && logoLoaded;
  const isLogoTile = presentation?.logoLayout === "tile" && logoUrl === presentation.logoUrl;

  return (
    <span
      data-testid={`channel-logo-${feature.name}`}
      className={cn(
        "relative grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-[9px] text-[11px] font-semibold text-muted-foreground",
        showLoadedLogo ? (isLogoTile ? "bg-transparent" : "bg-white") : "bg-muted",
      )}
      aria-hidden
    >
      <span className={cn(
        "transition-opacity duration-150 motion-reduce:transition-none",
        showLoadedLogo ? "opacity-0" : "opacity-100",
      )}>
        {Icon ? <Icon className="h-6 w-6" strokeWidth={2} /> : initials}
      </span>
      {showRemoteLogo ? <img
        src={logoUrl}
        alt=""
        decoding="async"
        loading="lazy"
        referrerPolicy="no-referrer"
        draggable={false}
        className={cn(
          "absolute object-contain transition-opacity duration-150 motion-reduce:transition-none",
          isLogoTile ? "h-8 w-8" : "h-6 w-6",
          logoLoaded ? "opacity-100" : "opacity-0",
        )}
        onLoad={onLogoLoad}
        onError={onLogoError}
      /> : null}
    </span>
  );
}

function channelDisplayName(feature: NanobotFeatureInfo): string {
  return channelUiPresentation(feature.name, feature.webui)?.displayName ?? feature.display_name;
}

export function localizedChannelDisplayName(
  feature: NanobotFeatureInfo,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const fallback = channelDisplayName(feature);
  return channelTranslator(t, channelUiOwner(feature.name))("displayName", fallback);
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
  if (feature.configured === false) return tx("settings.channels.needsConfig", "Needs setup");
  if (feature.configured === true) return tx("settings.nanobotFeatures.ready", "Ready");
  return tx("settings.values.off", "Off");
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
  const { t } = useTranslation();
  if (!message) return null;
  return (
    <div className={`${className} rounded-control border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12px] leading-5 text-destructive`}>
      {channelValidationMessage(message, t)}
    </div>
  );
}
