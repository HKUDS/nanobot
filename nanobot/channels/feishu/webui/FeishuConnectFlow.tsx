import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
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
  const tx = channelTranslator(t, "feishu");
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="feishu"
      startOptions={{ domain: "feishu", instanceId, mode }}
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      onFeaturesUpdate={onFeaturesUpdate}
      labels={{
        qrAlt: tx("custom.qrAlt", "Feishu connection QR code"),
        scanTitle: tx("custom.scanTitle", "Scan with Feishu"),
        scanDescription: tx(
          "custom.scanDescription",
          "Use Feishu or Lark on your phone to scan this code. nanobot will finish setup automatically after authorization.",
        ),
        waiting: tx("custom.waiting", "Waiting for authorization..."),
        connected: tx("custom.connected", "Feishu is connected."),
        stopped: tx("custom.stopped", "Connection stopped."),
        connecting: tx("custom.connecting", "Connecting..."),
        scanAgain: t("settings.channels.scanAgain", { defaultValue: "Scan again" }),
        connect: t("settings.channels.connect", { defaultValue: "Connect" }),
      }}
    />
  );
}
