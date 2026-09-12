import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Telegram",
    initials: "TG",
    color: "#229ED9",
    logoUrl: "https://telegram.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("telegram"),
      fields: [
        { key: "channels.telegram.token" },
        { key: "channels.telegram.proxy" },
        { key: "channels.telegram.allowFrom" },
        { key: "channels.telegram.groupPolicy" },
        { key: "channels.telegram.technical.enabled" },
        { key: "channels.telegram.technical.profileName" },
        { key: "channels.telegram.technical.chatId" },
        { key: "channels.telegram.technical.token" },
        { key: "channels.telegram.technical.includeToolEvents" },
        { key: "channels.telegram.technical.includeStatusEvents" },
        { key: "channels.telegram.technical.mainChatId" },
        { key: "channels.telegram.technical.sharedInbox" },
      ],
    },
  },
} satisfies ChannelUiContribution;
