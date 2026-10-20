import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelQrConnectFlowView, type ChannelQrConnectFlowViewProps, type ChannelQrConnectLabels } from "@/components/settings/channels/ChannelQrConnectFlowView";

export type QQConnectFlowViewProps = Omit<ChannelQrConnectFlowViewProps, "labels"> & {
  configured?: boolean;
};

export function useQQConnectLabels(): ChannelQrConnectLabels {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "qq");
  return {
    qrAlt: tx("custom.qrAlt", "QQ login QR code"),
    scanTitle: tx("custom.scanTitle", "Scan with mobile QQ"),
    scanDescription: "",
    waiting: tx("custom.waiting", "Waiting for QQ scan..."),
    connected: tx("custom.connected", "QQ is connected."),
    stopped: tx("custom.stopped", "QQ login stopped."),
    connecting: tx("custom.connecting", "Connecting..."),
    scanAgain: t("settings.channels.scanAgain", { defaultValue: "Scan again" }),
    connect: t("settings.channels.connect", { defaultValue: "Connect" }),
  };
}

export function QQConnectFlowView({ configured, ...props }: QQConnectFlowViewProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "qq");
  const labels = useQQConnectLabels();
  const rescanWarning = configured ? tx("custom.scanAgainWarning", "") : "";
  return <ChannelQrConnectFlowView {...props} labels={labels}
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
  />;
}
