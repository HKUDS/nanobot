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
      "message.fallbackResponse",
      "thread.composer.fallbackNotice", "thread.composer.checkModelSettings",
      "thread.composer.reauthNotice", "thread.composer.reauthFallback", "thread.composer.reauthSettings",
    ]) {
      expect(i18n.exists(key), key).toBe(true);
      expect(i18n.t(key), key).not.toBe(key);
    }
  });

  it("uses one Chinese work-status vocabulary with and without duration", async () => {
    const i18n = createInstance();
    await i18n.init({
      lng: "zh-CN",
      fallbackLng: false,
      resources: { "zh-CN": { translation: zhCN } },
    });

    expect(i18n.t("message.activityWorkingFor", { duration: "15s" })).toBe("处理中 15s");
    expect(i18n.t("message.activityWorked")).toBe("已处理");
    expect(i18n.t("message.activityWorkedFor", { duration: "15s" })).toBe("已处理 15s");
    expect(i18n.t("message.activityShowFor", { duration: "15s" })).toBe("查看过程 15s");
    expect(i18n.t("message.activityHide")).toBe("收起过程");
  });
});
