import { Network } from "lucide-react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "WebSocket",
    initials: "WS",
    color: "#111827",
    icon: Network,
    setup: {
      mode: "webui",
      docsUrl: chatAppGuideUrl("websocket"),
    },
  },
} satisfies ChannelUiContribution;
