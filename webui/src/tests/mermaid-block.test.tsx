import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MessageBubble } from "@/components/MessageBubble";
import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";
import { DiagramScope } from "@/components/markdown-diagrams/context";
import type { DiagramInput } from "@/components/markdown-diagrams/types";
import type { DiagramState } from "@/components/markdown-diagrams/runtime";

const runtime = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/components/markdown-diagrams/runtime", () => ({ requestDiagram: runtime.request }));
const code = "flowchart LR\n开始 --> 完成";
const markdown = `Before the graph.\n\n\`\`\`mermaid\n${code}\n\`\`\`\n\nAfter the graph.`;
const jobs: { input: DiagramInput; signal: AbortSignal; publish: (state: DiagramState) => void; demand: ReturnType<typeof vi.fn> }[] = [];
class VisibleObserver {
  constructor(private callback: (entries: { isIntersecting: boolean }[]) => void) {}
  observe() { this.callback([{ isIntersecting: true }]); }
  disconnect() {}
}
class SizeObserver {
  constructor(private callback: () => void) {}
  observe() { this.callback(); }
  disconnect() {}
}
beforeEach(() => {
  jobs.length = 0;
  runtime.request.mockImplementation((input: DiagramInput, signal: AbortSignal, publish: (state: DiagramState) => void) => {
    const demand = vi.fn();
    jobs.push({ input, signal, publish, demand });
    return { setDemand: demand, setPalette: vi.fn(), retry: vi.fn(), dispose: vi.fn() };
  });
  vi.stubGlobal("IntersectionObserver", VisibleObserver);
  vi.stubGlobal("ResizeObserver", SizeObserver);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(640);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Mermaid message fences", () => {
  it("renders identical source at actual completion through preserved Streamdown layout", async () => {
    const message = { id: "diagram", role: "assistant" as const, content: markdown, createdAt: 1, isStreaming: true };
    const view = render(<MessageBubble message={message} />);
    await waitFor(() => expect(view.container.querySelector(".markdown-content")).toBeInTheDocument());
    const tree = view.container.querySelector(".markdown-content");
    expect(runtime.request).not.toHaveBeenCalled();
    expect(view.container).toHaveTextContent("开始 --> 完成");
    view.rerender(<MessageBubble message={{ ...message, isStreaming: false }} />);
    await waitFor(() => expect(jobs).toHaveLength(1));
    expect(jobs[0].input.source).toBe(code);
    expect(view.container.querySelector(".markdown-content")).toBe(tree);
    act(() => jobs[0].publish({ kind: "ready", image: { url: "blob:completed-diagram", width: 200, height: 100, label: "A real diagram result" } }));
    expect(screen.getByRole("img", { name: "A real diagram result" })).toHaveAttribute("src", "blob:completed-diagram");
    expect(screen.getByRole("button", { name: "Enlarge diagram" })).not.toBeDisabled();
    expect(view.container).toHaveTextContent("Before the graph.");
    expect(view.container).toHaveTextContent("After the graph.");
  });

  it("keeps errors local and makes failed source available", async () => {
    render(<MarkdownTextRenderer>{markdown}</MarkdownTextRenderer>);
    await waitFor(() => expect(jobs).toHaveLength(1));
    act(() => jobs[0].publish({ kind: "failed", reason: "syntax" }));
    expect(screen.getByRole("status")).toHaveTextContent("Check the diagram syntax");
    expect(screen.getByTestId("plain-code-fallback")).toHaveTextContent("开始 --> 完成");
    expect(screen.getByText("After the graph.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy source" })).toBeInTheDocument();
  });

  it("keeps a chosen source view and cancels resources when the conversation identity changes", async () => {
    const view = render(<DiagramScope identity="first"><MarkdownTextRenderer>{markdown}</MarkdownTextRenderer></DiagramScope>);
    await waitFor(() => expect(jobs).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(jobs[0].demand).toHaveBeenLastCalledWith("none");
    view.rerender(<DiagramScope identity="second"><MarkdownTextRenderer>{markdown}</MarkdownTextRenderer></DiagramScope>);
    await waitFor(() => expect(jobs).toHaveLength(2));
    expect(jobs[0].signal.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Source" })).toHaveAttribute("aria-pressed", "true");
    expect(jobs[1].demand).toHaveBeenLastCalledWith("none");
  });
});
