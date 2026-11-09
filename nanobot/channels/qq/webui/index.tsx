import { lazy } from "react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/channel-plugins/catalog";

const QQConnectFlow = lazy(() =>
  import("./QQConnectFlow").then(({ QQConnectFlow: component }) => ({ default: component })),
);

export default {
  ConnectFlow: QQConnectFlow,
  canConnectBeforeConfigured: true,
  presentation: {
    logoUrl: "https://static-res.qq.com/static-res/imqq/qq-logo.png",
    logoFallbackUrl: "https://im.qq.com/favicon.ico",
    displayName: "QQ",
    initials: "QQ",
    color: "#12B7F5",
    setup: {
      mode: "connect",
      command: "nanobot channels login qq",
      docsUrl: chatAppGuideUrl("qq"),
      manualFields: [
        { key: "channels.qq.appId", section: "credentials" },
        { key: "channels.qq.secret", section: "credentials" },
        { key: "channels.qq.allowFrom", section: "access" },
        { key: "channels.qq.msgFormat", section: "behavior" },
        { key: "channels.qq.ackMessage", section: "behavior" },
        { key: "channels.qq.showCompactionNotices", section: "behavior" },
        { key: "channels.qq.mediaDir", section: "advanced" },
        { key: "channels.qq.downloadChunkSize", section: "advanced" },
        { key: "channels.qq.downloadMaxBytes", section: "advanced" },
      ],
    },
  },
} satisfies ChannelUiContribution;
