import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import type { NanobotFeaturesPayload } from "@/lib/types";

import { FeishuConnectFlowView, useFeishuConnectLabels } from "./FeishuConnectFlowView";

export function FeishuConnectFlow({
  token,
  instanceId = "default",
  mode = "replace",
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: {
  token: string;
  instanceId?: string;
  mode?: "replace" | "create";
  idleLabel?: string;
  connectRequestId?: number;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const labels = useFeishuConnectLabels();
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="feishu"
      startParams={{ domain: "feishu", instance_id: instanceId, mode }}
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      onFeaturesUpdate={onFeaturesUpdate}
      labels={labels}
      renderView={(props) => <FeishuConnectFlowView {...props} />}
    />
  );
}
