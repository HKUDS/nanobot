import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Discord",
    initials: "DC",
    color: "#5865F2",
    logoUrl: "https://discord.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("discord"),
      fields: [
        { key: "channels.discord.token" },
        { key: "channels.discord.allowChannels" },
        { key: "channels.discord.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
