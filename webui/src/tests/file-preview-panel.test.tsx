import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import { setAppLanguage } from "@/i18n";
import { fetchFilePreview } from "@/lib/api";

vi.mock("@/components/CodeBlock", () => ({
  CodeBlock: ({
    code,
    language,
    highlight,
  }: {
    code: string;
    language?: string;
    highlight?: boolean;
  }) => (
    <pre
      data-testid="mock-code-block"
      data-language={language}
      data-highlight={String(highlight)}
    >
      {code}
    </pre>
  ),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFilePreview: vi.fn(),
  };
});

describe("FilePreviewPanel", () => {
  beforeEach(async () => {
    await setAppLanguage("en");
    vi.mocked(fetchFilePreview).mockReset();
  });

  it("renders a raster instead of source and reports failed image decoding", async () => {
    const dataUrl = "data:image/png;base64,example";
    vi.mocked(fetchFilePreview).mockResolvedValue({
      kind: "image", path: "/workspace/chart.png", display_path: "chart.png",
      project_path: "/workspace", size: 42, mime_type: "image/png", data_url: dataUrl,
    });
    render(<FilePreviewPanel sessionKey="websocket:a" path="chart.png" token="test" />);
    const img = await screen.findByRole("img", { name: "chart.png" });
    expect(img).toHaveAttribute("src", dataUrl);
    expect(screen.queryByTestId("mock-code-block")).not.toBeInTheDocument();
    fireEvent.error(img);
    expect(await screen.findByText("Could not preview this file.")).toBeInTheDocument();
  });

  it("ignores a late response after changing session", async () => {
    let resolveFirst!: (payload: import("@/lib/types").FilePreviewPayload) => void;
    vi.mocked(fetchFilePreview).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const payload = {
      path: "/workspace/b.txt", display_path: "b.txt", project_path: "/workspace",
      language: "text", content: "session B", truncated: false, size: 9,
    };
    vi.mocked(fetchFilePreview).mockResolvedValueOnce(payload);
    const view = (key: string) => <FilePreviewPanel key={key} sessionKey={key} path="notes.txt" token="test" />;
    const { rerender } = render(view("a"));
    rerender(view("b"));
    await screen.findByText("session B");
    await act(async () => resolveFirst({ ...payload, content: "session A" }));
    expect(screen.queryByText("session A")).not.toBeInTheDocument();
  });

  it("opens the sidebar image in the shared zoomable viewer and returns to the preview", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      kind: "image", path: "/workspace/chart.png", display_path: "chart.png",
      size: 42, mime_type: "image/png", data_url: "data:image/png;base64,example",
    });
    render(<FilePreviewPanel sessionKey="websocket:a" path="chart.png" token="test" />);
    const trigger = await screen.findByRole("button", { name: "View image: chart.png" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("img", { name: "chart.png" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    expect(within(dialog).getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.getByTestId("file-preview-panel")).toBeInTheDocument();
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });

  it("renders file content without a second filename or breadcrumb below the tabs", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/Users/hr/workspace/quicksort.py",
      display_path: "quicksort.py",
      language: "python",
      content: "print('ok')",
      truncated: false,
    });

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="quicksort.py"
        token="tok"
      />,
    );

    const codeBlock = await screen.findByTestId("mock-code-block");
    expect(codeBlock).toHaveTextContent("print('ok')");
    expect(codeBlock).toHaveAttribute("data-language", "python");
    expect(codeBlock).toHaveAttribute("data-highlight", "true");
    expect(screen.queryByTestId("file-preview-breadcrumb")).not.toBeInTheDocument();
    expect(screen.queryByText("quicksort.py")).not.toBeInTheDocument();

  });

  it("paints cached content immediately, revalidates it, and does not restart when the cache ages", async () => {
    const cached = { path: "notes.txt", display_path: "notes.txt", language: "text", content: "Cached", truncated: false };
    let resolve!: (payload: typeof cached) => void;
    const loadPreview = vi.fn(() => new Promise<typeof cached>(r => { resolve = r; }));
    const view = (initialPreview?: typeof cached) => <FilePreviewPanel sessionKey="a" path="notes.txt"
      token="test" loadPreview={loadPreview} initialPreview={initialPreview} />;
    const { rerender } = render(view(cached));
    expect(screen.getByTestId("mock-code-block")).toHaveTextContent("Cached");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await act(async () => resolve({ ...cached, content: "Updated" }));
    expect(screen.getByTestId("mock-code-block")).toHaveTextContent("Updated");
    rerender(view());
    expect(screen.getByTestId("mock-code-block")).toHaveTextContent("Updated");
    expect(loadPreview).toHaveBeenCalledTimes(1);
  });

  it("reports a failed revalidation rather than leaving stale cached content looking current", async () => {
    const cached = { path: "notes.txt", display_path: "notes.txt", language: "text", content: "Cached", truncated: false };
    render(<FilePreviewPanel sessionKey="a" path="notes.txt" token="test" initialPreview={cached}
      loadPreview={vi.fn().mockRejectedValue(new Error("Forbidden"))} />);
    await screen.findByText("Could not preview this file.");
    expect(screen.queryByText("Cached")).not.toBeInTheDocument();
  });

  it("updates translated chrome without refetching the open file", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      language: "markdown",
      content: "# Notes",
      truncated: false,
    });

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
      />,
    );

    await screen.findByTestId("mock-code-block");
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);

    await act(async () => {
      await setAppLanguage("zh-CN");
    });

    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });
});
