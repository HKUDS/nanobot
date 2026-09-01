import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "NapCat",
    initials: "NC",
    color: "#F97316",
    logoUrl: "https://napneko.github.io/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("napcat"),
      fields: [
        { key: "channels.napcat.wsUrl" },
        { key: "channels.napcat.accessToken" },
        { key: "channels.napcat.groupPolicy" },
        { key: "channels.napcat.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
