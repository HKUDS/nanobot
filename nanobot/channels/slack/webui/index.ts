import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

const SLACK_SOCKET_MODE_MANIFEST = `display_information:
  name: nanobot
features:
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: nanobot
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - files:read
      - files:write
      - groups:history
      - groups:read
      - im:history
      - im:write
      - mpim:history
      - reactions:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
      - message.mpim
  socket_mode_enabled: true
  interactivity:
    is_enabled: true`;

export default {
  presentation: {
    displayName: "Slack",
    initials: "SL",
    color: "#4A154B",
    logoUrl: "https://slack.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("slack"),
      actions: [
        {
          id: "slack-manifest",
          copyText: SLACK_SOCKET_MODE_MANIFEST,
          logoUrl: "https://slack.com/favicon.ico",
        },
      ],
      fields: [
        { key: "channels.slack.appToken" },
        { key: "channels.slack.botToken" },
        { key: "channels.slack.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
