import { useTranslation } from "react-i18next";

import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

export function QQConnectFlow({
  token,
  feature,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "qq");
  // Every scan rotates the App Secret, so warn before the user scans again.
  const rescanWarning = feature.configured
    ? tx("custom.scanAgainWarning", "")
    : "";
  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="qq"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      autoStart={!feature.configured}
      forceOnRepeat
      renderActions={(connectButton) => (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {rescanWarning ? (
            <p className="max-w-[22rem] text-[11.5px] leading-5 text-muted-foreground">
              {rescanWarning}
            </p>
          ) : null}
          {connectButton}
        </div>
      )}
      labels={{
        qrAlt: tx("custom.qrAlt", "QQ login QR code"),
        scanTitle: tx("custom.scanTitle", "Scan with mobile QQ"),
        scanDescription: "",
        waiting: tx("custom.waiting", "Waiting for QQ scan..."),
        connected: tx("custom.connected", "QQ is connected."),
        stopped: tx("custom.stopped", "QQ login stopped."),
        connecting: tx("custom.connecting", "Connecting..."),
        scanAgain: t("settings.channels.scanAgain", { defaultValue: "Scan again" }),
        connect: t("settings.channels.connect", { defaultValue: "Connect" }),
      }}
      onFeaturesUpdate={onFeaturesUpdate}
    />
  );
}
