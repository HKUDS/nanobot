import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

export function WeixinConnectFlow({
  token,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "weixin");
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="weixin"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      forceOnRepeat
      onFeaturesUpdate={onFeaturesUpdate}
      labels={{
        qrAlt: tx("custom.qrAlt", "WeChat login QR code"),
        scanTitle: tx("custom.scanTitle", "Scan with WeChat"),
        scanDescription: tx(
          "custom.scanDescription",
          "Use WeChat on your phone to scan this code. nanobot saves the account state locally after login.",
        ),
        waiting: tx("custom.waiting", "Waiting for WeChat scan..."),
        connected: tx("custom.connected", "WeChat is connected."),
        stopped: tx("custom.stopped", "WeChat login stopped."),
        connecting: tx("custom.connecting", "Connecting..."),
        scanAgain: t("settings.channels.scanAgain", { defaultValue: "Scan again" }),
        connect: t("settings.channels.connect", { defaultValue: "Connect" }),
      }}
    />
  );
}
