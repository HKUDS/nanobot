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
  const pending: ContextSnapshot = { id: "after-compaction", graph: compacted.graph, contextWindowTokens: 10000 };
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[compacted, pending]} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "15");
  expect(screen.getByText("≈15%")).toBeVisible();
});


it("keeps the latest measured usage while the live graph advances and updates on completion", async () => {
  const measured = { ...snapshots[1], usage: { ...snapshots[1].usage, generation_ms: 2000 } };
  const history = [snapshots[0], measured];
  const { rerender } = render(<ContextInspector context={null} rounds={[]} snapshots={history} />);
  const meter = screen.getByRole("progressbar").parentElement!.parentElement!;
  fireEvent.pointerEnter(meter);
  expect(screen.getByText("2k / 10k")).toBeVisible();
  expect(screen.getByText("40%")).toBeVisible();
  const pending: ContextSnapshot = { id: "third", contextWindowTokens: 20000, graph: {
    nodes: [{ path: "/c.md", name: "c.md", state: "loaded", tokens: 100 }], edges: [],
  } };
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[...history, pending]} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
  expect(screen.getByText("2k / 10k")).toBeVisible();
  expect(screen.getByText("40%")).toBeVisible();
  expect(screen.getByText("2s")).toBeVisible();
  expect(await screen.findByRole("button", { name: "c.md" })).toBeInTheDocument();
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[...history, {
    ...pending, usage: { context_tokens: 3000, prompt_tokens: 3000, cached_tokens: 1500, generation_ms: 4000 },
  }]} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "15");
  expect(screen.getByText("3k / 20k")).toBeVisible();
  expect(screen.getByText("50%")).toBeVisible();
  expect(screen.getByText("4s")).toBeVisible();
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[{
    id: "compacted", estimatedTokens: 1500, contextWindowTokens: 10000, graph: { nodes: [], edges: [] },
  }]} />);
  expect(screen.getByText("≈1.5k / 10k")).toBeVisible();
  expect(screen.queryByText("50%")).not.toBeInTheDocument();
  expect(screen.queryByText("4s")).not.toBeInTheDocument();
  rerender(<ContextInspector context={null} rounds={[]} snapshots={[pending]} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.getByText("— / 20k")).toBeVisible();
});
