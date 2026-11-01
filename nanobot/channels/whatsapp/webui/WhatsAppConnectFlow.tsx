import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

import { WhatsAppConnectFlowView, useWhatsAppConnectLabels } from "./WhatsAppConnectFlowView";

export function WhatsAppConnectFlow({
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const labels = useWhatsAppConnectLabels();

  return (
    <ChannelQrConnectFlow
      channelName="whatsapp"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      autoStart
      minimalPending
      forceOnRepeat
      labels={labels}
      renderView={(props) => <WhatsAppConnectFlowView {...props} />}
      onFeaturesUpdate={onFeaturesUpdate}
    />
  );
}
