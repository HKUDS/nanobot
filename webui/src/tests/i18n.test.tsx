import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { resources } from "@/i18n";

const QUICK_ACTION_KEYS = ["plan", "analyze", "brainstorm", "code", "summarize", "more"];
const IMAGE_QUICK_ACTION_KEYS = ["icon", "sticker", "poster", "product", "portrait", "edit"];
const SETTINGS_NAV_KEYS = ["general", "byok"];

describe("webui i18n", () => {
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

  it("keeps welcome quick actions localized for every registered locale", () => {
    for (const resource of Object.values(resources)) {
      const empty = resource.common.thread.empty;
      expect(empty.greeting).toBeTruthy();
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

  it("keeps settings navigation localized for every registered locale", () => {
    for (const resource of Object.values(resources)) {
      const common = resource.common;
      expect(common.app.system.restarting).toBeTruthy();
      expect(common.sidebar.settings).toBeTruthy();
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
});
