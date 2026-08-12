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
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("email"),
      presets: EMAIL_PROVIDER_PRESETS,
      fields: [
        { key: "channels.email.consentGranted", section: "account" },
        { key: "channels.email.imapHost", section: "receiving" },
        { key: "channels.email.imapUsername", section: "receiving" },
        { key: "channels.email.imapPassword", section: "receiving" },
        { key: "channels.email.imapPort", section: "receiving" },
        { key: "channels.email.smtpHost", section: "sending" },
        { key: "channels.email.smtpUsername", section: "sending" },
        { key: "channels.email.smtpPassword", section: "sending" },
        { key: "channels.email.smtpPort", section: "sending" },
        { key: "channels.email.fromAddress", section: "sending" },
        { key: "channels.email.pollIntervalSeconds", section: "behavior" },
        { key: "channels.email.allowFrom", section: "access" },
        { key: "channels.email.verifyDkim", section: "security" },
        { key: "channels.email.verifySpf", section: "security" },
      ],
    },
  },
} satisfies ChannelUiContribution;
