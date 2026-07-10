import { Network, type LucideIcon } from "lucide-react";

export type ChannelPresentation = {
  displayName: string;
  description: string;
  requirements: string;
  initials: string;
  color: string;
  icon?: LucideIcon;
  logoUrl?: string;
  setup?: ChannelSetupPresentation;
};
export type ChannelSetupPresentation = {
  mode?: "webui" | "credentials" | "connect";
  primaryActionLabel?: string;
  command?: string;
  docsUrl?: string;
  docsLabel?: string;
  docsLogoUrl?: string;
  officialUrl?: string;
  officialLabel?: string;
  summary?: string;
  tryIt?: string;
  steps: string[];
  fields?: ChannelConfigField[];
  manualFields?: ChannelConfigField[];
  actions?: ChannelSetupAction[];
  presets?: ChannelProviderPreset[];
};

export type ChannelSetupAction = {
  id: string;
  label: string;
  url?: string;
  copyText?: string;
  logoUrl?: string;
};

export type ChannelProviderPreset = {
  id: string;
  label: string;
  values: Record<string, string>;
};

export type ChannelConfigField = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  optional?: boolean;
  help?: string;
  inputType?: "text" | "number";
  defaultValue?: string;
  options?: ChannelConfigOption[];
};

export type ChannelConfigOption = {
  value: string;
  label: string;
};

const GROUP_BEHAVIOR_OPTIONS: ChannelConfigOption[] = [
  { value: "mention", label: "Mention only" },
  { value: "open", label: "All messages" },
];

const GROUP_BEHAVIOR_ALLOWLIST_OPTIONS: ChannelConfigOption[] = [
  ...GROUP_BEHAVIOR_OPTIONS,
  { value: "allowlist", label: "Allowlist" },
];

const FEISHU_REGION_OPTIONS: ChannelConfigOption[] = [
  { value: "feishu", label: "Feishu" },
  { value: "lark", label: "Lark" },
];

const BOOLEAN_OPTIONS: ChannelConfigOption[] = [
  { value: "true", label: "On" },
  { value: "false", label: "Off" },
];

const CONSENT_OPTIONS: ChannelConfigOption[] = [
  { value: "true", label: "Granted" },
  { value: "false", label: "Not granted" },
];

const QQ_MESSAGE_FORMAT_OPTIONS: ChannelConfigOption[] = [
  { value: "plain", label: "Plain text" },
  { value: "markdown", label: "Markdown" },
];

const NANOBOT_DOCS_URL = "https://nanobot.wiki/docs/latest";
const CHAT_APPS_DOCS_URL = `${NANOBOT_DOCS_URL}/getting-started/chat-apps`;
const SLACK_APPS_URL = "https://api.slack.com/apps";
const TELEGRAM_BOTFATHER_URL = "https://t.me/BotFather";
const DISCORD_DEVELOPER_URL = "https://discord.com/developers/applications";
const GMAIL_APP_PASSWORDS_URL = "https://support.google.com/accounts/answer/185833";
const FEISHU_OPEN_PLATFORM_URL = "https://open.feishu.cn/app";
const DINGTALK_OPEN_PLATFORM_URL = "https://open.dingtalk.com/";
const WECOM_DEVELOPER_URL = "https://developer.work.weixin.qq.com/";
const QQ_OPEN_PLATFORM_URL = "https://q.qq.com/";
const MATRIX_CLIENTS_URL = "https://matrix.org/ecosystem/clients/";
const MATTERMOST_BOT_DOCS_URL = "https://developers.mattermost.com/integrate/reference/bot-accounts/";
const SIGNAL_CLI_URL = "https://github.com/bbernhard/signal-cli-rest-api";
const TEAMS_DEVELOPER_URL = "https://dev.teams.microsoft.com/apps";
const NAPCAT_DOCS_URL = "https://napneko.github.io/";

const SLACK_SOCKET_MODE_MANIFEST = `display_information:
  name: nanobot
features:
  bot_user:
    display_name: nanobot
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - chat:write
      - groups:history
      - im:history
      - im:write
settings:
  socket_mode_enabled: true
  interactivity:
    is_enabled: true`;

