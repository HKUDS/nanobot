import i18n, { type InitOptions } from "i18next";
import { initReactI18next } from "react-i18next";

import {
  channelLocaleNamespaces,
  channelLocaleResources,
} from "@/channel-plugins/locale-registry";

import {
  applyDocumentLocale,
  defaultLocale,
  fallbackLocale,
  normalizeLocale,
  persistLocale,
  resolveInitialLocale,
  supportedLocales,
  type SupportedLocale,
} from "./config";

type CommonMessages = typeof import("./locales/en/common.json");
type CommonMessagesModule = { default: CommonMessages };
type LocaleResource = { common: CommonMessages } & Record<string, unknown>;

const commonModules = import.meta.glob<CommonMessagesModule>(
  "./locales/*/common.json",
);
const commonLoaders = new Map<SupportedLocale, () => Promise<CommonMessagesModule>>();
const resourcePromises = new Map<SupportedLocale, Promise<LocaleResource>>();
const supportedLocaleCodes = new Set<string>(supportedLocales.map(({ code }) => code));

for (const [modulePath, loader] of Object.entries(commonModules)) {
  const match = modulePath.match(/locales\/([^/]+)\/common\.json$/);
  if (!match || !supportedLocaleCodes.has(match[1])) continue;
  commonLoaders.set(match[1] as SupportedLocale, loader);
}

// Tests and validation tooling inspect this registry after explicitly loading
// every locale. Production startup populates only the current and fallback
// entries, keeping all other translation JSON out of the initial graph.
export const resources = {} as Record<SupportedLocale, LocaleResource>;

let initialization: Promise<typeof i18n> | undefined;
let localeListenerBound = false;

export function currentLocale(): SupportedLocale {
  return normalizeLocale(i18n.resolvedLanguage ?? i18n.language ?? defaultLocale);
}

async function loadLocaleResources(
  locale: SupportedLocale,
): Promise<LocaleResource> {
  const existing = resourcePromises.get(locale);
  if (existing) return existing;

  const loader = commonLoaders.get(locale);
  if (!loader) throw new Error(`No common locale loader registered for '${locale}'`);

  const pending = Promise.all([loader(), channelLocaleResources(locale)])
    .then(([common, channels]) => {
      const resource: LocaleResource = { common: common.default, ...channels };
      resources[locale] = resource;
      if (i18n.isInitialized) {
        for (const [namespace, messages] of Object.entries(resource)) {
          i18n.addResourceBundle(locale, namespace, messages, true, true);
        }
      }
      return resource;
    })
    .catch((error) => {
      resourcePromises.delete(locale);
      throw error;
    });
  resourcePromises.set(locale, pending);
  return pending;
}

export async function loadAllLocaleResources(): Promise<void> {
  await Promise.all(supportedLocales.map(({ code }) => loadLocaleResources(code)));
}

export async function initializeI18n(): Promise<typeof i18n> {
  if (i18n.isInitialized) return i18n;
  if (initialization) return initialization;

  initialization = (async () => {
    const initialLocale = resolveInitialLocale();
    const startupLocales = initialLocale === fallbackLocale
      ? [fallbackLocale]
      : [fallbackLocale, initialLocale];
    await Promise.all(startupLocales.map(loadLocaleResources));
    await i18n
      .use(initReactI18next)
      .init({
        resources: Object.fromEntries(
          startupLocales.map((locale) => [locale, resources[locale]]),
        ) as InitOptions["resources"],
        lng: initialLocale,
        fallbackLng: fallbackLocale,
        defaultNS: "common",
        ns: ["common", ...channelLocaleNamespaces()],
        interpolation: {
          escapeValue: false,
        },
        returnNull: false,
        supportedLngs: supportedLocales.map(({ code }) => code),
      });

    syncLocaleSideEffects(currentLocale());
    if (!localeListenerBound) {
      i18n.on("languageChanged", syncLocaleSideEffects);
      localeListenerBound = true;
    }
    return i18n;
  })().catch((error) => {
    initialization = undefined;
    throw error;
  });
  return initialization;
}

export async function setAppLanguage(locale: SupportedLocale): Promise<void> {
  await initializeI18n();
  await loadLocaleResources(locale);
  await i18n.changeLanguage(locale);
}

function syncLocaleSideEffects(language: string) {
  const locale = normalizeLocale(language);
  applyDocumentLocale(locale);
  persistLocale(locale);
}

export default i18n;
