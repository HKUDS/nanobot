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
    document.body.append(host);
    const view = render(<ComposerUsagePopover sidebarHost={host} context={null} rounds={[]} snapshots={[first]} />);
    await user.click(screen.getByTestId("composer-context-usage"));
    const sidebar = within(host).getByRole("complementary");
    act(() => within(sidebar).getByRole("slider").focus());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.getByTestId("composer-context-usage")).toHaveFocus());
    expect(screen.getByTestId("composer-context-usage")).toHaveAttribute("aria-expanded", "false");
    view.unmount(); host.remove();
  });
});
