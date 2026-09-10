import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { ToggleButton } from "@/components/settings/ToggleButton";
import type { ChannelConfigField } from "@/components/settings/channels/catalog";
import {
  CredentialForm,
  channelValidationStatusClass,
  channelValidationStatusIcon,
  channelValuesForSave,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  ChannelLogo,
  ChannelRuntimeError,
  channelSetup,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import {
} from "@/components/settings/channels/ChannelSetupParts";
import { Button } from "@/components/ui/button";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import {
  configureChannel,
  disableNanobotFeature,
  enableNanobotFeature,
} from "@/lib/api";
import { logoFallbackUrls } from "@/lib/provider-brand";
import type {
  NanobotChannelInstanceInfo,
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export type ChannelInstancesPanelCustomization = {
  toggleAriaLabel?: (instance: NanobotChannelInstanceInfo) => string;
  configuredLabel?: string;
  needsSetupLabel?: string;
  renderInstanceSummary?: (instance: NanobotChannelInstanceInfo) => ReactNode;
  renderInstanceAction?: (instance: NanobotChannelInstanceInfo) => ReactNode;
  footer?: ReactNode;
};

export function ChannelInstancesPanel({
  feature,
  showBrandLogos,
  instances: providedInstances,
  onFeaturesUpdate,
  customization = {},
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  chatAppsDocsUrl?: string;
  instances?: NanobotChannelInstanceInfo[];
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  customization?: ChannelInstancesPanelCustomization;
}) {
  const { client } = useClient();
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const instances = providedInstances ?? feature.instances ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyInstanceId, setBusyInstanceId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selected = selectedId ? instances.find((instance) => instance.id === selectedId) : undefined;
  const setup = useMemo(
    () => channelSetup(feature, i18n.resolvedLanguage ?? i18n.language),
    [feature.name, feature.setup, i18n.language, i18n.resolvedLanguage],
  );
  const instanceFields = useMemo(
    () => channelInstanceFields(feature, setup.fields, setup.manualFields),
    [feature, setup.fields, setup.manualFields],
  );
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    defaultChannelFieldValues(instanceFields, selected?.config_values),
  );
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [savingFields, setSavingFields] = useState(false);
  const selectedValuesKey = JSON.stringify(selected?.config_values ?? {});
  const selectedConfiguredFields = useMemo(
    () => new Set(selected?.configured_fields ?? []),
    [selected?.configured_fields],
  );

  useEffect(() => {
    if (selectedId && !instances.some((instance) => instance.id === selectedId)) {
      setSelectedId(null);
    }
  }, [instances, selectedId]);

  useEffect(() => {
    setFieldValues(defaultChannelFieldValues(instanceFields, selected?.config_values));
    setVisibleSecrets({});
  }, [instanceFields, selected?.id, selectedValuesKey]);

  const toggleInstance = async (instance: NanobotChannelInstanceInfo, checked: boolean) => {
    setBusyInstanceId(instance.id);
    setNotice(null);
    try {
      const payload = checked
        ? await enableNanobotFeature(client, feature.name, { instanceId: instance.id })
        : await disableNanobotFeature(client, feature.name, { instanceId: instance.id });
      onFeaturesUpdate(payload);
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setBusyInstanceId(null);
    }
  };

  const saveSelectedInstanceSettings = async () => {
    if (!selected) return;
    setSavingFields(true);
    setNotice(null);
    try {
      const payload = await configureChannel(
        client,
        feature.name,
        channelValuesForSave(instanceFields, fieldValues),
        { enable: selected.enabled, instanceId: selected.id },
      );
      if (payload.nanobot_features) {
        onFeaturesUpdate(payload.nanobot_features);
      }
      setNotice(tx("settings.channels.savedSettings", "Settings saved."));
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSavingFields(false);
    }
  };

  return (
    <aside className="min-h-full rounded-panel bg-settings-surface p-5">
      <div className="flex items-start justify-between gap-3 pr-16">
        <div className="flex min-w-0 max-w-full items-center gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="sr-only">
              {displayName}
            </h3>
          </div>
        </div>
      </div>

      <ChannelRuntimeError message={feature.runtime_error} />

      <div className="mt-5 space-y-3">
        {instances.map((instance) => {
          const expanded = selected?.id === instance.id;
          const instanceSummary = customization.renderInstanceSummary
            ? customization.renderInstanceSummary(instance)
            : instance.id;
          const instanceAction = customization.renderInstanceAction?.(instance);
          const hasInstanceOverview = Boolean(instanceSummary || instanceAction);
          return (
            <article
              key={instance.id}
              className={cn(
                "overflow-hidden rounded-floating transition-colors",
                expanded
                  ? "bg-background"
                  : "bg-background/70 settings-hover",
              )}
            >
              <div className="flex items-center gap-3 px-3 py-3">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  onClick={() =>
                    setSelectedId((current) => (current === instance.id ? null : instance.id))
                  }
                  aria-label={channelInstanceDisplayName(instance)}
                  aria-expanded={expanded}
                >
                  <ChannelInstanceAvatar
                    feature={feature}
                    instance={instance}
                    showBrandLogos={showBrandLogos}
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground">
                    {channelInstanceDisplayName(instance)}
                  </span>
                  <ChannelInstanceStatusBadge
                    instance={instance}
                    configuredLabel={customization.configuredLabel}
                    needsSetupLabel={customization.needsSetupLabel}
                  />
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                      expanded && "rotate-180",
                    )}
                    aria-hidden
                  />
                </button>
                <div className="flex shrink-0 items-center gap-2">
                  {busyInstanceId === instance.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden />
                  ) : null}
                  <ToggleButton
                    checked={instanceToggleChecked(instance)}
                    disabled={
                      busyInstanceId === instance.id
                      || !instance.configured
                    }
                    ariaLabel={customization.toggleAriaLabel?.(instance)
                      ?? t("settings.channels.toggleInstance", {
                        name: channelInstanceDisplayName(instance),
                        defaultValue: "{{name}} instance",
                      })}
                    label={instanceToggleChecked(instance) ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
                    onChange={(checked) => void toggleInstance(instance, checked)}
                  />
                </div>
              </div>

              {expanded ? (
                <div className="space-y-3 px-4 pb-4 pt-1">
                  {hasInstanceOverview ? <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    {instanceSummary ? (
                      <p className="min-w-0 flex-1 truncate font-mono text-[11.5px] leading-6 text-muted-foreground">
                        {instanceSummary}
                      </p>
                    ) : <span className="flex-1" />}
                    {instanceAction}
                  </section> : null}
                  {instanceFields.length ? (
                    <details className={cn(
                      "group text-[12px] leading-5 text-muted-foreground",
                      hasInstanceOverview && "border-t border-border/50 pt-3",
                    )}>
                      <summary className="cursor-pointer list-none text-[12px] font-semibold text-foreground">
                        <span className="inline-flex items-center gap-1.5">
                          {tx("settings.channels.advanced", "Advanced")}
                          <ChevronDown
                            className="h-3.5 w-3.5 transition-transform group-open:rotate-180"
                            aria-hidden
                          />
                        </span>
                      </summary>
                      <form
                        className="mt-3"
                        onSubmit={(event) => {
                          event.preventDefault();
                          void saveSelectedInstanceSettings();
                        }}
                      >
                        <CredentialForm
                          fields={instanceFields}
                          values={fieldValues}
                          configuredFields={selectedConfiguredFields}
                          visibleSecrets={visibleSecrets}
                          onChange={(key, value) =>
                            setFieldValues((current) => ({ ...current, [key]: value }))
                          }
                          onToggleSecret={(key) =>
                            setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }))
                          }
                          compact
                        />
                        <div className="mt-3 flex justify-end">
                          <Button
                            type="submit"
                            size="sm"
                            variant="secondary"
                            className="h-8 rounded-full bg-muted/70 px-3 text-[12px] font-semibold settings-hover"
                            disabled={savingFields}
                          >
                            {savingFields ? (
                              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                            ) : null}
                            {tx("settings.channels.saveSettings", "Save settings")}
                          </Button>
                        </div>
                      </form>
                    </details>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      {customization.footer}

      {notice ? (
        <div className="mt-3 rounded-control border border-destructive/20 px-3 py-2 text-[12px] leading-5 text-destructive">
          {notice}
        </div>
      ) : null}
    </aside>
  );
}

function channelInstanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  const displayName = instance.display_name?.trim();
  if (displayName) return displayName;
  const localName = instance.name?.trim();
  if (localName) return localName;
  return instance.id;
}

function instanceToggleChecked(instance: NanobotChannelInstanceInfo): boolean {
  return instance.runtime_status === "running" || instance.runtime_status === "starting";
}

function ChannelInstanceStatusBadge({
  instance,
  configuredLabel,
  needsSetupLabel,
}: {
  instance: NanobotChannelInstanceInfo;
  configuredLabel?: string;
  needsSetupLabel?: string;
}) {
  const { t } = useTranslation();
  let status = instance.configured ? "configured" : "needs_setup";
  let label = instance.configured
    ? t("settings.channels.instanceConfigured", { defaultValue: "Configured" })
    : needsSetupLabel ?? t("settings.channels.instanceNeedsSetup", { defaultValue: "Needs setup" });
  if (instance.runtime_status === "failed") {
    status = "invalid";
    label = t("settings.channels.runtimeFailed", { defaultValue: "Failed" });
  } else if (instance.runtime_status === "starting") {
    label = t("settings.channels.runtimeStarting", { defaultValue: "Starting" });
  } else if (instance.enabled && instance.runtime_status !== "running") {
    label = t("settings.channels.runtimeStopped", { defaultValue: "Not running" });
  } else if (instance.runtime_status === "running") {
    status = "connected";
    label = configuredLabel
      ?? t("settings.channels.validation.connected", { defaultValue: "Connected" });
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium",
        channelValidationStatusClass(status),
      )}
    >
      {channelValidationStatusIcon(status)}
      {label}
    </span>
  );
}

function ChannelInstanceAvatar({
  feature,
  instance,
  showBrandLogos,
}: {
  feature: NanobotFeatureInfo;
  instance: NanobotChannelInstanceInfo;
  showBrandLogos: boolean;
}) {
  const presentation = channelUiPresentation(feature.name, feature.webui);
  const [avatarFailed, setAvatarFailed] = useState(false);
  const fallbackLogoUrls = useMemo(() => logoFallbackUrls(presentation?.logoUrl), [presentation?.logoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(fallbackLogoUrls);
  const remoteAvatarUrl = !avatarFailed ? instance.avatar_url?.trim() : "";
  const imageUrl = remoteAvatarUrl || (showBrandLogos ? logoUrl : "");
  const Icon = presentation?.icon;
  const initials = presentation?.initials ?? feature.display_name.slice(0, 2).toUpperCase();
  const color = presentation?.color ?? "#3370FF";

  useEffect(() => {
    setAvatarFailed(false);
  }, [instance.avatar_url]);

  return (
    <span
      className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-full bg-background text-[10px] font-bold"
      style={{ color }}
      aria-hidden
    >
      {remoteAvatarUrl ? (
        <img
          src={remoteAvatarUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-full w-full object-cover"
          onError={() => setAvatarFailed(true)}
        />
      ) : imageUrl ? (
        <img
          src={imageUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-6 w-6 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : Icon ? (
        <Icon className="h-5 w-5" strokeWidth={2.25} />
      ) : (
        initials
      )}
    </span>
  );
}

function channelInstanceFields(
  feature: NanobotFeatureInfo,
  fields: ChannelConfigField[] | undefined,
  manualFields: ChannelConfigField[] | undefined,
): ChannelConfigField[] {
  const available = new Map(
    [...(fields ?? []), ...(manualFields ?? [])].map((field) => [field.key, field]),
  );
  if (!feature.setup) return [...available.values()];
  return feature.setup.fields.flatMap((field) => {
    const resolved = available.get(field.key);
    return resolved ? [resolved] : [];
  });
}
