import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
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
      ],
    },
  },
} satisfies ChannelUiContribution;
