import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    logoUrl: "https://mochat.io/favicon.ico",
    displayName: "MoChat",
    initials: "MC",
    color: "#111827",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("mochat"),
      fields: [
        { key: "channels.mochat.clawToken", section: "credentials" },
        { key: "channels.mochat.baseUrl", section: "connection" },
        { key: "channels.mochat.agentUserId", section: "account" },
        { key: "channels.mochat.sessions", section: "access" },
        { key: "channels.mochat.panels", section: "access" },
        { key: "channels.mochat.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
