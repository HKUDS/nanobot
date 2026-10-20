import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

import { QQConnectFlowView, useQQConnectLabels } from "./QQConnectFlowView";

export function QQConnectFlow({
  token,
  feature,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const labels = useQQConnectLabels();
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="qq"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      autoStart={!feature.configured}
      forceOnRepeat
      labels={labels}
      onFeaturesUpdate={onFeaturesUpdate}
      renderView={(props) => <QQConnectFlowView {...props} configured={feature.configured} />}
    />
  );
}
