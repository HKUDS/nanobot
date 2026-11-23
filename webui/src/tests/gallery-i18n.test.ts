import { beforeAll, expect, it } from "vitest";

import i18n from "@/i18n";
import { supportedLocales } from "@/i18n/config";
import { examples } from "@/dev/gallery/Gallery";
import { initializeGalleryI18n } from "@/dev/gallery/i18n";

type Copy = { [key: string]: string | Copy };
const bundles = import.meta.glob<{ default: Copy }>("../dev/gallery/locales/*/*.json", { eager: true });

function strings(copy: Copy, prefix = ""): Record<string, string> {
  return Object.fromEntries(Object.entries(copy).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [[path, value]] : Object.entries(strings(value, path));
  }));
}

function placeholders(text: string): string[] {
  return (text.match(/{{\s*[^{}]+\s*}}/g) ?? []).sort();
}

beforeAll(initializeGalleryI18n);

it("provides complete gallery copy and interpolation variables in every supported locale", () => {
  for (const domain of ["ui", "controls", "previews"]) {
    const english = strings(bundles[`../dev/gallery/locales/${domain}/en.json`].default);
    for (const { code } of supportedLocales) {
      const copy = strings(bundles[`../dev/gallery/locales/${domain}/${code}.json`].default);
      expect(Object.keys(copy).sort(), `${domain}/${code}`).toEqual(Object.keys(english).sort());
      for (const [key, text] of Object.entries(copy)) {
        expect(text.trim(), `${domain}/${code}/${key}`).not.toBe("");
        expect(placeholders(text), `${domain}/${code}/${key}`).toEqual(placeholders(english[key]));
        expect(i18n.getResource(code, "gallery", `${domain}.${key}`)).toBe(text);
      }
    }
  }
});

it("resolves every example's title and usage notes directly from each locale", () => {
  for (const { code } of supportedLocales) {
    for (const example of examples) {
      for (const key of [example.title, example.description, example.options]) {
        expect(i18n.getResource(code, "gallery", key), `${code}/${key}`).toBeTypeOf("string");
      }
    }
  }
});
