import { lazy } from "react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

import {
  WEIXIN_ADVANCED_FIELD_KEYS,
  WEIXIN_PRIMARY_FIELD_KEYS,
} from "./presentation";

const WeixinPanel = lazy(() =>
  import("./WeixinPanel").then(({ WeixinPanel: component }) => ({ default: component })),
);
const WeixinConnectFlow = lazy(() =>
  import("./WeixinConnectFlow").then(({ WeixinConnectFlow: component }) => ({
    default: component,
  })),
);

export default {
  Panel: WeixinPanel,
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
      command: "nanobot channels login weixin",
      docsUrl: chatAppGuideUrl("wechat"),
      fields: WEIXIN_PRIMARY_FIELD_KEYS.map((key) => ({ key })),
      manualFields: WEIXIN_ADVANCED_FIELD_KEYS.map((key) => ({ key })),
    },
  },
} satisfies ChannelUiContribution;
