import { useTranslation } from "react-i18next";

import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import type { NanobotFeaturesPayload } from "@/lib/types";

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
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="feishu"
      startOptions={{ domain: "feishu", instanceId, mode }}
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      onFeaturesUpdate={onFeaturesUpdate}
      labels={{
        qrAlt: tx("settings.channels.feishuQrAlt", "Feishu connection QR code"),
        scanTitle: tx("settings.channels.feishuScanTitle", "Scan with Feishu"),
        scanDescription: tx(
          "settings.channels.feishuScanDescription",
          "Use Feishu or Lark on your phone to scan this code. nanobot will finish setup automatically after authorization.",
        ),
        waiting: tx("settings.channels.feishuWaiting", "Waiting for authorization..."),
        connected: tx("settings.channels.feishuConnected", "Feishu is connected."),
        stopped: tx("settings.channels.feishuConnectStopped", "Connection stopped."),
        connecting: tx("settings.channels.feishuConnecting", "Connecting..."),
        scanAgain: tx("settings.channels.scanAgain", "Scan again"),
        connect: tx("settings.channels.connect", "Connect"),
      }}
    />
  );
}
