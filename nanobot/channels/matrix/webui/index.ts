import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Matrix",
    initials: "MX",
    color: "#0DBD8B",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("matrix"),
      fields: [
        { key: "channels.matrix.homeserver", section: "connection" },
        { key: "channels.matrix.userId", section: "account" },
        { key: "channels.matrix.password", section: "credentials" },
        { key: "channels.matrix.accessToken", section: "credentials" },
        { key: "channels.matrix.deviceId", section: "credentials" },
        { key: "channels.matrix.groupPolicy", section: "behavior" },
      ],
    },
  },
} satisfies ChannelUiContribution;
