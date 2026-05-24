import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import {
  applyDocumentLocale,
  defaultLocale,
  fallbackLocale,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  persistLocale,
  resolveInitialLocale,
  type SupportedLocale,
} from "./config";

import enCommon from "./locales/en/common.json";
import zhCNCommon from "./locales/zh-CN/common.json";
import zhTWCommon from "./locales/zh-TW/common.json";
import frCommon from "./locales/fr/common.json";
import jaCommon from "./locales/ja/common.json";
import koCommon from "./locales/ko/common.json";
import esCommon from "./locales/es/common.json";
import viCommon from "./locales/vi/common.json";
import idCommon from "./locales/id/common.json";

export const resources = {
  en: { common: enCommon },
  "zh-CN": { common: zhCNCommon },
  "zh-TW": { common: zhTWCommon },
  fr: { common: frCommon },
  ja: { common: jaCommon },
  ko: { common: koCommon },
  es: { common: esCommon },
  vi: { common: viCommon },
  id: { common: idCommon },
} as const;

export function currentLocale(): SupportedLocale {
  return normalizeLocale(i18n.resolvedLanguage ?? i18n.language ?? defaultLocale);
}

export async function setAppLanguage(locale: SupportedLocale): Promise<void> {
  await i18n.changeLanguage(locale);
}

if (!i18n.isInitialized) {
  void i18n
    .use(initReactI18next)
    .init({
      resources,
      lng: resolveInitialLocale(),
      fallbackLng: fallbackLocale,
      defaultNS: "common",
      ns: ["common"],
      interpolation: {
        escapeValue: false,
      },
      returnNull: false,
      supportedLngs: Object.keys(resources),
    });
}

const syncLocaleSideEffects = (language: string) => {
  const locale = normalizeLocale(language);
  applyDocumentLocale(locale);
  persistLocale(locale);
};

syncLocaleSideEffects(currentLocale());
i18n.on("languageChanged", syncLocaleSideEffects);

export { LOCALE_STORAGE_KEY };
export default i18n;