const EMAIL_PROVIDER_PRESETS: ChannelProviderPreset[] = [
  {
    id: "gmail",
    label: "Gmail",
    values: {
      "channels.email.imapHost": "imap.gmail.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.gmail.com",
      "channels.email.smtpPort": "587",
    },
  },
  {
    id: "outlook",
    label: "Outlook",
    values: {
      "channels.email.imapHost": "outlook.office365.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.office365.com",
      "channels.email.smtpPort": "587",
    },
  },
  {
    id: "icloud",
    label: "iCloud",
    values: {
      "channels.email.imapHost": "imap.mail.me.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.mail.me.com",
      "channels.email.smtpPort": "587",
    },
  },
  { id: "custom", label: "Custom", values: {} },
];

function chatAppGuideUrl(sectionId: string): string {
  return `${CHAT_APPS_DOCS_URL}#${sectionId}`;
}

export function docsUrlWithBase(url: string | undefined, chatAppsDocsUrl?: string): string | undefined {
  if (!url || !chatAppsDocsUrl) return url;
  if (!url.startsWith(CHAT_APPS_DOCS_URL)) return url;
  const anchor = url.includes("#") ? `#${url.split("#").pop()}` : "";
  return `${chatAppsDocsUrl.replace(/\/$/, "")}${anchor}`;
}

