import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

export function WhatsAppConnectFlow({
  token,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "whatsapp");

  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="whatsapp"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      forceOnRepeat
      labels={{
        qrAlt: tx("custom.qrAlt", "WhatsApp linking QR code"),
        scanTitle: tx("custom.scanTitle", "Link WhatsApp"),
        scanDescription: tx(
          "custom.scanDescription",
          "In WhatsApp, open Linked devices, choose Link a device, then scan this code.",
        ),
        waiting: tx("custom.waiting", "Waiting for WhatsApp…"),
        connected: tx("custom.connected", "WhatsApp is connected."),
        stopped: tx(
          "custom.stopped",
          "The WhatsApp connection attempt stopped. Start again to get a new code.",
        ),
        connecting: tx("custom.connecting", "Connecting…"),
        scanAgain: tx("custom.scanAgain", "Link another account"),
        connect: tx("custom.connect", "Link WhatsApp"),
      }}
      onFeaturesUpdate={onFeaturesUpdate}
    />
  );
}
