import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Discord",
    initials: "DC",
    color: "#5865F2",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("discord"),
      fields: [
        { key: "channels.discord.token", section: "credentials" },
        { key: "channels.discord.allowFrom", section: "access" },
        { key: "channels.discord.allowChannels", section: "access" },
        { key: "channels.discord.groupPolicy", section: "behavior" },
      ],
    },
  },
} satisfies ChannelUiContribution;
