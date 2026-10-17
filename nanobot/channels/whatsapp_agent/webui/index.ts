import { Bot } from "lucide-react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    logoUrl: "https://static.whatsapp.net/rsrc.php/y1/r/FJbTMJqMap7.svg",
    displayName: "WhatsApp Agent Platform",
    initials: "WA",
    color: "#25D366",
    icon: Bot,
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("whatsapp-agent-platform"),
      fields: [
        { key: "channels.whatsapp_agent.token", section: "credentials" },
        { key: "channels.whatsapp_agent.allowFrom", section: "access" },
        { key: "channels.whatsapp_agent.markRead", section: "behavior" },
        { key: "channels.whatsapp_agent.typingIndicator", section: "behavior" },
        { key: "channels.whatsapp_agent.downloadMedia", section: "behavior" },
        { key: "channels.whatsapp_agent.deleteMediaAfterDownload", section: "behavior" },
        { key: "channels.whatsapp_agent.retryAmbiguousSends", section: "behavior" },
        { key: "channels.whatsapp_agent.pollTimeout", section: "advanced" },
        { key: "channels.whatsapp_agent.maxMediaMb", section: "advanced" },
        { key: "channels.whatsapp_agent.stateDir", section: "advanced" },
      ],
    },
  },
} satisfies ChannelUiContribution;
