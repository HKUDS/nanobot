import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  channelTranslator,
  type ChannelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import {
  ChannelQrConnectFlow,
  type ChannelQrConnectPendingContext,
} from "@/components/settings/channels/ChannelQrConnectFlow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChannelConnectPayload } from "@/lib/types";

type WeixinVerificationPayload = ChannelConnectPayload & {
  challenge: "verify_code";
  verification_failed?: boolean;
};

export const WEIXIN_AUTH_EXPIRED_MESSAGE =
  "WeChat login expired. Scan again to reconnect.";

function isVerificationChallenge(
  payload: ChannelConnectPayload,
): payload is WeixinVerificationPayload {
  return (
    "challenge" in payload
    && payload.challenge === "verify_code"
    && (
      !("verification_failed" in payload)
      || typeof payload.verification_failed === "boolean"
    )
  );
}

function weixinConnectMessage(
  payload: ChannelConnectPayload,
  tx: ChannelTranslator,
): string {
  if (payload.status === "succeeded") {
    return tx("custom.connected", "WeChat is connected.");
  }
  if (payload.status === "expired") {
    return tx("custom.expired", WEIXIN_AUTH_EXPIRED_MESSAGE);
  }
  if (payload.status === "failed") {
    return payload.message
      ?? tx("custom.failed", "Unable to connect WeChat. Try again.");
  }
  if (payload.status === "cancelled") {
    return tx("custom.stopped", "WeChat login stopped.");
  }
  if (isVerificationChallenge(payload)) {
    return payload.verification_failed
      ? tx(
        "custom.verifyMismatch",
        "That code did not match. Enter the new number shown in WeChat.",
      )
      : tx(
        "custom.verifyDescription",
        "Enter the number shown in WeChat to continue.",
      );
  }
  return tx("custom.waiting", "Waiting for WeChat scan...");
}

export function WeixinConnectFlow({
  token,
  feature,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "weixin");
  const [verificationCode, setVerificationCode] = useState("");
  const authExpired = feature.runtime_error === WEIXIN_AUTH_EXPIRED_MESSAGE;
  const scanAgainLabel = t("settings.channels.scanAgain", {
    defaultValue: "Scan again",
  });

  const renderVerification = ({
    connect,
    busy,
    poll,
  }: ChannelQrConnectPendingContext) => {
    if (!isVerificationChallenge(connect)) return null;
    return (
      <form
        className="mt-3 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          const code = verificationCode.trim();
          if (!code) return;
          void poll({ verify_code: code }).then((payload) => {
            if (payload && !isVerificationChallenge(payload)) {
              setVerificationCode("");
            }
          });
        }}
      >
        <div className="text-[12px] font-semibold text-foreground">
          {tx("custom.verifyTitle", "Verification required")}
        </div>
        <p className="text-[12px] leading-5 text-muted-foreground">
          {weixinConnectMessage(connect, tx)}
        </p>
        <div className="flex gap-2">
          <Input
            value={verificationCode}
            onChange={(event) => setVerificationCode(event.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder={tx("custom.verifyPlaceholder", "Code")}
            className="h-8 max-w-40"
            aria-invalid={connect.verification_failed || undefined}
          />
          <Button
            type="submit"
            size="sm"
            className="h-8 rounded-full px-3 text-[12px] font-semibold"
            disabled={busy || !verificationCode.trim()}
          >
            {tx("custom.verifySubmit", "Verify")}
          </Button>
        </div>
      </form>
    );
  };

  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="weixin"
      startOptions={{ force: authExpired }}
      idleLabel={authExpired ? scanAgainLabel : idleLabel}
      connectRequestId={connectRequestId}
      forceOnRepeat
      onFeaturesUpdate={onFeaturesUpdate}
      pausePolling={isVerificationChallenge}
      suppressSucceeded={feature.runtime_status === "failed"}
      renderPending={renderVerification}
      resolveMessage={(payload) => weixinConnectMessage(payload, tx)}
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
        scanAgain: scanAgainLabel,
        connect: t("settings.channels.connect", { defaultValue: "Connect" }),
      }}
    />
  );
}
