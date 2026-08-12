import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "QQ",
    initials: "QQ",
    color: "#12B7F5",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("qq"),
      fields: [
        { key: "channels.qq.appId", section: "credentials" },
        { key: "channels.qq.secret", section: "credentials" },
        { key: "channels.qq.allowFrom", section: "access" },
        { key: "channels.qq.msgFormat", section: "behavior" },
      ],
    },
  },
} satisfies ChannelUiContribution;
