import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "WhatsApp",
    initials: "WA",
    color: "#25D366",
    logoUrl: "https://www.whatsapp.com/favicon.ico",
    setup: {
      mode: "connect",
      command: "nanobot channels login whatsapp",
      docsUrl: chatAppGuideUrl("whatsapp"),
      manualFields: [
        { key: "channels.whatsapp.allowFrom" },
        { key: "channels.whatsapp.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
