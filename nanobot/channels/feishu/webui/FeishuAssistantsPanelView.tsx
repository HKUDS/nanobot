import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelInstancesPanelView, type ChannelInstancesPanelViewProps } from "@/components/settings/channels/ChannelInstancesPanelView";
import type { NanobotChannelInstanceInfo, NanobotFeatureInfo } from "@/lib/types";

export type FeishuConnectOptions = {
  instanceId?: string;
  mode: "replace" | "create";
  idleLabel: string;
};

export type FeishuAssistantsPanelViewProps = Omit<ChannelInstancesPanelViewProps, "customization"> & {
  renderConnectFlow: (options: FeishuConnectOptions) => ReactNode;
};

export function FeishuAssistantsPanelView({
  feature,
  showBrandLogos,
  instances: providedInstances,
  onToggleInstance,
  onSaveInstance,
  renderConnectFlow,
}: FeishuAssistantsPanelViewProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "feishu");
  const instances = providedInstances ?? (feature.instances?.length
    ? feature.instances
    : [defaultFeishuInstance(feature)]);

  return <ChannelInstancesPanelView
    feature={feature}
    showBrandLogos={showBrandLogos}
    instances={instances}
    onToggleInstance={onToggleInstance}
    onSaveInstance={onSaveInstance}
    customization={{
      toggleAriaLabel: (instance) => tx("custom.toggleAssistant", "{{name}} assistant", {
        name: instanceDisplayName(instance),
      }),
      configuredLabel: tx("custom.configured", "Connected"),
      needsSetupLabel: tx("custom.needsSetup", "Needs authorization"),
      renderInstanceSummary: () => null,
      renderInstanceAction: (instance) => instance.configured ? null : (
        <Fragment key={instance.id}>{renderConnectFlow({
          instanceId: instance.id,
          mode: "replace",
          idleLabel: t("settings.channels.connect", { defaultValue: "Connect" }),
        })}</Fragment>
      ),
      footer: instances.some((instance) => instance.configured) ? (
        <Fragment key={instances.map((instance) => instance.id).join(",")}>{renderConnectFlow({
          mode: "create",
          idleLabel: tx("custom.addAssistant", "Add another assistant"),
        })}</Fragment>
      ) : null,
    }}
  />;
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
