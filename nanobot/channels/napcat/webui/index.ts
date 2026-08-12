import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "NapCat",
    initials: "NC",
    color: "#F97316",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("napcat"),
      fields: [
        { key: "channels.napcat.wsUrl", section: "connection" },
        { key: "channels.napcat.accessToken", section: "credentials" },
        { key: "channels.napcat.groupPolicy", section: "behavior" },
        { key: "channels.napcat.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