export const CHANNEL_PRESENTATION: Record<string, ChannelPresentation> = {
  websocket: {
    displayName: "WebSocket",
    description: "Use nanobot from the local browser workbench.",
    requirements: "Local gateway, WebSocket token",
    initials: "WS",
    color: "#111827",
    icon: Network,
    setup: {
      mode: "webui",
      docsUrl: chatAppGuideUrl("websocket"),
      docsLabel: "Open WebSocket setup",
      tryIt: "Open the WebUI and send a short message.",
      summary: "WebSocket is required by the browser workbench and is prepared by the nanobot webui command.",
      steps: [
        "Start the workbench with nanobot webui so the local gateway and WebSocket channel are enabled together.",
        "Keep this channel enabled while using the WebUI.",
        "Change host, port, or token only from config.json when you need a custom local setup.",
      ],
    },
  },
  telegram: {
    displayName: "Telegram",
    description: "Chat with nanobot from Telegram chats.",
    requirements: "Bot token, allowed users, gateway",
    initials: "TG",
    color: "#229ED9",
    logoUrl: "https://telegram.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("telegram"),
      docsLabel: "Open Telegram setup",
      officialUrl: TELEGRAM_BOTFATHER_URL,
      officialLabel: "Open BotFather",
      tryIt: "Send /start or a short DM to your Telegram bot.",
      summary: "Enable turns on Telegram support. Telegram still needs a BotFather token before messages can flow.",
      steps: [
        "Create a bot with BotFather and copy the bot token.",
        "Add the token under channels.telegram.token; optionally restrict allowFrom and groupPolicy.",
        "Restart nanobot, then send the bot a direct message or mention it in a group.",
      ],
      fields: [
        {
          key: "channels.telegram.token",
          label: "Bot token",
          placeholder: "123456:ABC...",
          secret: true,
          help: "Create it with BotFather.",
        },
        {
          key: "channels.telegram.allowFrom",
          label: "Allowed users",
          placeholder: "* or Telegram user IDs",
          optional: true,
          help: "Leave empty to use pairing codes.",
        },
        {
          key: "channels.telegram.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  feishu: {
    displayName: "Feishu",
    description: "Use nanobot from Feishu chats and groups.",
    requirements: "Feishu app credentials, event subscription, gateway",
    initials: "FS",
    color: "#3370FF",
    logoUrl: "https://www.feishu.cn/favicon.ico",
    setup: {
      mode: "connect",
      primaryActionLabel: "Connect with Feishu",
      command: "nanobot channels login feishu",
      docsUrl: chatAppGuideUrl("feishu"),
      docsLabel: "Open Feishu setup",
      officialUrl: FEISHU_OPEN_PLATFORM_URL,
      officialLabel: "Open Feishu console",
      tryIt: "Send a DM or mention the Feishu assistant in a group.",
      summary:
        "Connect creates or links a Feishu app by QR code, then saves the app credentials for nanobot.",
      steps: [
        "Click Connect and scan the QR code with Feishu or Lark on your phone.",
        "Approve the app connection. nanobot saves the App ID and Secret automatically.",
        "Send the bot a direct message or mention it in a Feishu group to test it.",
      ],
      manualFields: [
        {
          key: "channels.feishu.appId",
          label: "App ID",
          placeholder: "cli_xxx",
        },
        {
          key: "channels.feishu.appSecret",
          label: "App Secret",
          placeholder: "Leave blank to keep current secret",
          secret: true,
          help: "Paste a new App Secret only when rotating credentials.",
        },
        {
          key: "channels.feishu.domain",
          label: "Region",
          defaultValue: "feishu",
          options: FEISHU_REGION_OPTIONS,
          optional: true,
        },
        {
          key: "channels.feishu.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_OPTIONS,
          optional: true,
        },
        {
          key: "channels.feishu.allowFrom",
          label: "Allowed users",
          placeholder: "User IDs, comma separated",
          optional: true,
        },
      ],
    },
  },
  slack: {
    displayName: "Slack",
    description: "Use nanobot from Slack workspaces.",
    requirements: "Slack app token, bot token, workspace install",
    initials: "SL",
    color: "#4A154B",
    logoUrl: "https://slack.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("slack"),
      docsLabel: "Open Slack setup",
      officialUrl: SLACK_APPS_URL,
      officialLabel: "Open Slack apps",
      tryIt: "Mention the Slack app or send it a direct message.",
      actions: [
        {
          id: "slack-manifest",
          label: "Copy manifest",
          copyText: SLACK_SOCKET_MODE_MANIFEST,
          logoUrl: "https://slack.com/favicon.ico",
        },
      ],
      summary: "Slack uses Socket Mode by default, so it needs both app-level and bot-level tokens.",
      steps: [
        "Create a Slack app, enable Socket Mode, and install it into the workspace.",
        "Add the app token and bot token under channels.slack.",
        "Restart nanobot, then mention the app or send it a direct message in Slack.",
      ],
      fields: [
        {
          key: "channels.slack.appToken",
          label: "App token",
          placeholder: "xapp-...",
          secret: true,
          help: "Create this from Slack Socket Mode.",
        },
        {
          key: "channels.slack.botToken",
          label: "Bot token",
          placeholder: "xoxb-...",
          secret: true,
          help: "Use the bot token after installing the Slack app.",
        },
        {
          key: "channels.slack.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_ALLOWLIST_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  discord: {
    displayName: "Discord",
    description: "Use nanobot from Discord servers and DMs.",
    requirements: "Discord bot token, permissions, gateway",
    initials: "DC",
    color: "#5865F2",
    logoUrl: "https://discord.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("discord"),
      docsLabel: "Open Discord setup",
      officialUrl: DISCORD_DEVELOPER_URL,
      officialLabel: "Open Discord portal",
      tryIt: "Mention the bot in a server or send it a direct message.",
      summary: "Enable turns on Discord support. Discord still needs a bot token and server permissions.",
      steps: [
        "Create an application and bot in the Discord Developer Portal, then copy the bot token.",
        "Invite the bot to your server with message read/send and slash command permissions.",
        "Add the token under channels.discord.token; optionally restrict allowFrom and allowChannels.",
        "Restart nanobot, then mention the bot or use its slash command in Discord.",
      ],
      fields: [
        {
          key: "channels.discord.token",
          label: "Bot token",
          placeholder: "Discord bot token",
          secret: true,
          help: "Create it from the Bot page in Discord Developer Portal.",
        },
        {
          key: "channels.discord.allowChannels",
          label: "Allowed channels",
          placeholder: "Channel IDs, comma separated",
          optional: true,
          help: "Leave empty to allow any channel the bot can read.",
        },
        {
          key: "channels.discord.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  email: {
    displayName: "Email",
    description: "Let nanobot receive and answer email messages.",
    requirements: "IMAP inbox, SMTP sender, app password, explicit consent",
    initials: "EM",
    color: "#64748B",
    logoUrl: "https://gmail.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("email"),
      docsLabel: "Open Email setup",
      officialUrl: GMAIL_APP_PASSWORDS_URL,
      officialLabel: "Open app password guide",
      tryIt: "Send a test email to the connected mailbox.",
      presets: EMAIL_PROVIDER_PRESETS,
      summary:
        "Email is IMAP polling plus SMTP replies. Use a dedicated mailbox when possible, and grant explicit consent before nanobot reads mail.",
      steps: [
        "Create or choose the mailbox nanobot will own, enable IMAP, and create an app password when the provider requires one.",
        "Fill IMAP settings for receiving unread mail, then SMTP settings for sending replies.",
        "Set consentGranted to true only after confirming this mailbox may be processed by nanobot.",
        "Restart nanobot, then send a test email to the mailbox.",
      ],
      fields: [
        {
          key: "channels.email.consentGranted",
          label: "Consent granted",
          defaultValue: "false",
          options: CONSENT_OPTIONS,
          help: "Required safety switch. Leave false until this bot mailbox is intentionally connected.",
        },
        {
          key: "channels.email.imapHost",
          label: "IMAP host",
          placeholder: "imap.gmail.com",
        },
        {
          key: "channels.email.imapUsername",
          label: "IMAP username",
          placeholder: "bot@example.com",
        },
        {
          key: "channels.email.imapPassword",
          label: "IMAP password",
          placeholder: "App password",
          secret: true,
          help: "Use an app password when your mail provider requires one.",
        },
        {
          key: "channels.email.smtpHost",
          label: "SMTP host",
          placeholder: "smtp.gmail.com",
        },
        {
          key: "channels.email.smtpUsername",
          label: "SMTP username",
          placeholder: "bot@example.com",
        },
        {
          key: "channels.email.smtpPassword",
          label: "SMTP password",
          placeholder: "App password",
          secret: true,
          help: "Usually the same app password used for IMAP.",
        },
        {
          key: "channels.email.imapPort",
          label: "IMAP port",
          placeholder: "993",
          inputType: "number",
          optional: true,
        },
        {
          key: "channels.email.smtpPort",
          label: "SMTP port",
          placeholder: "587",
          inputType: "number",
          optional: true,
        },
        {
          key: "channels.email.fromAddress",
          label: "From address",
          placeholder: "bot@example.com",
          optional: true,
        },
        {
          key: "channels.email.pollIntervalSeconds",
          label: "Poll interval",
          placeholder: "30",
          inputType: "number",
          optional: true,
        },
        {
          key: "channels.email.allowFrom",
          label: "Allowed senders",
          placeholder: "Email addresses, comma separated",
          optional: true,
          help: "Leave empty to require pairing before a sender can use email.",
        },
        {
          key: "channels.email.verifyDkim",
          label: "Verify DKIM",
          defaultValue: "true",
          options: BOOLEAN_OPTIONS,
          optional: true,
        },
        {
          key: "channels.email.verifySpf",
          label: "Verify SPF",
          defaultValue: "true",
          options: BOOLEAN_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  matrix: {
    displayName: "Matrix",
    description: "Use nanobot from Matrix rooms.",
    requirements: "Homeserver, account token, room access",
    initials: "MX",
    color: "#0DBD8B",
    logoUrl: "https://matrix.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("matrix"),
      docsLabel: "Open Matrix setup",
      officialUrl: MATRIX_CLIENTS_URL,
      officialLabel: "Open Matrix clients",
      tryIt: "Invite the Matrix account into a room and send a test message.",
      summary: "Matrix needs a homeserver account and either password login or an access token.",
      steps: [
        "Create or choose a Matrix account for nanobot.",
        "Add homeserver and login credentials under channels.matrix.",
        "Invite the account into the rooms nanobot should read, then restart nanobot.",
      ],
      fields: [
        {
          key: "channels.matrix.homeserver",
          label: "Homeserver",
          placeholder: "https://matrix.org",
        },
        {
          key: "channels.matrix.userId",
          label: "User ID",
          placeholder: "@nanobot:matrix.org",
        },
        {
          key: "channels.matrix.password",
          label: "Password",
          placeholder: "••••••",
          secret: true,
          optional: true,
          help: "Use either password login or access token login.",
        },
        {
          key: "channels.matrix.accessToken",
          label: "Access token",
          placeholder: "Optional token login",
          secret: true,
          optional: true,
          help: "Preferred when your Matrix client exposes an access token.",
        },
        {
          key: "channels.matrix.deviceId",
          label: "Device ID",
          placeholder: "Required with an access token",
          optional: true,
          help: "Copy the device ID associated with the access token. Password login does not need it.",
        },
        {
          key: "channels.matrix.groupPolicy",
          label: "Group behavior",
          defaultValue: "open",
          options: GROUP_BEHAVIOR_ALLOWLIST_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  mattermost: {
    displayName: "Mattermost",
    description: "Use nanobot from Mattermost channels and DMs.",
    requirements: "Mattermost server URL, bot token, channel access",
    initials: "MM",
    color: "#1C58D9",
    logoUrl: "https://mattermost.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("mattermost"),
      docsLabel: "Open Mattermost setup",
      officialUrl: MATTERMOST_BOT_DOCS_URL,
      officialLabel: "Open Mattermost bot guide",
      tryIt: "Mention the bot in a Mattermost channel or send it a direct message.",
      summary:
        "Mattermost connects with a bot account token and listens through the Mattermost WebSocket API.",
      steps: [
        "Create or choose a Mattermost bot account and copy its token.",
        "Add the Mattermost server URL and bot token.",
        "Invite the bot to the channels it should read.",
        "Restart nanobot, then mention the bot or send a direct message.",
      ],
      fields: [
        {
          key: "channels.mattermost.serverUrl",
          label: "Server URL",
          placeholder: "https://mattermost.example.com",
          help: "Use the base URL of your Mattermost workspace.",
        },
        {
          key: "channels.mattermost.token",
          label: "Bot token",
          placeholder: "Mattermost bot token",
          secret: true,
          help: "Create this from a Mattermost bot account.",
        },
        {
          key: "channels.mattermost.teamId",
          label: "Team ID",
          placeholder: "Optional team ID",
          optional: true,
        },
        {
          key: "channels.mattermost.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_ALLOWLIST_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  whatsapp: {
    displayName: "WhatsApp",
    description: "Use nanobot from WhatsApp conversations.",
    requirements: "WhatsApp connection setup and gateway",
    initials: "WA",
    color: "#25D366",
    logoUrl: "https://www.whatsapp.com/favicon.ico",
    setup: {
      mode: "connect",
      primaryActionLabel: "Connect WhatsApp",
      command: "nanobot channels login whatsapp",
      docsUrl: chatAppGuideUrl("whatsapp"),
      docsLabel: "Open WhatsApp setup",
      tryIt: "After terminal login finishes, send a WhatsApp DM to the connected account.",
      summary: "WhatsApp is connected by scanning a QR code from the account that should run the bot.",
      steps: [
        "Start the WhatsApp login flow.",
        "Scan the QR code with WhatsApp on your phone.",
        "Restart nanobot after the account state is saved, then send a direct test message.",
      ],
      manualFields: [
        {
          key: "channels.whatsapp.allowFrom",
          label: "Allowed contacts",
          placeholder: "Phone numbers or WhatsApp IDs",
          optional: true,
        },
        {
          key: "channels.whatsapp.groupPolicy",
          label: "Group behavior",
          defaultValue: "open",
          options: GROUP_BEHAVIOR_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  dingtalk: {
    displayName: "DingTalk",
    description: "Use nanobot from DingTalk groups.",
    requirements: "DingTalk app credentials and gateway",
    initials: "DT",
    color: "#1677FF",
    logoUrl: "https://www.dingtalk.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("dingtalk"),
      docsLabel: "Open DingTalk setup",
      officialUrl: DINGTALK_OPEN_PLATFORM_URL,
      officialLabel: "Open DingTalk console",
      tryIt: "Send a test message from the DingTalk group where the app is installed.",
      summary: "DingTalk needs app credentials from Stream mode.",
      steps: [
        "Create or choose a DingTalk app with Stream mode enabled.",
        "Add Client ID and Client Secret.",
        "Restart nanobot, then send a test message from DingTalk.",
      ],
      fields: [
        {
          key: "channels.dingtalk.clientId",
          label: "Client ID",
          placeholder: "DingTalk client ID",
          help: "Copy it from DingTalk app credentials.",
        },
        {
          key: "channels.dingtalk.clientSecret",
          label: "Client Secret",
          placeholder: "••••••",
          secret: true,
          help: "Copy it from the same DingTalk app credentials page.",
        },
        {
          key: "channels.dingtalk.allowFrom",
          label: "Allowed users",
          placeholder: "User IDs, comma separated",
          optional: true,
        },
      ],
    },
  },
  wecom: {
    displayName: "WeCom",
    description: "Use nanobot from WeCom work chats.",
    requirements: "WeCom app credentials and callback settings",
    initials: "WC",
    color: "#2F7DFF",
    logoUrl: "https://work.weixin.qq.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("wecom"),
      docsLabel: "Open WeCom setup",
      officialUrl: WECOM_DEVELOPER_URL,
      officialLabel: "Open WeCom console",
      tryIt: "Send a test message to the WeCom bot.",
      summary: "WeCom needs an AI bot ID and secret from the WeCom admin console.",
      steps: [
        "Create or choose a WeCom AI Bot.",
        "Add Bot ID and Secret.",
        "Restart nanobot, then send a test message from WeCom.",
      ],
      fields: [
        {
          key: "channels.wecom.botId",
          label: "Bot ID",
          placeholder: "WeCom bot ID",
          help: "Copy it from the WeCom AI Bot API mode page.",
        },
        {
          key: "channels.wecom.secret",
          label: "Secret",
          placeholder: "••••••",
          secret: true,
          help: "Keep the WeCom bot secret private.",
        },
        {
          key: "channels.wecom.allowFrom",
          label: "Allowed users",
          placeholder: "User IDs, comma separated",
          optional: true,
        },
      ],
    },
  },
  weixin: {
    displayName: "WeChat",
    description: "Use nanobot from WeChat conversations.",
    requirements: "WeChat channel setup and gateway",
    initials: "WX",
    color: "#07C160",
    logoUrl: "https://weixin.qq.com/favicon.ico",
    setup: {
      mode: "connect",
      primaryActionLabel: "Connect WeChat",
      command: "nanobot channels login weixin",
      docsUrl: chatAppGuideUrl("wechat"),
      docsLabel: "Open WeChat setup",
      tryIt: "After the QR login finishes, send a WeChat DM to the connected account.",
      summary: "WeChat signs in with a QR code and saves the account state locally.",
      steps: [
        "Click Connect and scan the QR code with WeChat.",
        "Keep the local gateway running while WeChat receives messages.",
        "Send a direct test message to confirm the account is connected.",
      ],
      manualFields: [
        {
          key: "channels.weixin.allowFrom",
          label: "Allowed users",
          placeholder: "User IDs, comma separated",
          optional: true,
        },
        {
          key: "channels.weixin.token",
          label: "Token",
          placeholder: "Saved by QR login",
          secret: true,
          optional: true,
        },
      ],
    },
  },
  qq: {
    displayName: "QQ",
    description: "Use nanobot from QQ chats.",
    requirements: "QQ bot credentials and gateway",
    initials: "QQ",
    color: "#12B7F5",
    logoUrl: "https://im.qq.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("qq"),
      docsLabel: "Open QQ setup",
      officialUrl: QQ_OPEN_PLATFORM_URL,
      officialLabel: "Open QQ bot console",
      tryIt: "Send a direct or group test message from QQ.",
      summary: "QQ uses the official bot credentials and a long WebSocket connection.",
      steps: [
        "Create or choose a QQ bot application and copy its App ID and Secret.",
        "Add appId and secret under channels.qq.",
        "Restart nanobot, then send a direct or group test message from QQ.",
      ],
      fields: [
        {
          key: "channels.qq.appId",
          label: "App ID",
          placeholder: "QQ bot app ID",
          help: "Copy it from QQ Open Platform.",
        },
        {
          key: "channels.qq.secret",
          label: "Secret",
          placeholder: "••••••",
          secret: true,
          help: "Save this before leaving the QQ credentials page.",
        },
        {
          key: "channels.qq.allowFrom",
          label: "Allowed users",
          placeholder: "Open IDs, comma separated",
          optional: true,
        },
        {
          key: "channels.qq.msgFormat",
          label: "Message format",
          defaultValue: "plain",
          options: QQ_MESSAGE_FORMAT_OPTIONS,
          optional: true,
        },
      ],
    },
  },
  signal: {
    displayName: "Signal",
    description: "Use nanobot from Signal messages.",
    requirements: "signal-cli HTTP daemon, phone number, allowlist",
    initials: "SG",
    color: "#3A76F0",
    logoUrl: "https://signal.org/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("signal"),
      docsLabel: "Open Signal setup",
      officialUrl: SIGNAL_CLI_URL,
      officialLabel: "Open signal-cli guide",
      tryIt: "Send a Signal DM to the linked phone number.",
      summary:
        "Signal connects through a local signal-cli HTTP daemon. Run the daemon first, then point nanobot at it.",
      steps: [
        "Register or link the Signal account in signal-cli.",
        "Start signal-cli in HTTP daemon mode for the same phone number.",
        "Set phoneNumber plus daemon host and port under channels.signal.",
        "Restart nanobot, then send a direct test message from Signal.",
      ],
      fields: [
        {
          key: "channels.signal.phoneNumber",
          label: "Phone number",
          placeholder: "+1234567890",
          help: "Use the Signal number registered with signal-cli.",
        },
        {
          key: "channels.signal.daemonHost",
          label: "Daemon host",
          placeholder: "localhost",
          optional: true,
        },
        {
          key: "channels.signal.daemonPort",
          label: "Daemon port",
          placeholder: "8080",
          inputType: "number",
          optional: true,
        },
        {
          key: "channels.signal.dm.allowFrom",
          label: "Allowed DMs",
          placeholder: "Phone numbers or UUIDs",
          optional: true,
        },
        {
          key: "channels.signal.group.allowFrom",
          label: "Allowed groups",
          placeholder: "Group IDs",
          optional: true,
        },
      ],
    },
  },
  msteams: {
    displayName: "Microsoft Teams",
    description: "Use nanobot from Microsoft Teams chats.",
    requirements: "Azure bot app credentials, public callback endpoint",
    initials: "MS",
    color: "#6264A7",
    logoUrl: "https://www.microsoft.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("msteams"),
      docsLabel: "Open Teams setup",
      officialUrl: TEAMS_DEVELOPER_URL,
      officialLabel: "Open Teams developer portal",
      tryIt: "Install the Teams app and send a test message.",
      summary:
        "Teams receives messages through the Bot Framework callback URL. It needs a reachable HTTPS endpoint in production.",
      steps: [
        "Create an Azure Bot / Teams app and copy the Microsoft App ID and client secret.",
        "Set the bot messaging endpoint to the nanobot Teams callback path.",
        "Add appId and appPassword under channels.msteams.",
        "Restart nanobot, then install the app in Teams and send a test message.",
      ],
      fields: [
        {
          key: "channels.msteams.appId",
          label: "App ID",
          placeholder: "Microsoft App ID",
          help: "Copy it from the Azure Bot or Teams app registration.",
        },
        {
          key: "channels.msteams.appPassword",
          label: "Client secret",
          placeholder: "••••••",
          secret: true,
          help: "Create a client secret for the Microsoft app.",
        },
        {
          key: "channels.msteams.tenantId",
          label: "Tenant ID",
          placeholder: "Optional tenant ID",
          optional: true,
        },
        {
          key: "channels.msteams.path",
          label: "Callback path",
          placeholder: "/api/messages",
          optional: true,
        },
        {
          key: "channels.msteams.allowFrom",
          label: "Allowed users",
          placeholder: "Teams user IDs, comma separated",
          optional: true,
        },
      ],
    },
  },
  napcat: {
    displayName: "NapCat",
    description: "Connect nanobot through a NapCat gateway.",
    requirements: "NapCat WebSocket endpoint, optional access token",
    initials: "NC",
    color: "#F97316",
    logoUrl: "https://napneko.github.io/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("napcat"),
      docsLabel: "Open NapCat setup",
      officialUrl: NAPCAT_DOCS_URL,
      officialLabel: "Open NapCat docs",
      tryIt: "Send a QQ test message through NapCat.",
      summary: "NapCat connects nanobot to QQ through a local or remote OneBot WebSocket endpoint.",
      steps: [
        "Start NapCat and enable its OneBot WebSocket server.",
        "Set wsUrl to the NapCat WebSocket endpoint; add accessToken if NapCat requires one.",
        "Restart nanobot, then send a QQ test message through NapCat.",
      ],
      fields: [
        {
          key: "channels.napcat.wsUrl",
          label: "WebSocket URL",
          placeholder: "ws://127.0.0.1:3001",
          help: "Use the Forward WebSocket URL from NapCat.",
        },
        {
          key: "channels.napcat.accessToken",
          label: "Access token",
          placeholder: "Optional token",
          secret: true,
          optional: true,
        },
        {
          key: "channels.napcat.groupPolicy",
          label: "Group behavior",
          defaultValue: "mention",
          options: GROUP_BEHAVIOR_OPTIONS,
          optional: true,
        },
        {
          key: "channels.napcat.allowFrom",
          label: "Allowed users",
          placeholder: "QQ IDs, comma separated",
          optional: true,
        },
      ],
    },
  },
};
