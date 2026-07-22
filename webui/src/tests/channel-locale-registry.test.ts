import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { channelFieldMessageKey } from "@/channel-plugins/i18n";
import { registeredChannelLocales } from "@/channel-plugins/locale-registry";
import { registeredChannelUiContributions } from "@/channel-plugins/registry";
import { supportedLocales } from "@/i18n/config";

const expectedChannels = [
  "dingtalk",
  "discord",
  "email",
  "feishu",
  "matrix",
  "mattermost",
  "msteams",
  "napcat",
  "qq",
  "signal",
  "slack",
  "telegram",
  "websocket",
  "wecom",
  "weixin",
  "whatsapp",
];

function flatten(value: unknown, prefix = ""): Map<string, string> {
  const entries = new Map<string, string>();
  if (typeof value === "string") {
    entries.set(prefix, value);
    return entries;
  }
  if (!value || typeof value !== "object") return entries;

  for (const [key, child] of Object.entries(value)) {
    if (!prefix && key === "displayName") continue;
    const childPrefix = prefix ? `${prefix}.${key}` : key;
    for (const [childKey, text] of flatten(child, childPrefix)) {
      entries.set(childKey, text);
    }
  }
  return entries;
}

function interpolationKeys(value: string): string[] {
  return [...value.matchAll(/{{\s*([\w.-]+)\s*}}/g)]
    .map((match) => match[1])
    .sort();
}

describe("channel locale registry", () => {
  it("loads every supported locale from every built-in channel package", () => {
    const registrations = registeredChannelLocales();
    expect([...registrations.keys()].sort()).toEqual(expectedChannels);

    for (const [channel, locales] of registrations) {
      expect([...locales.keys()].sort()).toEqual(
        supportedLocales.map(({ code }) => code).sort(),
      );

      const english = flatten(locales.get("en"));
      for (const [locale, messages] of locales) {
        const translated = flatten(messages);
        expect([...translated.keys()].sort(), `${channel}/${locale} message keys`).toEqual(
          [...english.keys()].sort(),
        );
        for (const [key, source] of english) {
          expect(
            interpolationKeys(translated.get(key) ?? ""),
            `${channel}/${locale}:${key} interpolation keys`,
          ).toEqual(interpolationKeys(source));
        }
      }
    }
  });

  it("keeps structural UI definitions aligned with English locale keys", () => {
    const locales = registeredChannelLocales();
    for (const { channel, contribution } of registeredChannelUiContributions()) {
      const messages = locales.get(channel)?.get("en");
      expect(messages, `${channel} English messages`).toBeDefined();

      const setup = contribution.presentation.setup;
      for (const field of [...(setup?.fields ?? []), ...(setup?.manualFields ?? [])]) {
        const messageKey = channelFieldMessageKey(channel, field.key);
        expect(messages?.setup.fields?.[messageKey], `${channel} field ${messageKey}`).toBeDefined();
      }
      for (const action of setup?.actions ?? []) {
        expect(messages?.setup.actions?.[action.id], `${channel} action ${action.id}`).toBeTypeOf("string");
      }
      for (const preset of setup?.presets ?? []) {
        expect(messages?.setup.presets?.[preset.id], `${channel} preset ${preset.id}`).toBeTypeOf("string");
      }
    }
  });

  it("keeps i18n initialization independent from channel React modules", () => {
    const localeRegistry = readFileSync(
      resolve(process.cwd(), "src/channel-plugins/locale-registry.ts"),
      "utf8",
    );
    const i18nEntry = readFileSync(resolve(process.cwd(), "src/i18n/index.ts"), "utf8");

    expect(localeRegistry).toContain("webui/locales/*.json");
    expect(localeRegistry).not.toMatch(/channel-plugins\/registry|\.tsx|\breact\b/i);
    expect(i18nEntry).toContain("channel-plugins/locale-registry");
    expect(i18nEntry).not.toContain("channel-plugins/registry");
  });
});
