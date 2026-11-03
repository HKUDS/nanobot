import { useTranslation } from "react-i18next";

import i18n, { initializeI18n } from "@/i18n";
import { supportedLocales } from "@/i18n/config";

const bundles = import.meta.glob<{ default: Record<string, unknown> }>(
  "./locales/*/*.json",
  { eager: true },
);

export async function initializeGalleryI18n(): Promise<void> {
  await initializeI18n();
  for (const { code } of supportedLocales) {
    for (const [path, bundle] of Object.entries(bundles)) {
      const match = path.match(/^\.\/locales\/([^/]+)\/([^/]+)\.json$/);
      if (match?.[2] === code) {
        i18n.addResourceBundle(code, "gallery", { [match[1]]: bundle.default }, true, true);
      }
    }
  }
}

export function useGalleryTranslation() {
  return useTranslation("gallery");
}
