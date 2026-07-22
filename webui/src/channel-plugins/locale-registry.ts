import type { ChannelMessages } from "@/channel-plugins/i18n";
import { channelNamespace } from "@/channel-plugins/i18n";
import {
  supportedLocales,
  type SupportedLocale,
} from "@/i18n/config";

type ChannelMessagesModule = {
  default?: ChannelMessages;
};

const modules = import.meta.glob<ChannelMessagesModule>(
  "../../../nanobot/channels/*/webui/locales/*.json",
  { eager: true },
);

const translationsByChannel = new Map<string, Map<SupportedLocale, ChannelMessages>>();
const supportedLocaleCodes = new Set<string>(supportedLocales.map(({ code }) => code));

for (const [modulePath, module] of Object.entries(modules)) {
  const messages = module.default;
  if (!messages) continue;
  const match = modulePath.match(/nanobot\/channels\/([^/]+)\/webui\/locales\/([^/]+)\.json$/);
  if (!match) {
    throw new Error(`Cannot derive channel locale identity from '${modulePath}'`);
  }
  const [, channel, locale] = match;
  if (!supportedLocaleCodes.has(locale)) {
    throw new Error(`Channel '${channel}' has unsupported locale '${locale}'`);
  }
  const translations = translationsByChannel.get(channel) ?? new Map();
  if (translations.has(locale as SupportedLocale)) {
    throw new Error(`Channel '${channel}' registers locale '${locale}' more than once`);
  }
  translations.set(locale as SupportedLocale, messages);
  translationsByChannel.set(channel, translations);
}

export function channelLocaleNamespaces(): string[] {
  return [...translationsByChannel.keys()].map(channelNamespace);
}

export function channelLocaleResources(locale: SupportedLocale): Record<string, unknown> {
  return Object.fromEntries(
    [...translationsByChannel.keys()].map((channel) => [
      channelNamespace(channel),
      channelLocaleMessages(channel, locale) ?? {},
    ]),
  );
}

export function channelLocaleMessages(
  channel: string,
  locale: SupportedLocale,
): ChannelMessages | undefined {
  const translations = translationsByChannel.get(channel);
  return translations?.get(locale) ?? translations?.get("en");
}

export function registeredChannelLocales(): ReadonlyMap<
  string,
  ReadonlyMap<SupportedLocale, ChannelMessages>
> {
  return translationsByChannel;
}
