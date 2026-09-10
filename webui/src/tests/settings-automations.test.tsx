import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AutomationsSettings } from "@/components/settings/system/AutomationsSettings";
import i18n from "@/i18n";

afterEach(cleanup);

function renderAutomations(channel: string) {
  return render(
    <AutomationsSettings
      payload={{ jobs: [{
        id: "task-1",
        name: "Scheduled task",
        enabled: true,
        schedule: { kind: "every", every_ms: 60_000 },
        payload: { message: "Summarize updates" },
        state: {},
        origin: { channel },
      }] }}
      loading={false}
      query=""
      filter="all"
      sort="name"
      actionKey={null}
      error={null}
      onQueryChange={vi.fn()}
      onFilterChange={vi.fn()}
      onSortChange={vi.fn()}
      onAction={vi.fn()}
      onRequestEdit={vi.fn()}
      onRequestDelete={vi.fn()}
      onBackToChat={vi.fn()}
    />,
  );
}

describe("automation channel identity", () => {
  it("uses channel-owned names in the list and details when the language changes", async () => {
    renderAutomations("email");
    expect(screen.getAllByText("Email")).toHaveLength(2);

    for (const [locale, name] of [
      ["zh-CN", "电子邮件"],
      ["ja", "メール"],
      ["es", "Correo electrónico"],
    ]) {
      await act(() => i18n.changeLanguage(locale));
      expect(screen.getAllByText(name)).toHaveLength(2);
      expect(screen.queryByText("Email")).not.toBeInTheDocument();
    }
  });

  it("resolves aliases through the owning channel namespace", async () => {
    await i18n.changeLanguage("zh-CN");
    renderAutomations("wechat");
    expect(screen.getAllByText("微信")).toHaveLength(2);
  });

  it.each([
    ["api", "API"],
    ["cli", "CLI"],
    ["extension-chat", "extension-chat"],
  ])("preserves the label for %s", (channel, label) => {
    renderAutomations(channel);
    expect(screen.getAllByText(label)).toHaveLength(2);
  });
});
