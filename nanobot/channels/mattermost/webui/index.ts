import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Mattermost",
    initials: "MM",
    color: "#1C58D9",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("mattermost"),
      fields: [
        { key: "channels.mattermost.serverUrl", section: "connection" },
        { key: "channels.mattermost.teamId", section: "account" },
        { key: "channels.mattermost.token", section: "credentials" },
        { key: "channels.mattermost.allowFrom", section: "access" },
        { key: "channels.mattermost.groupPolicy", section: "behavior" },
        { key: "channels.mattermost.groupPolicyInThread", section: "behavior" },
      ],
    },
  },
} satisfies ChannelUiContribution;
