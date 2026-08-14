import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "DingTalk",
    initials: "DT",
    color: "#1677FF",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("dingtalk"),
      fields: [
        { key: "channels.dingtalk.clientId", section: "credentials" },
        { key: "channels.dingtalk.clientSecret", section: "credentials" },
        { key: "channels.dingtalk.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
