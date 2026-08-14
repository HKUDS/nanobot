import type { ChannelUiContribution } from "@/channel-plugins/types";
import {
  type ChannelProviderPresetDefinition,
  chatAppGuideUrl,
} from "@/components/settings/channels/catalog";

const EMAIL_PROVIDER_PRESETS: ChannelProviderPresetDefinition[] = [
  {
    id: "gmail",
    values: {
      "channels.email.imapHost": "imap.gmail.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.gmail.com",
      "channels.email.smtpPort": "587",
    },
  },
  {
    id: "outlook",
    values: {
      "channels.email.imapHost": "outlook.office365.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.office365.com",
      "channels.email.smtpPort": "587",
    },
  },
  {
    id: "icloud",
    values: {
      "channels.email.imapHost": "imap.mail.me.com",
      "channels.email.imapPort": "993",
      "channels.email.smtpHost": "smtp.mail.me.com",
      "channels.email.smtpPort": "587",
    },
  },
  { id: "custom", values: {} },
];

export default {
  presentation: {
    displayName: "Email",
    initials: "EM",
    color: "#64748B",
    logoUrl: "https://gmail.com/favicon.ico",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("email"),
      presets: EMAIL_PROVIDER_PRESETS,
      fields: [
        { key: "channels.email.consentGranted" },
        { key: "channels.email.imapHost" },
        { key: "channels.email.imapUsername" },
        { key: "channels.email.imapPassword" },
        { key: "channels.email.smtpHost" },
        { key: "channels.email.smtpUsername" },
        { key: "channels.email.smtpPassword" },
        { key: "channels.email.imapPort" },
        { key: "channels.email.smtpPort" },
        { key: "channels.email.fromAddress" },
        { key: "channels.email.pollIntervalSeconds" },
        { key: "channels.email.allowFrom" },
        { key: "channels.email.verifyDkim" },
        { key: "channels.email.verifySpf" },
      ],
    },
  },
} satisfies ChannelUiContribution;
