import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";

import en from "@/i18n/locales/en/common.json";
import zhCN from "@/i18n/locales/zh-CN/common.json";

describe("chat translation resources", () => {
  it.each([
    ["en", en],
    ["zh-CN", zhCN],
  ] as const)("resolves sidebar labels from the chat namespace in %s", async (lng, common) => {
    const i18n = createInstance();
    await i18n.init({ lng, fallbackLng: false, resources: { [lng]: { translation: common } } });

    for (const key of [
      "chat.groups.all", "chat.groups.projects", "chat.newChat",
      "chat.fallbackTitle", "chat.activity.running", "chat.rename", "chat.loading",
    ]) {
      expect(i18n.exists(key), key).toBe(true);
      expect(i18n.t(key), key).not.toBe(key);
    }
  });
});
