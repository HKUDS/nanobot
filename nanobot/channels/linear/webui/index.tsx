import { lazy } from "react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

const LinearConnectFlow = lazy(() =>
  import("./LinearConnectFlow").then(({ LinearConnectFlow: component }) => ({
    default: component,
  })),
);

export default {
  ConnectFlow: LinearConnectFlow,
  presentation: {
    displayName: "Linear",
    initials: "LI",
    color: "#5E6AD2",
    logoUrl: "https://linear.app/favicon.ico",
    setup: {
      mode: "connect",
      docsUrl: chatAppGuideUrl("linear"),
      fields: [
        { key: "channels.linear.clientId" },
        { key: "channels.linear.clientSecret" },
        { key: "channels.linear.webhookSigningSecret" },
        { key: "channels.linear.publicBaseUrl" },
      ],
      manualFields: [
        { key: "channels.linear.host" },
        { key: "channels.linear.port" },
        { key: "channels.linear.webhookPath" },
        { key: "channels.linear.oauthCallbackPath" },
        { key: "channels.linear.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
