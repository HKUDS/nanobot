import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  CHANNEL_PRESENTATION,
  type ChannelConfigField,
} from "@/components/settings/channels/catalog";
import {
  CredentialForm,
  channelValidationStatusClass,
  channelValidationStatusIcon,
  channelValuesForSave,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  ChannelLogo,
  ChannelStatusBadge,
  channelDisplayName,
  channelSetup,
  channelStatusLabel,
} from "@/components/settings/channels/ChannelIdentity";
import { FeishuConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import {
  ChannelGuideLink,
  ChannelSetupSteps,
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

export function FeishuAssistantsPanel({
  token,
  feature,
  showBrandLogos,
  chatAppsDocsUrl,
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  chatAppsDocsUrl?: string;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const instances = feishuFeatureInstances(feature);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyInstanceId, setBusyInstanceId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selected = selectedId ? instances.find((instance) => instance.id === selectedId) : undefined;
  const setup = channelSetup(feature);
  const manualFields = setup.manualFields ?? [];
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    feishuInstanceFieldValues(manualFields, selected),
  );
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [savingFields, setSavingFields] = useState(false);
  const connectedAssistantCount = instances.filter((instance) => instance.configured).length;

  useEffect(() => {
    if (selectedId && !instances.some((instance) => instance.id === selectedId)) {
      setSelectedId(null);
    }
  }, [instances, selectedId]);

  useEffect(() => {
    setFieldValues(feishuInstanceFieldValues(manualFields, selected));
    setVisibleSecrets({});
  }, [
    manualFields,
    selected?.allow_from,
    selected?.app_id,
    selected?.domain,
    selected?.group_policy,
    selected?.id,
  ]);

  const toggleInstance = async (instance: NanobotChannelInstanceInfo, checked: boolean) => {
    setBusyInstanceId(instance.id);
    setNotice(null);
    try {
      const payload = checked
        ? await enableNanobotFeature(token, "feishu", { instanceId: instance.id })
        : await disableNanobotFeature(token, "feishu", { instanceId: instance.id });
      onFeaturesUpdate(payload);
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setBusyInstanceId(null);
    }
  };

  const reconnectInstance = async (instance: NanobotChannelInstanceInfo) => {
    setBusyInstanceId(instance.id);
    setNotice(null);
    try {
      const payload = await enableNanobotFeature(token, "feishu", { instanceId: instance.id });
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
        token,
        "feishu",
        channelValuesForSave(manualFields, fieldValues),
        { enable: selected.enabled, instanceId: selected.id },
      );
      if (payload.nanobot_features) {
        onFeaturesUpdate(payload.nanobot_features);
      }
      setNotice(tx("settings.channels.savedSettings", "Saved settings."));
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSavingFields(false);
    }
  };

  return (
    <aside className="min-h-full rounded-[20px] border border-border/80 bg-background p-5 shadow-none">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[18px] font-semibold leading-6 text-foreground">
              {channelDisplayName(feature)}
            </h3>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {feishuAssistantCountLabel(connectedAssistantCount, tx)}
            </p>
          </div>
        </div>
        <ChannelStatusBadge>{channelStatusLabel(feature, tx)}</ChannelStatusBadge>
      </div>

      <div className="mt-5 space-y-3">
        {instances.map((instance) => {
          const expanded = selected?.id === instance.id;
          return (
            <article
              key={instance.id}
              className={cn(
                "overflow-hidden rounded-[18px] border transition-colors",
                expanded
                  ? "border-border/75 bg-card/95 shadow-sm"
                  : "border-border/55 bg-background hover:border-border/75 hover:bg-muted/15",
              )}
            >
              <div className="flex items-center gap-3 px-3 py-3">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  onClick={() =>
                    setSelectedId((current) => (current === instance.id ? null : instance.id))
                  }
                  aria-expanded={expanded}
                >
                  <FeishuAssistantAvatar
                    feature={feature}
                    instance={instance}
                    showBrandLogos={showBrandLogos}
                    size="lg"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground">
                    {feishuInstanceDisplayName(instance)}
                  </span>
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
                    checked={instance.enabled}
                    disabled={busyInstanceId === instance.id || !instance.configured}
                    ariaLabel={t("settings.channels.toggleFeishuAssistant", {
                      name: feishuInstanceDisplayName(instance),
                      defaultValue: "{{name}} assistant",
                    })}
                    label={instance.enabled ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
                    onChange={(checked) => void toggleInstance(instance, checked)}
                  />
                </div>
              </div>

              {expanded ? (
                <div className="border-t border-border/60">
                  <section className="px-4 py-4">
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <p className="min-w-0 flex-1 truncate font-mono text-[11.5px] leading-6 text-muted-foreground">
                        {maskFeishuAppId(instance.app_id) || tx("settings.channels.noAppId", "No App ID")}
                      </p>
                      <FeishuAssistantConnectionBadge instance={instance} />
                    </div>
                    {instance.configured ? (
                      <div className="mt-3 flex justify-end">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
                          onClick={() => void reconnectInstance(instance)}
                          disabled={busyInstanceId === instance.id || !instance.enabled}
                        >
                          {busyInstanceId === instance.id ? (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                          ) : (
                            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                          )}
                          {tx("settings.channels.reconnectAssistant", "Reconnect")}
                        </Button>
                      </div>
                    ) : (
                      <FeishuConnectFlow
                        key={`connect-${instance.id}`}
                        token={token}
                        instanceId={instance.id}
                        mode="replace"
                        idleLabel={tx("settings.channels.connect", "Connect")}
                        onFeaturesUpdate={onFeaturesUpdate}
                      />
                    )}
                  </section>
                  <ChannelSetupSteps
                    featureName={feature.name}
                    steps={setup.steps}
                    action={
                      <ChannelGuideLink
                        feature={feature}
                        setup={setup}
                        chatAppsDocsUrl={chatAppsDocsUrl}
                        compact
                      />
                    }
                  />
                  {manualFields.length ? (
                    <details className="group border-t border-border/60 px-4 py-3 text-[12px] leading-5 text-muted-foreground">
                      <summary className="cursor-pointer list-none text-[12px] font-semibold text-foreground">
                        <span className="inline-flex items-center gap-1.5">
                          {tx("settings.channels.advanced", "Advanced")}
                          <ChevronDown
                            className="h-3.5 w-3.5 transition-transform group-open:rotate-180"
                            aria-hidden
                          />
                        </span>
                      </summary>
                      <div className="mt-3">
                        <CredentialForm
                          fields={manualFields}
                          values={fieldValues}
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
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
                            onClick={() => void saveSelectedInstanceSettings()}
                            disabled={savingFields}
                          >
                            {savingFields ? (
                              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                            ) : null}
                            {tx("settings.channels.saveSettings", "Save settings")}
                          </Button>
                        </div>
                      </div>
                    </details>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      <div className="mt-4 overflow-hidden rounded-[16px] border border-border/70 bg-background px-4 py-4">
        <div className="text-[13px] font-semibold text-foreground">
          {tx("settings.channels.createFeishuAssistant", "Create another assistant")}
        </div>
        <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
          {tx(
            "settings.channels.createFeishuAssistantHint",
            "Create a separate Feishu bot for another team, space, or workflow.",
          )}
        </p>
        <FeishuConnectFlow
          key="create-feishu-assistant"
          token={token}
          instanceId="default"
          mode="create"
          idleLabel={tx("settings.channels.createAssistant", "Create assistant")}
          onFeaturesUpdate={onFeaturesUpdate}
        />
      </div>

      {notice ? (
        <div className="mt-3 rounded-[12px] border border-destructive/20 px-3 py-2 text-[12px] leading-5 text-destructive">
          {notice}
        </div>
      ) : null}
    </aside>
  );
}

function feishuFeatureInstances(feature: NanobotFeatureInfo): NanobotChannelInstanceInfo[] {
  if (feature.instances?.length) return feature.instances;
  return [{
    id: "default",
    runtime_name: "feishu",
    name: "nanobot",
    domain: "feishu",
    enabled: feature.enabled,
    configured: Boolean(feature.configured),
    app_id: "",
  }];
}

function feishuAssistantCountLabel(
  count: number,
  tx: (key: string, fallback: string) => string,
): string {
  if (count === 0) {
    return tx("settings.channels.noFeishuAssistants", "No assistant connected");
  }
  if (count === 1) {
    return tx("settings.channels.oneFeishuAssistant", "1 assistant connected");
  }
  return tx("settings.channels.manyFeishuAssistants", `${count} assistants connected`);
}

function feishuInstanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  const displayName = instance.display_name?.trim();
  if (displayName) return displayName;
  const localName = instance.name?.trim();
  if (localName) return localName;
  return instance.id === "default" ? "nanobot" : "nanobot";
}

function FeishuAssistantConnectionBadge({ instance }: { instance: NanobotChannelInstanceInfo }) {
  const { t } = useTranslation();
  const status = instance.configured ? "connected" : "needs_setup";
  const label = instance.configured
    ? t("settings.channels.feishuConfigured", { defaultValue: "Connected" })
    : t("settings.channels.feishuNotConfigured", { defaultValue: "Needs authorization" });
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

function FeishuAssistantAvatar({
  feature,
  instance,
  showBrandLogos,
  size,
}: {
  feature: NanobotFeatureInfo;
  instance: NanobotChannelInstanceInfo;
  showBrandLogos: boolean;
  size: "sm" | "lg";
}) {
  const presentation = CHANNEL_PRESENTATION[feature.name];
  const [avatarFailed, setAvatarFailed] = useState(false);
  const fallbackLogoUrls = useMemo(() => logoFallbackUrls(presentation?.logoUrl), [presentation?.logoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(fallbackLogoUrls);
  const remoteAvatarUrl = !avatarFailed ? instance.avatar_url?.trim() : "";
  const imageUrl = remoteAvatarUrl || (showBrandLogos ? logoUrl : "");
  const Icon = presentation?.icon;
  const initials = presentation?.initials ?? feature.display_name.slice(0, 2).toUpperCase();
  const color = presentation?.color ?? "#3370FF";
  const frameClass = size === "lg" ? "h-11 w-11" : "h-9 w-9";
  const fallbackImageClass = size === "lg" ? "h-6 w-6" : "h-5 w-5";
  const iconClass = size === "lg" ? "h-5 w-5" : "h-4 w-4";

  useEffect(() => {
    setAvatarFailed(false);
  }, [instance.avatar_url]);

  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center overflow-hidden rounded-full border border-border/45 bg-background text-[10px] font-bold",
        frameClass,
      )}
      style={{ color, boxShadow: `inset 0 0 0 1px ${color}18` }}
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
          className={cn("object-contain", fallbackImageClass)}
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : Icon ? (
        <Icon className={iconClass} strokeWidth={2.25} />
      ) : (
        initials
      )}
    </span>
  );
}

function maskFeishuAppId(appId: string | undefined): string {
  if (!appId) return "";
  if (appId.length <= 10) return appId;
  return `${appId.slice(0, 7)}...${appId.slice(-4)}`;
}

function feishuInstanceFieldValues(
  fields: ChannelConfigField[],
  instance: NanobotChannelInstanceInfo | undefined,
): Record<string, string> {
  const values = defaultChannelFieldValues(fields);
  if (!instance) return values;
  values["channels.feishu.appId"] = instance.app_id ?? "";
  values["channels.feishu.appSecret"] = "";
  values["channels.feishu.domain"] = instance.domain ?? values["channels.feishu.domain"] ?? "feishu";
  values["channels.feishu.groupPolicy"] =
    instance.group_policy ?? values["channels.feishu.groupPolicy"] ?? "mention";
  values["channels.feishu.allowFrom"] = (instance.allow_from ?? []).join(", ");
  return values;
}
