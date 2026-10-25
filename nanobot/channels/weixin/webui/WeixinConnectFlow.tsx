import { useTranslation } from "react-i18next";

import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";

import { WeixinConnectFlowView, weixinConnectLabels } from "./WeixinConnectFlowView";
import { isVerificationChallenge, WEIXIN_AUTH_EXPIRED_MESSAGE } from "./presentation";

export { WEIXIN_AUTH_EXPIRED_MESSAGE } from "./presentation";

export function WeixinConnectFlow({
  token,
  feature,
  authRecoveryActive = false,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps & { authRecoveryActive?: boolean }) {
  const { t } = useTranslation();
  const authExpired = authRecoveryActive
    || feature.runtime_error === WEIXIN_AUTH_EXPIRED_MESSAGE;
  const scanAgainLabel = t("settings.channels.scanAgain", {
    defaultValue: "Scan again",
  });

  if (feature.configured && !authExpired) return null;

  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="weixin"
      startParams={authExpired ? { force: true } : {}}
      idleLabel={authExpired ? scanAgainLabel : idleLabel}
      connectRequestId={connectRequestId}
      autoStart={!feature.configured || authExpired}
      minimalPending
      forceOnRepeat
      onFeaturesUpdate={onFeaturesUpdate}
      pausePolling={isVerificationChallenge}
      suppressSucceeded={feature.runtime_status === "failed"}
      labels={weixinConnectLabels(t)}
      renderView={(props) => <WeixinConnectFlowView {...props} />}
    />
  );
}
