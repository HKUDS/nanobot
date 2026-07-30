import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Signal",
    initials: "SG",
    color: "#3A76F0",
    logoUrl: "https://signal.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("signal"),
      fields: [
        { key: "channels.signal.phoneNumber" },
        { key: "channels.signal.daemonHost" },
        { key: "channels.signal.daemonPort" },
        { key: "channels.signal.dm.allowFrom" },
        { key: "channels.signal.group.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
