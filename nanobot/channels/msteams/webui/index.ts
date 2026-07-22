import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Microsoft Teams",
    initials: "MS",
    color: "#6264A7",
    logoUrl: "https://www.microsoft.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("msteams"),
      fields: [
        { key: "channels.msteams.appId" },
        { key: "channels.msteams.appPassword" },
        { key: "channels.msteams.tenantId" },
        { key: "channels.msteams.path" },
        { key: "channels.msteams.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
