import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import { Button } from "@/components/ui/button";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";

export function LinearConnectFlow({
  token,
  feature,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const publicBaseUrl = feature.config_values?.["channels.linear.publicBaseUrl"]?.replace(/\/$/, "");
  const webhookPath = feature.config_values?.["channels.linear.webhookPath"] || "/linear/webhook";
  const callbackPath = feature.config_values?.["channels.linear.oauthCallbackPath"] || "/linear/oauth/callback";
  const manifestUrl = publicBaseUrl
    ? linearManifestUrl(publicBaseUrl, webhookPath, callbackPath)
    : null;

  return (
    <div className="mt-3 space-y-3">
      {manifestUrl ? (
        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 rounded-full px-3 text-[12px] font-semibold"
            onClick={() => window.open(manifestUrl, "_blank", "noopener,noreferrer")}
          >
            <ExternalLink className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            {t("settings.channels.createApp", { defaultValue: "Create prefilled Linear app" })}
          </Button>
        </div>
      ) : null}
      <ChannelQrConnectFlow
        token={token}
        channelName="linear"
        idleLabel={idleLabel}
        connectRequestId={connectRequestId}
        forceOnRepeat
        onFeaturesUpdate={onFeaturesUpdate}
        labels={{
          qrAlt: tx("custom.qrAlt", "Linear authorization QR code"),
          scanTitle: tx("custom.authorizeTitle", "Authorize in Linear"),
          scanDescription: tx(
            "custom.authorizeDescription",
            "Open Linear in this browser or scan the QR code. nanobot enables the channel after authorization.",
          ),
          waiting: tx("custom.waiting", "Waiting for Linear authorization..."),
          connected: tx("custom.connected", "Linear is connected."),
          stopped: tx("custom.stopped", "Authorization stopped."),
          connecting: tx("custom.connecting", "Connecting..."),
          scanAgain: tx("custom.reconnect", "Connect another workspace"),
          connect: tx("custom.connect", "Connect Linear"),
        }}
        renderPending={({ connect }) => (
          <div className="mt-3 space-y-3">
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <span className="h-2 w-2 animate-pulse rounded-full bg-[#5E6AD2]" aria-hidden />
              {tx("custom.waiting", "Waiting for Linear authorization...")}
            </div>
            {connect.qr_url ? (
              <Button
                type="button"
                size="sm"
                className="h-8 rounded-full px-3 text-[12px] font-semibold"
                onClick={() => window.open(connect.qr_url, "_blank", "noopener,noreferrer")}
              >
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {tx("custom.openLinear", "Continue in Linear")}
              </Button>
            ) : null}
          </div>
        )}
      />
    </div>
  );
}

export function linearManifestUrl(
  publicBaseUrl: string,
  webhookPath: string,
  callbackPath: string,
): string {
  const manifest = {
    $schema: "https://linear.app/.well-known/oauth-app-manifest.schema.json",
    schemaVersion: "1.0.0",
    distribution: "private",
    display: {
      description: "Use nanobot as a native issue agent.",
    },
    developer: { name: "nanobot" },
    oauth: {
      client_name: "nanobot Agent",
      client_uri: publicBaseUrl,
      redirect_uris: [`${publicBaseUrl}${callbackPath}`],
      grant_types: ["authorization_code"],
    },
    webhook: {
      enabled: true,
      url: `${publicBaseUrl}${webhookPath}`,
      resourceTypes: [
        "AgentSessionEvent",
        "PermissionChange",
        "OAuthAuthorization",
      ],
    },
  };
  return `https://linear.app/settings/api/applications/new?${new URLSearchParams({
    manifest: JSON.stringify(manifest),
  })}`;
}
