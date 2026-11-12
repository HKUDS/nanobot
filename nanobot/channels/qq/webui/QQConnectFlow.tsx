import { useTranslation } from "react-i18next";

import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import { channelStatusLabel } from "@/components/settings/channels/ChannelIdentity";

import { QQConnectFlowView, useQQConnectLabels } from "./QQConnectFlowView";

export function QQConnectFlow({
  feature,
  connectRequestId,
  onOpenAdvanced,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const labels = useQQConnectLabels();
  const runtimeLabel = feature.runtime_status === "stopped"
    ? t("settings.channels.runtimeStopped", { defaultValue: "Not running" })
    : channelStatusLabel(feature, (key, fallback) => t(key, { defaultValue: fallback }));
  return (
    <ChannelQrConnectFlow
      channelName="qq"
      connectRequestId={connectRequestId}
      autoStart={!feature.configured}
      forceOnRepeat
      labels={labels}
      onFeaturesUpdate={onFeaturesUpdate}
      renderView={(props) => <QQConnectFlowView {...props}
        configured={feature.configured}
        appId={feature.config_values?.["channels.qq.appId"]}
        runtimeStatus={feature.runtime_status}
        runtimeLabel={feature.runtime_status ? runtimeLabel : undefined}
        onManualSetup={onOpenAdvanced} />}
    />
  );
}
