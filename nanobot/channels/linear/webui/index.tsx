import { lazy } from "react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

import { LinearHelpContent } from "./LinearHelpContent";

const LinearPanel = lazy(() =>
  import("./LinearPanel").then(({ LinearPanel: component }) => ({
    default: component,
  })),
);

export default {
  Panel: LinearPanel,
  HelpContent: LinearHelpContent,
  presentation: {
    displayName: "Linear",
    initials: "LI",
    color: "#5E6AD2",
    logoUrl: "https://linear.app/favicon.ico",
    logoLayout: "tile",
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
        { key: "channels.linear.showReasoning" },
      ],
    },
  },
} satisfies ChannelUiContribution;
