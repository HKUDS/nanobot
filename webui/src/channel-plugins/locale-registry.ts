import type { ChannelMessages } from "@/channel-plugins/i18n";
import { channelNamespace } from "@/channel-plugins/i18n";
import {
  supportedLocales,
  type SupportedLocale,
} from "@/i18n/config";

type ChannelMessagesModule = {
  default?: ChannelMessages;
};

type ChannelMessagesLoader = () => Promise<ChannelMessagesModule>;

const modules = import.meta.glob<ChannelMessagesModule>(
  "../../../nanobot/channels/*/webui/locales/*.json",
);

const loadersByChannel = new Map<
  string,
  Map<SupportedLocale, ChannelMessagesLoader>
>();
const translationsByChannel = new Map<string, Map<SupportedLocale, ChannelMessages>>();
const supportedLocaleCodes = new Set<string>(supportedLocales.map(({ code }) => code));

for (const [modulePath, loader] of Object.entries(modules)) {
  const match = modulePath.match(/nanobot\/channels\/([^/]+)\/webui\/locales\/([^/]+)\.json$/);
  if (!match) {
    throw new Error(`Cannot derive channel locale identity from '${modulePath}'`);
  }
  const [, channel, locale] = match;
  if (!supportedLocaleCodes.has(locale)) {
    throw new Error(`Channel '${channel}' has unsupported locale '${locale}'`);
  }
  const loaders = loadersByChannel.get(channel) ?? new Map();
  if (loaders.has(locale as SupportedLocale)) {
    throw new Error(`Channel '${channel}' registers locale '${locale}' more than once`);
  }
  loaders.set(locale as SupportedLocale, loader);
  loadersByChannel.set(channel, loaders);
}

export function channelLocaleNamespaces(): string[] {
  return [...loadersByChannel.keys()].map(channelNamespace);
}

export async function channelLocaleResources(
  locale: SupportedLocale,
): Promise<Record<string, ChannelMessages>> {
  return Object.fromEntries(await Promise.all(
    [...loadersByChannel.keys()].map(async (channel) => [
      channelNamespace(channel),
      await loadChannelLocale(channel, locale),
    ]),
  ));
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

async function loadChannelLocale(
  channel: string,
  locale: SupportedLocale,
): Promise<ChannelMessages> {
  // Get-or-create the shared per-channel map synchronously so concurrent locale
  // loads append to one Map instead of replacing each other's registration.
  let translations = translationsByChannel.get(channel);
  if (!translations) {
    translations = new Map();
    translationsByChannel.set(channel, translations);
  }
  const loaded = translations.get(locale);
  if (loaded) return loaded;

  const loaders = loadersByChannel.get(channel);
  const loader = loaders?.get(locale) ?? loaders?.get("en");
  if (!loader) {
    throw new Error(`Channel '${channel}' has no locale loader for '${locale}' or 'en'`);
  }
  const messages = (await loader()).default;
  if (!messages) {
    throw new Error(`Channel '${channel}' locale '${locale}' has no default export`);
  }
  translations.set(locale, messages);
  return messages;
}
