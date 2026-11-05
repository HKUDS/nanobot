import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContextInspector } from "@/components/thread/ContextInspector";
import type { ContextSnapshot } from "@/lib/types";

const snapshots: ContextSnapshot[] = [
  { id: "first", contextWindowTokens: 10000, usage: { prompt_tokens: 1000 }, graph: {
    nodes: [{ path: "/a.md", name: "a.md", state: "loaded", tokens: 100 }], edges: [],
  } },
  { id: "second", contextWindowTokens: 10000, usage: { prompt_tokens: 2000, cached_tokens: 800 }, graph: {
    nodes: [{ path: "/a.md", name: "a.md", state: "loaded", tokens: 100 }, { path: "/b.md", name: "b.md", state: "discovered", tokens: 0 }],
    edges: [{ source: "/a.md", target: "/b.md" }],
  } },
];

describe("Context inspector", () => {
  it("exposes every graph node as a named keyboard control", async () => {
    const user = userEvent.setup();
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
    const node = await screen.findByRole("button", { name: "a.md" });
    expect(screen.getByRole("button", { name: "b.md" })).toBeInTheDocument();
    act(() => node.focus());
    await user.keyboard("{Enter}");
    expect(await screen.findByText("About 100 tokens")).toBeVisible();
    expect(node).toHaveFocus();
  });

  it("opens the selected file through the supplied preview action without loading its context", async () => {
    const open = vi.fn();
    const user = userEvent.setup();
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} onOpenFile={open} />);
    const node = await screen.findByRole("button", { name: "a.md" });
    await user.hover(node);
    expect(screen.queryByText("About 100 tokens")).not.toBeInTheDocument();
    await user.click(node);
    expect(await screen.findByText("About 100 tokens")).toBeVisible();
    expect(open).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Open file" }));
    expect(open).toHaveBeenCalledWith("/a.md");
    expect(snapshots[1].graph.nodes[1].state).toBe("discovered");
  });
});


it("stops playback at compaction and shows the new baseline", async () => {
  const { rerender } = render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
  fireEvent.click(screen.getByRole("button", { name: "Play context history" }));
  const compacted: ContextSnapshot = { id: "compacted", graph: { nodes: [{ path: "/system.md", name: "system.md", state: "loaded", tokens: 300 }], edges: [] },
    estimatedTokens: 1500, contextWindowTokens: 10000 };
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[compacted]} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "15");
  expect(screen.getByText("≈15%")).toBeVisible();
  await waitFor(() => expect(screen.queryByRole("button", { name: "a.md" })).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "system.md" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Play context history" })).toBeDisabled();
});


it("shows token usage from the displayed snapshot, including estimates without cache data", () => {
  const { rerender } = render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
  const meter = screen.getByRole("progressbar").parentElement!.parentElement!;
  fireEvent.pointerEnter(meter);
  expect(screen.getByText("2k / 10k")).toBeVisible();
  expect(screen.getByText("40%")).toBeVisible();
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[{
    id: "compacted", estimatedTokens: 1500, contextWindowTokens: 10000, graph: { nodes: [], edges: [] },
  }]} />);
  expect(screen.getByText("≈1.5k / 10k")).toBeVisible();
});
