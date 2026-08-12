import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Signal",
    initials: "SG",
    color: "#3A76F0",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("signal"),
      fields: [
        { key: "channels.signal.phoneNumber", section: "account" },
        { key: "channels.signal.daemonHost", section: "connection" },
        { key: "channels.signal.daemonPort", section: "connection" },
        { key: "channels.signal.dm.allowFrom", section: "access" },
        { key: "channels.signal.group.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
