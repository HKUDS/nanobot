import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "WeCom",
    initials: "WC",
    color: "#2F7DFF",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("wecom"),
      fields: [
        { key: "channels.wecom.botId", section: "credentials" },
        { key: "channels.wecom.secret", section: "credentials" },
        { key: "channels.wecom.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
