import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

import { WeixinConnectFlow } from "./WeixinConnectFlow";

export default {
  ConnectFlow: WeixinConnectFlow,
  canConnectBeforeConfigured: true,
  aliases: {
    wechat: {},
  },
  presentation: {
    displayName: "WeChat",
    initials: "WX",
    color: "#07C160",
    logoUrl: "https://weixin.qq.com/favicon.ico",
    setup: {
      mode: "connect",
      compact: true,
      command: "nanobot channels login weixin",
      docsUrl: chatAppGuideUrl("wechat"),
      fields: [
        { key: "channels.weixin.allowFrom" },
        { key: "channels.weixin.sendProgress" },
        { key: "channels.weixin.sendToolHints" },
        { key: "channels.weixin.streaming" },
      ],
      manualFields: [
        { key: "channels.weixin.token" },
        { key: "channels.weixin.replyProgressMessages" },
        { key: "channels.weixin.replyProgressMaxMessages" },
        { key: "channels.weixin.contextMessageBudget" },
        { key: "channels.weixin.blockStreaming" },
        { key: "channels.weixin.blockStreamingMinChars" },
        { key: "channels.weixin.blockStreamingMaxMessages" },
        { key: "channels.weixin.baseUrl" },
        { key: "channels.weixin.cdnBaseUrl" },
        { key: "channels.weixin.routeTag" },
        { key: "channels.weixin.stateDir" },
        { key: "channels.weixin.pollTimeout" },
      ],
    },
  },
} satisfies ChannelUiContribution;
