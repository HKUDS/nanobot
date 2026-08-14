import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Microsoft Teams",
    initials: "MS",
    color: "#6264A7",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("msteams"),
      fields: [
        { key: "channels.msteams.appId", section: "credentials" },
        { key: "channels.msteams.appPassword", section: "credentials" },
        { key: "channels.msteams.tenantId", section: "account" },
        { key: "channels.msteams.path", section: "connection" },
        { key: "channels.msteams.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
