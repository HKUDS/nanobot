import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
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
    const content = (host: HTMLElement) => <ComposerUsagePopover triggerHost={host} context={null} rounds={[]}
      snapshots={[first, { ...first, id: "2", usage: { prompt_tokens: 2000 } }]} />;
    const view = render(content(toolbar));
    await user.click(within(toolbar).getByTestId("composer-context-usage"));
    const sidebar = screen.getByRole("complementary");
    await user.click(within(sidebar).getByRole("button", { name: "Play context history" }));
    view.rerender(content(footer));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    expect(within(sidebar).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    expect(within(footer).getByTestId("composer-context-usage")).toHaveAttribute("aria-expanded", "true");
    await user.click(within(footer).getByTestId("composer-context-usage"));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    expect(sidebar.style.getPropertyValue("--file-preview-slot-width")).toBe("0px");
    // Reopening during exit retains the graph instead of remounting it.
    await user.click(within(footer).getByTestId("composer-context-usage"));
    expect(screen.getByRole("complementary")).toBe(sidebar);
    await user.click(within(footer).getByTestId("composer-context-usage"));
    await waitFor(() => expect(screen.queryByRole("complementary")).not.toBeInTheDocument());
    view.unmount(); toolbar.remove(); footer.remove();
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
