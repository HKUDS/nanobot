import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Mattermost",
    initials: "MM",
    color: "#1C58D9",
    logoUrl: "https://mattermost.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("mattermost"),
      fields: [
        { key: "channels.mattermost.serverUrl" },
        { key: "channels.mattermost.token" },
        { key: "channels.mattermost.teamId" },
        { key: "channels.mattermost.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
