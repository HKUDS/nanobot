import { useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  channelTranslator,
  type ChannelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import { Button } from "@/components/ui/button";
import { enableNanobotFeature } from "@/lib/api";
import type {
  NanobotChannelInstanceInfo,
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
} from "@/lib/types";

import { FeishuConnectFlow } from "./FeishuConnectFlow";

export function FeishuAssistantsPanel({
  token,
  feature,
  showBrandLogos,
  chatAppsDocsUrl,
  onFeaturesUpdate,
}: ChannelPluginPanelProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "feishu");
  const instances = feature.instances?.length
    ? feature.instances
    : [defaultFeishuInstance(feature)];

  return (
    <ChannelInstancesPanel
      token={token}
      feature={feature}
      showBrandLogos={showBrandLogos}
      chatAppsDocsUrl={chatAppsDocsUrl}
      instances={instances}
      onFeaturesUpdate={onFeaturesUpdate}
      customization={{
        countLabel: (count) => feishuAssistantCountLabel(count, tx),
        toggleAriaLabel: (instance) => tx("custom.toggleAssistant", "{{name}} assistant", {
          name: instanceDisplayName(instance),
        }),
        configuredLabel: tx("custom.configured", "Connected"),
        needsSetupLabel: tx("custom.needsSetup", "Needs authorization"),
        renderInstanceSummary: (instance) => (
          maskFeishuAppId(instance.config_values?.["channels.feishu.appId"])
          || tx("custom.noAppId", "No App ID")
        ),
        renderInstanceAction: (instance) => (
          <FeishuInstanceAction
            key={instance.id}
            token={token}
            instance={instance}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ),
        footer: (
          <div className="mt-4 overflow-hidden rounded-[16px] border border-border/70 bg-background px-4 py-4">
            <div className="text-[13px] font-semibold text-foreground">
              {tx("custom.createAnother", "Create another assistant")}
            </div>
            <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
              {tx(
                "custom.createHint",
                "Create a separate Feishu bot for another team, space, or workflow.",
              )}
            </p>
            <FeishuConnectFlow
              token={token}
              instanceId="default"
              mode="create"
              idleLabel={tx("custom.createAssistant", "Create assistant")}
              onFeaturesUpdate={onFeaturesUpdate}
            />
          </div>
        ),
      }}
    />
  );
}

function FeishuInstanceAction({
  token,
  instance,
  onFeaturesUpdate,
}: {
  token: string;
  instance: NanobotChannelInstanceInfo;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "feishu");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!instance.configured) {
    return (
      <FeishuConnectFlow
        token={token}
        instanceId={instance.id}
        mode="replace"
        idleLabel={t("settings.channels.connect", { defaultValue: "Connect" })}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    );
  }

  const reconnect = async () => {
    setBusy(true);
    setError(null);
    try {
      onFeaturesUpdate(
        await enableNanobotFeature(token, "feishu", { instanceId: instance.id }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mt-3 flex justify-end">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
          onClick={() => void reconnect()}
          disabled={busy || !instance.enabled}
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {tx("custom.reconnect", "Reconnect")}
        </Button>
      </div>
      {error ? (
        <div className="mt-3 rounded-[12px] border border-destructive/20 px-3 py-2 text-[12px] leading-5 text-destructive">
          {error}
        </div>
      ) : null}
    </>
  );
}

function defaultFeishuInstance(feature: NanobotFeatureInfo): NanobotChannelInstanceInfo {
  return {
    id: "default",
    name: "nanobot",
    enabled: feature.enabled,
    configured: Boolean(feature.configured),
    config_values: feature.config_values ?? {},
    configured_fields: feature.configured_fields ?? [],
  };
}

function feishuAssistantCountLabel(
  count: number,
  tx: ChannelTranslator,
): string {
  if (count === 0) return tx("custom.countNone", "No assistant connected");
  if (count === 1) return tx("custom.countOne", "1 assistant connected");
  return tx("custom.countMany", "{{count}} assistants connected", { count });
}

function instanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  return instance.display_name?.trim() || instance.name.trim() || instance.id;
}

function maskFeishuAppId(appId: string | undefined): string {
  if (!appId) return "";
  if (appId.length <= 10) return appId;
  return `${appId.slice(0, 7)}...${appId.slice(-4)}`;
}
