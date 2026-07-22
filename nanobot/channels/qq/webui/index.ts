import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "QQ",
    initials: "QQ",
    color: "#12B7F5",
    logoUrl: "https://im.qq.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("qq"),
      fields: [
        { key: "channels.qq.appId" },
        { key: "channels.qq.secret" },
        { key: "channels.qq.allowFrom" },
        { key: "channels.qq.msgFormat" },
      ],
    },
  },
} satisfies ChannelUiContribution;
