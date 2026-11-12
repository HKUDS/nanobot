import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createPortal } from "react-dom";
import { describe, expect, it, vi } from "vitest";
import { ComposerUsagePopover } from "@/components/thread/ComposerUsagePopover";
import type { ContextSnapshot } from "@/lib/types";

const first: ContextSnapshot = { id: "1", contextWindowTokens: 10000, usage: { prompt_tokens: 1000 },
  graph: { nodes: [{ path: "/a.md", name: "a.md", state: "loaded", tokens: 100 }], edges: [] } };

describe("Context sidebar", () => {
  it("stays open while writing a message and updates the graph as new snapshots arrive", async () => {
    const user = userEvent.setup();
    const content = (snapshots: ContextSnapshot[]) => <><textarea aria-label="Message" />
      <ComposerUsagePopover context={null} rounds={[]} snapshots={snapshots} /></>;
    const view = render(content([first]));
    await user.click(screen.getByTestId("composer-context-usage"));
    const sidebar = screen.getByRole("complementary", { name: "Context usage" });
    await user.type(screen.getByRole("textbox"), "Continue reading");
    expect(sidebar).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("Continue reading");
    view.rerender(content([first, { ...first, id: "2", usage: { prompt_tokens: 2000 }, graph: {
      nodes: [...first.graph.nodes, { path: "/b.md", name: "b.md", state: "loaded", tokens: 200 }], edges: [],
    } }]));
    expect(await within(sidebar).findByRole("button", { name: "b.md" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    expect(screen.getByRole("textbox")).toHaveFocus();
    await user.click(within(sidebar).getByRole("button", { name: "Expand context panel" }));
    const expanded = await screen.findByRole("dialog", { name: "Context usage" });
    expect(within(expanded).getByRole("button", { name: "b.md" })).toBeInTheDocument();
    expect(within(expanded).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    await user.click(within(expanded).getByRole("button", { name: "Collapse context panel" }));
    expect(within(sidebar).getByRole("button", { name: "Expand context panel" })).toBeVisible();
    await user.click(screen.getByTestId("composer-context-usage"));
    await waitFor(() => expect(screen.getByTestId("composer-context-usage")).toHaveFocus());
  });

  it("closes the sidebar from its own control", async () => {
    const user = userEvent.setup();
    render(<ComposerUsagePopover context={null} rounds={[]} snapshots={[first]} />);
    await user.click(screen.getByTestId("composer-context-usage"));
    const sidebar = screen.getByRole("complementary", { name: "Context usage" });
    await user.click(within(sidebar).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("complementary")).not.toBeInTheDocument());
    expect(screen.getByTestId("composer-context-usage")).toHaveFocus();
  });

  it("mounts in the conversation's side slot and closes with Escape from its controls", async () => {
    const user = userEvent.setup();
    const host = document.createElement("section");
    Object.defineProperty(host, "clientWidth", { value: 900 });
    document.body.append(host);
    const view = render(<ComposerUsagePopover sidebarHost={host} context={null} rounds={[]} snapshots={[first]} />);
    await user.click(screen.getByTestId("composer-context-usage"));
    const sidebar = within(host).getByRole("complementary");
    act(() => within(sidebar).getByRole("button", { name: "Expand context panel" }).focus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByTestId("composer-context-usage")).toHaveFocus());
    expect(screen.getByTestId("composer-context-usage")).toHaveAttribute("aria-expanded", "false");
    view.unmount(); host.remove();
  });
  it("keeps the open sidebar and playback when its trigger moves between responsive slots", async () => {
    const user = userEvent.setup();
    const toolbar = document.createElement("span");
    const footer = document.createElement("span");
    document.body.append(toolbar, footer);
    const content = (host: HTMLElement) => <ComposerUsagePopover context={null} rounds={[]}
      snapshots={[first, { ...first, id: "2", usage: { prompt_tokens: 2000 } }]}>
      {(renderControl) => createPortal(renderControl?.({ showLabel: false, compactLabel: false }), host)}
    </ComposerUsagePopover>;
    const view = render(content(toolbar));
    await user.click(within(toolbar).getByTestId("composer-context-usage"));
    const sidebar = screen.getByRole("complementary");
    await user.click(within(sidebar).getByRole("button", { name: "Play context history" }));
    view.rerender(content(footer));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    expect(within(sidebar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    expect(within(footer).getByTestId("composer-context-usage")).toHaveAttribute("aria-expanded", "true");
    // happy-dom has no CSS timeline; model the real surface exit for this interruption.
    let finishExit!: () => void;
    const finished = new Promise<void>((resolve) => { finishExit = resolve; });
    Object.defineProperty(sidebar, "getAnimations", { value: vi.fn(() => [{ finished }]) });
    await user.click(within(footer).getByTestId("composer-context-usage"));
    expect(sidebar).toBeInTheDocument();
    expect(sidebar).toHaveAttribute("inert");
    expect(sidebar.style.getPropertyValue("--file-preview-slot-width")).toBe("0px");
    // Reopening during exit retains the graph instead of remounting it.
    await user.click(within(footer).getByTestId("composer-context-usage"));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    await user.click(within(footer).getByTestId("composer-context-usage"));
    await act(async () => finishExit());
    await waitFor(() => expect(screen.queryByRole("complementary")).not.toBeInTheDocument());
    view.unmount(); toolbar.remove(); footer.remove();
  });

  it("resets session playback without replacing the open sidebar", async () => {
    const user = userEvent.setup();
    const content = (sessionKey: string, snapshots: ContextSnapshot[]) => (
      <ComposerUsagePopover sessionKey={sessionKey} context={null} rounds={[]} snapshots={snapshots} />
    );
    const view = render(content("first-session", [first, { ...first, id: "2", usage: { prompt_tokens: 2000 } }]));
    await user.click(screen.getByTestId("composer-context-usage"));
    const sidebar = screen.getByRole("complementary");
    await within(sidebar).findByRole("button", { name: "a.md" });
    fireEvent.click(within(sidebar).getByRole("button", { name: "Play context history" }));
    expect(within(sidebar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    view.rerender(content("second-session", [{ ...first, id: "other", usage: { prompt_tokens: 3000 },
      graph: { nodes: [{ path: "/other.md", name: "other.md", state: "loaded", tokens: 300 }], edges: [] } }]));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    expect(within(sidebar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "30");
    expect(await within(sidebar).findByRole("button", { name: "other.md" })).toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: "a.md" })).not.toBeInTheDocument();
  });

  it("opens a pane-contained drawer with a visible close control on narrow panes", async () => {
    const user = userEvent.setup();
    const host = document.createElement("section");
    Object.defineProperty(host, "clientWidth", { value: 600 });
    document.body.append(host);
    const view = render(<ComposerUsagePopover sidebarHost={host} context={null} rounds={[]} snapshots={[first]} />);
    await user.click(screen.getByTestId("composer-context-usage"));
    const drawer = within(host).getByRole("dialog", { name: "Context usage" });
    await user.click(within(drawer).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("composer-context-usage")).toHaveFocus();
    view.unmount(); host.remove();
  });

});
