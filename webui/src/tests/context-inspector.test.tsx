import { act, createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("plays from the first snapshot to the current graph without pausing", () => {
    vi.useFakeTimers();
    try {
      render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
      const play = screen.getByRole("button", { name: "Play context history" });
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
      fireEvent.click(play);
      expect(play).toBeDisabled();
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
      act(() => vi.advanceTimersByTime(750));
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
      act(() => vi.advanceTimersByTime(750));
      expect(play).toBeEnabled();
      fireEvent.click(play);
      expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    } finally { vi.useRealTimers(); }
  });

  it("reveals filenames on hover and fades them in when zooming", async () => {
    const user = userEvent.setup();
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
    const node = await screen.findByRole("button", { name: "a.md" });
    const label = screen.getByText("a.md");
    expect(label).toHaveStyle({ opacity: "0" });
    await user.hover(node.querySelector("span span")!);
    expect(label).toHaveStyle({ opacity: "1" });
    await user.unhover(node.querySelector("span span")!);
    expect(label).toHaveStyle({ opacity: "0" });
    const zoom = (deltaY: number) => {
      const event = createEvent.wheel(node);
      Object.defineProperties(event, { deltaY: { value: deltaY }, clientX: { value: 100 }, clientY: { value: 100 } });
      fireEvent(node, event);
    };
    zoom(-400);
    expect(Number(label.style.opacity)).toBeGreaterThan(0);
    expect(Number(label.style.opacity)).toBeLessThan(1);
    await user.hover(node.querySelector("span span")!);
    expect(label).toHaveStyle({ opacity: "1" });
    await user.unhover(node.querySelector("span span")!);
    expect(Number(label.style.opacity)).toBeGreaterThan(0);
    expect(Number(label.style.opacity)).toBeLessThan(1);
    zoom(1000);
    expect(label).toHaveStyle({ opacity: "0" });
  });

  it("opens the selected file through the supplied preview action without loading its context", async () => {
    const open = vi.fn();
    const user = userEvent.setup();
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} onOpenFile={open} />);
    const node = await screen.findByRole("button", { name: "a.md" });
    await user.hover(node.querySelector("span span")!);
    expect(screen.queryByText("About 100 tokens")).not.toBeInTheDocument();
    await user.click(node.querySelector("span span")!);
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
