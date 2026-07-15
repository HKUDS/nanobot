import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Matrix",
    initials: "MX",
    color: "#0DBD8B",
    logoUrl: "https://matrix.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("matrix"),
      fields: [
        { key: "channels.matrix.homeserver" },
        { key: "channels.matrix.userId" },
        { key: "channels.matrix.password" },
        { key: "channels.matrix.accessToken" },
        { key: "channels.matrix.deviceId" },
        { key: "channels.matrix.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
