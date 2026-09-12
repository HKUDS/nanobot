import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    logoUrl: "https://img.alicdn.com/imgextra/i3/O1CN01WMvMRG1ks3Ixc9x1v_!!6000000004738-55-tps-32-32.svg",
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
