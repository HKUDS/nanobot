import { useTranslation } from "react-i18next";

import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

export function WeixinConnectFlow({
  token,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="weixin"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      forceOnRepeat
      onFeaturesUpdate={onFeaturesUpdate}
      labels={{
        qrAlt: tx("settings.channels.weixinQrAlt", "WeChat login QR code"),
        scanTitle: tx("settings.channels.weixinScanTitle", "Scan with WeChat"),
        scanDescription: tx(
          "settings.channels.weixinScanDescription",
          "Use WeChat on your phone to scan this code. nanobot saves the account state locally after login.",
        ),
        waiting: tx("settings.channels.weixinWaiting", "Waiting for WeChat scan..."),
        connected: tx("settings.channels.weixinConnected", "WeChat is connected."),
        stopped: tx("settings.channels.weixinConnectStopped", "WeChat login stopped."),
        connecting: tx("settings.channels.weixinConnecting", "Connecting..."),
        scanAgain: tx("settings.channels.scanAgain", "Scan again"),
        connect: tx("settings.channels.connect", "Connect"),
      }}
    />
  );
}
