import type { ChannelUiContribution } from "@/channel-plugins/types";

import { FeishuAssistantsPanel } from "./FeishuAssistantsPanel";

export default {
  Panel: FeishuAssistantsPanel,
} satisfies ChannelUiContribution;
