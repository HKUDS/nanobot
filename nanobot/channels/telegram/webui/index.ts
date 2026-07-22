import { Send } from "lucide-react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

import { TelegramBotsPanel } from "./TelegramBotsPanel";

export default {
  Panel: TelegramBotsPanel,
  presentation: {
    displayName: "Telegram",
    initials: "TG",
    color: "#229ED9",
    icon: Send,
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("telegram"),
      fields: [
        { key: "channels.telegram.name" },
        { key: "channels.telegram.token" },
        { key: "channels.telegram.allowFrom" },
        { key: "channels.telegram.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
