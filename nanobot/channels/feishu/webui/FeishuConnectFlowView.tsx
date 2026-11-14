import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelQrConnectFlowView, type ChannelQrConnectFlowViewProps, type ChannelQrConnectLabels } from "@/components/settings/channels/ChannelQrConnectFlowView";

export type FeishuConnectFlowViewProps = Omit<ChannelQrConnectFlowViewProps, "labels">;

export function useFeishuConnectLabels(): ChannelQrConnectLabels {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "feishu");
  return {
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
  };
}

export function FeishuConnectFlowView(props: FeishuConnectFlowViewProps) {
  const labels = useFeishuConnectLabels();
  return <ChannelQrConnectFlowView {...props} labels={labels} />;
}
