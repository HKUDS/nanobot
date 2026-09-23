import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";
import { MessageBubble } from "@/components/MessageBubble";
import { MermaidBlock } from "@/components/MermaidBlock";
import { ThemeProvider } from "@/hooks/useTheme";
import { renderMermaid } from "@/lib/mermaid-renderer";

vi.mock("@/lib/mermaid-renderer", () => ({ renderMermaid: vi.fn() }));

describe("Mermaid blocks", () => {
  beforeEach(() => {
    vi.mocked(renderMermaid).mockReset().mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"><text>Example</text></svg>');
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:diagram");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("renders a completed assistant diagram while preserving the chat's streaming layout", async () => {
    const message = { id: "diagram-reply", role: "assistant" as const, createdAt: 1,
      content: "Before\n\n```mermaid\nflowchart LR\n A-->B\n```" };
    const view = render(<MessageBubble message={{ ...message, isStreaming: true }} />);
    await screen.findByTestId("plain-code-fallback");
    expect(renderMermaid).not.toHaveBeenCalled();
    view.rerender(<MessageBubble message={{ ...message, isStreaming: false }} />);
    expect(await screen.findByRole("img", { name: "Mermaid diagram" })).toBeInTheDocument();
  });
  it("renders through the actual Markdown fence route, with source and expand controls", async () => {
    render(<MarkdownTextRenderer>{"```mermaid\nflowchart LR\n A-->B\n```"}</MarkdownTextRenderer>);
    expect(await screen.findByRole("img", { name: "Mermaid diagram" })).toHaveAttribute("src", "blob:diagram");
    fireEvent.click(screen.getByRole("button", { name: "Source", exact: true }));
    expect(screen.getByTestId("plain-code-fallback")).toHaveTextContent("A-->B");
    fireEvent.click(screen.getByRole("button", { name: "Diagram", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Expand diagram" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("125%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
  it("does not layout a partial stream and renders when streaming finishes", async () => {
    const code = "```mermaid\nflowchart LR\n A-->B\n```";
    const view = render(<MarkdownTextRenderer streaming>{code}</MarkdownTextRenderer>);
    expect(screen.getByTestId("plain-code-fallback")).toHaveTextContent("A-->B");
    expect(renderMermaid).not.toHaveBeenCalled();
    view.rerender(<MarkdownTextRenderer streaming={false}>{code}</MarkdownTextRenderer>);
    expect(await screen.findByRole("img", { name: "Mermaid diagram" })).toBeInTheDocument();
  });
  it("preserves source on errors", async () => {
    vi.mocked(renderMermaid).mockRejectedValue(new Error("syntax"));
    render(<MermaidBlock code="invalid diagram" />);
    expect(await screen.findByRole("status")).toHaveTextContent("cannot be rendered safely");
    expect(screen.getByTestId("plain-code-fallback")).toHaveTextContent("invalid diagram");
  });
  it("releases image URLs on theme change and unmount", async () => {
    const view = render(<ThemeProvider theme="light"><MermaidBlock code="flowchart LR\n A-->B" /></ThemeProvider>);
    await screen.findByRole("img");
    view.rerender(<ThemeProvider theme="dark"><MermaidBlock code="flowchart LR\n A-->B" /></ThemeProvider>);
    await waitFor(() => expect(renderMermaid).toHaveBeenLastCalledWith(expect.any(String), true, expect.any(AbortSignal)));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:diagram");
    view.unmount();
  });
  it("ignores a render that resolves after unmount", async () => {
    let complete!: (value: string) => void;
    vi.mocked(renderMermaid).mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    const view = render(<MermaidBlock code="flowchart LR\n A-->B" />);
    await waitFor(() => expect(renderMermaid).toHaveBeenCalled());
    view.unmount();
    await act(async () => complete("<svg/>"));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
