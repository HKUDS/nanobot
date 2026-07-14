import type { ChannelUiContribution } from "@/channel-plugins/types";

import { WeixinConnectFlow } from "./WeixinConnectFlow";

export default {
  ConnectFlow: WeixinConnectFlow,
  canConnectBeforeConfigured: true,
} satisfies ChannelUiContribution;
