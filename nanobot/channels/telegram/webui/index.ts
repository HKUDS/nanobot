import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    logoUrl: "https://telegram.org/favicon.ico",
    displayName: "Telegram",
    initials: "TG",
    color: "#229ED9",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("telegram"),
      fields: [
        { key: "channels.telegram.token", section: "credentials" },
        { key: "channels.telegram.proxy", section: "connection" },
        { key: "channels.telegram.allowFrom", section: "access" },
        { key: "channels.telegram.groupPolicy", section: "behavior" },
        { key: "channels.telegram.technical.enabled", section: "behavior" },
        { key: "channels.telegram.technical.profileName", section: "behavior" },
        { key: "channels.telegram.technical.chatId", section: "behavior" },
        { key: "channels.telegram.technical.token", section: "behavior" },
        { key: "channels.telegram.technical.includeToolEvents", section: "behavior" },
        { key: "channels.telegram.technical.includeStatusEvents", section: "behavior" },
        { key: "channels.telegram.technical.mainChatId", section: "behavior" },
        { key: "channels.telegram.technical.sharedInbox", section: "behavior" },
      ],
    },
  },
} satisfies ChannelUiContribution;
