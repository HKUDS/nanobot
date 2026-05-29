import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { resources } from "@/i18n";
import { LOCALE_STORAGE_KEY, resolveInitialLocale } from "@/i18n/config";

const QUICK_ACTION_KEYS = ["plan", "analyze", "brainstorm", "code", "summarize", "more"];
const IMAGE_QUICK_ACTION_KEYS = ["icon", "sticker", "poster", "product", "portrait", "edit"];
const HERO_GREETING_KEYS = ["workOn", "start", "build", "tackle"];
const SLASH_COMMAND_KEYS = [
  "new",
  "stop",
  "restart",
  "status",
  "model",
  "history",
  "dream",
  "dream_log",
  "dream_restore",
  "goal",
  "help",
  "pairing",
];
const SETTINGS_NAV_KEYS = [
  "overview",
  "appearance",
  "models",
  "image",
  "browser",
  "apps",
  "runtime",
  "advanced",
];
function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function flattenResource(value: unknown, prefix = ""): Map<string, unknown> {
  const out = new Map<string, unknown>();
  if (!isRecord(value)) return out;
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isRecord(child)) {
      for (const [childPath, childValue] of flattenResource(child, path)) {
        out.set(childPath, childValue);
      }
    } else {
      out.set(path, child);
    }
  }
  return out;
}

function interpolationKeys(value: unknown): string[] {
  if (typeof value !== "string") return [];
  return Array.from(value.matchAll(/{{\s*([\w.-]+)\s*}}/g))
    .map((match) => match[1])
    .sort();
}

describe("webui i18n", () => {
  it("defaults to English until the user chooses another language", () => {
    localStorage.removeItem(LOCALE_STORAGE_KEY);
    expect(resolveInitialLocale()).toBe("en");

    localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
    expect(resolveInitialLocale()).toBe("zh-CN");
  });

  it("switches UI copy and document locale through the language switcher", async () => {
    const user = userEvent.setup();

    render(
      <>
        <LanguageSwitcher />
        <ThreadComposer onSend={vi.fn()} />
      </>,
    );

    expect(
      screen.getByPlaceholderText("Type your message…"),
    ).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en");

    await user.click(screen.getByRole("button", { name: "Change language" }));
    await user.click(screen.getByRole("menuitemradio", { name: /简体中文/i }));

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("zh-CN");
    });
    expect(localStorage.getItem("nanobot.locale")).toBe("zh-CN");
    expect(screen.getByPlaceholderText("输入消息…")).toBeInTheDocument();
  });

  it("updates the composer aria label when the language changes", async () => {
    render(<ThreadComposer onSend={vi.fn()} />);

    await act(async () => {
      const { setAppLanguage } = await import("@/i18n");
      await setAppLanguage("ja");
    });

    expect(screen.getByLabelText("メッセージ入力欄")).toBeInTheDocument();
  });

  it("keeps empty landing resources localized for every registered locale", () => {
    for (const resource of Object.values(resources)) {
      const empty = resource.common.thread.empty;
      for (const key of HERO_GREETING_KEYS) {
        expect(empty.greetings[key as keyof typeof empty.greetings]).toBeTruthy();
      }
      for (const key of QUICK_ACTION_KEYS) {
        const action = empty.quickActions[key as keyof typeof empty.quickActions];
        expect(action.title).toBeTruthy();
        expect(action.prompt).toBeTruthy();
      }
      for (const key of IMAGE_QUICK_ACTION_KEYS) {
        const action = empty.imageQuickActions[key as keyof typeof empty.imageQuickActions];
        expect(action.title).toBeTruthy();
        expect(action.prompt).toBeTruthy();
      }
    }
  });

  it("keeps every locale aligned with the English resource shape", () => {
    const reference = flattenResource(resources.en.common);
    for (const [locale, resource] of Object.entries(resources)) {
      if (locale === "en") continue;
      const current = flattenResource(resource.common);
      const missing = Array.from(reference.keys()).filter((key) => !current.has(key));
      const extra = Array.from(current.keys()).filter((key) => !reference.has(key));
      const interpolationMismatches = Array.from(reference.entries())
        .filter(([key]) => current.has(key))
        .filter(([key, value]) =>
          interpolationKeys(value).join(",") !== interpolationKeys(current.get(key)).join(",")
        )
        .map(([key]) => key);

      expect({ locale, missing, extra, interpolationMismatches }).toEqual({
        locale,
        missing: [],
        extra: [],
        interpolationMismatches: [],
      });
    }
  });

  it("keeps slash commands localized for every registered locale", () => {
    for (const resource of Object.values(resources)) {
      const slash = resource.common.thread.composer.slash;
      expect(slash.badges.current).toBeTruthy();
      expect(slash.badges.recent).toBeTruthy();
      expect(slash.details.goalActive).toBeTruthy();
      expect(slash.details.goalReady).toBeTruthy();
      expect(slash.details.history).toBeTruthy();
      expect(slash.details.stopRunning).toBeTruthy();
      for (const key of SLASH_COMMAND_KEYS) {
        const command = slash.commands[key as keyof typeof slash.commands];
        expect(command.title).toBeTruthy();
        expect(command.description).toBeTruthy();
      }
    }
  });

  it("keeps settings navigation localized for every registered locale", () => {
    for (const resource of Object.values(resources)) {
      const common = resource.common;
      expect(common.app.system.restarting).toBeTruthy();
      expect(common.sidebar.settings).toBeTruthy();
      expect(common.chat.showMore).toBeTruthy();
      expect(common.settings.sidebar.title).toBeTruthy();
      expect(common.settings.backToChat).toBeTruthy();
      for (const key of SETTINGS_NAV_KEYS) {
        expect(common.settings.nav[key as keyof typeof common.settings.nav]).toBeTruthy();
      }
      expect(common.settings.rows.theme).toBeTruthy();
      expect(common.settings.status.loading).toBeTruthy();
      expect(common.settings.actions.save).toBeTruthy();
      expect(common.settings.actions.edit).toBeTruthy();
      expect(common.settings.byok.configured).toBeTruthy();
      expect(common.settings.byok.configuredSection).toBeTruthy();
      expect(common.settings.byok.showMore).toBeTruthy();
      expect(common.settings.byok.apiKeyRequired).toBeTruthy();
      expect(common.settings.byok.showApiKey).toBeTruthy();
      expect(common.settings.byok.hideApiKey).toBeTruthy();
      expect(common.settings.byok.configuredKeyHint).toBeTruthy();
    }
  });

  it("keeps Simplified Chinese settings overview copy localized", () => {
    const settings = resources["zh-CN"].common.settings;

    expect(settings.nav.browser).toBe("网页");
    expect(settings.sections.webSearch).toBe("网页搜索");
    expect(settings.byok.tabs.webSearch).toBe("网页搜索");
    expect(settings.overview.webSearch).toBe("网页搜索");
    expect(settings.overview.workspace).toBe("工作区");
  });
});
