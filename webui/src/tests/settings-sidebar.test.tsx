import { useState, type ComponentProps } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SettingsSidebar } from "@/components/settings/SettingsSidebar";
import {
  installSettingsViewTestHooks,
  renderSettingsView,
  settingsPayload,
} from "@/tests/settings-test-utils";

function mockMobileMedia(initial = true) {
  const target = new EventTarget();
  const media = {
    matches: initial,
    media: "(max-width: 1023px)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return (matches: boolean) => act(() => {
    media.matches = matches;
    target.dispatchEvent(new Event("change"));
  });
}

function Sidebar(props: Partial<ComponentProps<typeof SettingsSidebar>>) {
  const [section, setSection] = useState(props.activeSection ?? "models");
  return <SettingsSidebar activeSection={section} onSelectSection={setSection}
    onBackToChat={() => {}} {...props} />;
}

describe("Settings navigation on mobile", () => {
  installSettingsViewTestHooks();

  it("keeps the single-row header and opens a section menu beneath its title", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    const restart = vi.fn();
    const back = vi.fn();
    render(<Sidebar onRestart={restart} onBackToChat={back} />);
    const header = screen.getByRole("complementary");
    expect(within(header).getAllByRole("button")).toHaveLength(2);
    const trigger = screen.getByRole("button", { name: "Settings: Models" });
    await user.click(trigger);
    const menu = screen.getByRole("menu", { name: "Settings sections" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(menu).toHaveAttribute("data-side", "bottom");
    expect(within(menu).getByRole("menuitem", { name: "Models", exact: true }))
      .toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("menuitem", { name: "Restart" })).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    await user.click(within(menu).getByRole("menuitem", { name: "Appearance" }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Settings: Appearance" })).toHaveFocus();
    expect(document.body.style.pointerEvents).not.toBe("none");
    expect(restart).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(back).toHaveBeenCalledOnce();
  });

  it("treats capability subpages as the same navigation section", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    render(<Sidebar activeSection="image" />);
    await user.click(screen.getByRole("button", { name: "Settings: Capabilities" }));
    expect(screen.getByRole("menuitem", { name: "Capabilities", exact: true }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("menuitem", { name: "Restart" })).not.toBeInTheDocument();
  });

  it.each(["trigger", "escape"])("dismisses with %s and restores focus without locking the page", async (method) => {
    mockMobileMedia();
    const user = userEvent.setup();
    render(<Sidebar />);
    const trigger = screen.getByRole("button", { name: "Settings: Models" });
    await user.click(trigger);
    expect(document.body.style.pointerEvents).not.toBe("none");
    if (method === "trigger") await user.click(trigger);
    else await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("dismisses on an outside click without swallowing the back action", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    const back = vi.fn();
    render(<Sidebar onBackToChat={back} />);
    await user.click(screen.getByRole("button", { name: "Settings: Models" }));
    const backButton = screen.getByRole("button", { name: "Back to chat" });
    await user.click(backButton);
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(back).toHaveBeenCalledOnce();
    expect(backButton).toHaveFocus();
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("supports keyboard section selection", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    render(<Sidebar />);
    screen.getByRole("button", { name: "Settings: Models" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Overview", exact: true })).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Settings: Appearance" })).toHaveFocus();
  });

  it("opens and selects sections with touch taps", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    render(<Sidebar />);
    const tap = (target: HTMLElement) => user.pointer([
      { keys: "[TouchA>]", target }, { keys: "[/TouchA]", target },
    ]);
    await tap(screen.getByRole("button", { name: "Settings: Models" }));
    await tap(screen.getByRole("menuitem", { name: "System", exact: true }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Settings: System" })).toBeVisible();
  });

  it("keeps manual restart in the menu and closes it on selection", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    const restart = vi.fn();
    render(<Sidebar onRestart={restart} />);
    expect(screen.queryByRole("button", { name: "Restart" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Settings: Models" }));
    await user.click(screen.getByRole("menuitem", { name: "Restart" }));
    expect(restart).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(document.body.style.pointerEvents).not.toBe("none");
  });

  it("shows pending changes inline, disables restart while running, and clears the prompt after restart", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    const restart = vi.fn();
    const { rerender } = render(<Sidebar onRestart={restart} restartPending />);
    expect(screen.getByRole("status")).toHaveTextContent("Saved. Restart to apply changes.");
    await user.click(screen.getByRole("button", { name: "Restart", exact: true }));
    expect(restart).toHaveBeenCalledOnce();
    rerender(<Sidebar onRestart={restart} restartPending isRestarting />);
    const runningLabel = screen.getByRole("status").textContent!;
    expect(screen.getByRole("button", { name: runningLabel, exact: true })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Settings: Models" }));
    expect(within(screen.getByRole("menu")).getByRole("menuitem", { name: runningLabel }))
      .toHaveAttribute("aria-disabled", "true");
    await user.keyboard("{Escape}");
    rerender(<Sidebar onRestart={restart} restartPending={false} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restart" })).not.toBeInTheDocument();
  });

  it("dismisses the open menu when crossing to desktop and does not reopen on return", async () => {
    const resize = mockMobileMedia();
    const user = userEvent.setup();
    const restart = vi.fn();
    render(<Sidebar onRestart={restart} />);
    await user.click(screen.getByRole("button", { name: "Settings: Models" }));
    resize(false);
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(document.body.style.pointerEvents).not.toBe("none");
    expect(screen.queryByRole("button", { name: "Settings: Models" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Models", exact: true })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Restart" }));
    expect(restart).toHaveBeenCalledOnce();
    resize(true);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings: Models" })).toBeVisible();
  });

  it("still asks before leaving saved changes that need a restart", async () => {
    mockMobileMedia();
    const user = userEvent.setup();
    const back = vi.fn();
    renderSettingsView({ initialSection: "models", initialSettings: {
      ...settingsPayload(), requires_restart: true,
    }, onBackToChat: back });
    await user.click(screen.getByRole("button", { name: "Settings: Models" }));
    await user.click(screen.getByRole("menuitem", { name: "Appearance", exact: true }));
    await user.click(screen.getByRole("button", { name: "Back to chat" }));
    const dialog = screen.getByRole("dialog", { name: "Restart before leaving?" });
    expect(back).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Restart later" }));
    expect(back).toHaveBeenCalledOnce();
    await waitFor(() => expect(document.body.style.pointerEvents).not.toBe("none"));
  });
});
