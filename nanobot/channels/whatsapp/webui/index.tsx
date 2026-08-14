import { MessageCircle } from "lucide-react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

import { WhatsAppConnectFlow } from "./WhatsAppConnectFlow";

export default {
  presentation: {
    displayName: "WhatsApp",
    initials: "WA",
    color: "#25D366",
    icon: MessageCircle,
    setup: {
      mode: "connect",
      docsUrl: chatAppGuideUrl("whatsapp"),
      manualFields: [
        { key: "channels.whatsapp.allowFrom", section: "access" },
        { key: "channels.whatsapp.groupPolicy", section: "behavior" },
      ],
    },
  },
  ConnectFlow: WhatsAppConnectFlow,
  canConnectBeforeConfigured: true,
} satisfies ChannelUiContribution;
