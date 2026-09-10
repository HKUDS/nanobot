import { useTranslation } from "react-i18next";

import {
  channelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import type {
  NanobotChannelInstanceInfo,
  NanobotFeatureInfo,
} from "@/lib/types";
import { FeishuConnectFlow } from "./FeishuConnectFlow";

export function FeishuAssistantsPanel({
  token,
  feature,
  showBrandLogos,
  onFeaturesUpdate,
}: ChannelPluginPanelProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "feishu");
  const instances = feature.instances?.length
    ? feature.instances
    : [defaultFeishuInstance(feature)];

  return (
    <ChannelInstancesPanel
      feature={feature}
      showBrandLogos={showBrandLogos}
      instances={instances}
      onFeaturesUpdate={onFeaturesUpdate}
      customization={{
        toggleAriaLabel: (instance) => tx("custom.toggleAssistant", "{{name}} assistant", {
          name: instanceDisplayName(instance),
        }),
        configuredLabel: tx("custom.configured", "Connected"),
        needsSetupLabel: tx("custom.needsSetup", "Needs authorization"),
        renderInstanceSummary: () => null,
        renderInstanceAction: (instance) => instance.configured ? null : (
          <FeishuConnectFlow
            key={instance.id}
            token={token}
            instanceId={instance.id}
            mode="replace"
            idleLabel={t("settings.channels.connect", { defaultValue: "Connect" })}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ),
        footer: (
          <div className="mt-3 overflow-hidden rounded-floating border border-dashed border-border/70 bg-background/60 p-4 sm:flex sm:items-center sm:justify-between sm:gap-4">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-foreground">
                {tx("custom.createAnother", "Create another assistant")}
              </div>
              <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">
                {tx(
                  "custom.createHint",
                  "Create a separate Feishu bot for another team, space, or workflow.",
                )}
              </p>
            </div>
            <div className="shrink-0 [&>div]:mt-0">
              <FeishuConnectFlow
                token={token}
                instanceId="default"
                mode="create"
                idleLabel={tx("custom.createAssistant", "Create assistant")}
                onFeaturesUpdate={onFeaturesUpdate}
              />
            </div>
          </div>
        ),
      }}
    />
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

function instanceDisplayName(instance: NanobotChannelInstanceInfo): string {
  return instance.display_name?.trim() || instance.name.trim() || instance.id;
}
