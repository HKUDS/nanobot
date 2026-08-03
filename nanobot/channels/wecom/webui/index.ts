import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "WeCom",
    initials: "WC",
    color: "#2F7DFF",
    logoUrl: "https://work.weixin.qq.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("wecom"),
      fields: [
        { key: "channels.wecom.botId" },
        { key: "channels.wecom.secret" },
        { key: "channels.wecom.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
