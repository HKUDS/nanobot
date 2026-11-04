import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("reviews matching graph and usage snapshots and returns to latest on release", async () => {
    render(<ContextInspector context={null} rounds={[]} snapshots={snapshots} />);
    const slider = screen.getByRole("slider");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    fireEvent.pointerDown(slider, { button: 0, pointerId: 1, clientX: 120 });
    expect(screen.getByText("2/2")).toBeVisible();
    fireEvent.pointerMove(slider, { pointerId: 1, clientX: 96 });
    expect(screen.getByText("1/2")).toBeVisible();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "10");
    expect(screen.queryByRole("button", { name: "b.md" })).not.toBeInTheDocument();
    fireEvent.pointerUp(slider, { pointerId: 1 });
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
    await waitFor(() => expect(screen.getByRole("button", { name: "b.md" })).toBeInTheDocument());
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
