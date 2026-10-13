import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AutomationsSettings } from "@/components/settings/system/AutomationsSettings";
import i18n from "@/i18n";

afterEach(cleanup);

function renderAutomationDetail(channel: string) {
  render(
    <AutomationsSettings
      payload={{ jobs: [{
        id: "task-1",
        name: "Scheduled task",
        enabled: true,
        schedule: { kind: "every", every_ms: 60_000 },
        payload: { message: "Summarize updates" },
        state: { next_run_at_ms: Date.now() + 60_000 },
        origin: { channel },
      }] }}
      loading={false}
      filter="all"
      actionKey={null}
      error={null}
      onFilterChange={vi.fn()}
      onAction={vi.fn()}
      onRequestEdit={vi.fn()}
      onRequestDelete={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Scheduled task/ }));
  return within(screen.getByRole("dialog", { name: "Scheduled task" }));
}

describe("automation channel identity", () => {
  it("uses channel-owned names in the detail when the language changes", async () => {
    const detail = renderAutomationDetail("email");
    expect(detail.getByText("Email")).toBeVisible();

    for (const [locale, name] of [
      ["zh-CN", "电子邮件"],
      ["ja", "メール"],
      ["es", "Correo electrónico"],
    ]) {
      await act(() => i18n.changeLanguage(locale));
      expect(detail.getByText(name)).toBeVisible();
      expect(detail.queryByText("Email")).not.toBeInTheDocument();
    }
  });

  it("resolves aliases through the owning channel namespace", async () => {
    await i18n.changeLanguage("zh-CN");
    const detail = renderAutomationDetail("wechat");
    expect(detail.getByText("微信")).toBeVisible();
  });

  it.each([
    ["api", "API"],
    ["cli", "CLI"],
    ["extension-chat", "extension-chat"],
  ])("preserves the label for %s", (channel, label) => {
    const detail = renderAutomationDetail(channel);
    expect(detail.getByText(label)).toBeVisible();
  });
});
