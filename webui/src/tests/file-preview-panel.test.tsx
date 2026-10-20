import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import { CodeBlock } from "@/components/CodeBlock";
import { PreviewPane } from "@/components/PreviewPane";
import { FilePreviewStore, useFilePreviewState } from "@/hooks/useFilePreviewState";
import { setAppLanguage } from "@/i18n";
import { fetchFilePreview } from "@/lib/api";
import { createFilePreviewResource } from "@/lib/file-preview-resource";

vi.mock("@/components/CodeBlock", () => ({
  CodeBlock: vi.fn(({
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
  )),
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
    vi.mocked(CodeBlock).mockClear();
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
    const resolvePath = vi.fn();
    let resolveFirst!: (payload: import("@/lib/types").FilePreviewPayload) => void;
    vi.mocked(fetchFilePreview).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const payload = {
      path: "/workspace/b.txt", display_path: "b.txt", project_path: "/workspace",
      language: "text", content: "session B", truncated: false, size: 9,
    };
    vi.mocked(fetchFilePreview).mockResolvedValueOnce(payload);
    const view = (key: string) => <FilePreviewPanel key={key} sessionKey={key} path="notes.txt" token="test" onResolvePath={resolvePath} />;
    const { rerender } = render(view("a"));
    rerender(view("b"));
    await screen.findByText("session B");
    await act(async () => resolveFirst({ ...payload, content: "session A" }));
    expect(screen.queryByText("session A")).not.toBeInTheDocument();
    expect(resolvePath).toHaveBeenCalledOnce();
    expect(resolvePath).toHaveBeenCalledWith("notes.txt", "/workspace/b.txt");
  });

  it("opens, follows a relative link and returns to one report tab with working source controls", async () => {
    const report = "# Report\n\n[Details](./details.md)\n";
    vi.mocked(fetchFilePreview).mockImplementation(async (_token, _session, path) => {
      const details = path.endsWith("details.md");
      const name = details ? "details.md" : "REPORT.md";
      const content = details ? "# Details\n\n[Return](./REPORT.md)\n" : report;
      return { path: `/workspace/reports/${name}`, display_path: `reports/${name}`,
        project_path: "/workspace", size: new TextEncoder().encode(content).byteLength,
        language: "markdown", content, truncated: false };
    });
    const store = new FilePreviewStore();
    const resource = createFilePreviewResource(path => fetchFilePreview("test", "a", path));
    store.open("a", "file", "reports/REPORT.md");
    function View() {
      const { state, openFile, resolveFile, selectTab, closeTab, close } = useFilePreviewState("a", store);
      const active = state.tabs.find(tab => tab.id === state.activeId)!;
      return <PreviewPane tabs={state.tabs} activeId={active.id} width={544} isClosing={false}
        onSelect={selectTab} onCloseTab={closeTab} onClose={close} onResizeStart={() => {}}>
        <FilePreviewPanel key={active.id} sessionKey="a" path={active.value} token="test"
          loadPreview={resource.load} initialPreview={resource.peek(active.value)}
          onOpenFilePreview={openFile} onResolvePath={resolveFile} />
      </PreviewPane>;
    }
    render(<View />);
    await screen.findByRole("heading", { name: "Report" });
    fireEvent.click(screen.getByRole("button", { name: "/workspace/reports/./details.md" }));
    await screen.findByRole("heading", { name: "Details" });
    fireEvent.click(screen.getByRole("button", { name: "/workspace/reports/./REPORT.md" }));
    await screen.findByRole("heading", { name: "Report" });
    expect(screen.getAllByRole("tab", { name: "REPORT.md" })).toHaveLength(1);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "REPORT.md" })).toHaveAttribute("aria-selected", "true");
    expect(fetchFilePreview).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.getByTestId("mock-code-block").textContent).toBe(report);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("heading", { name: "Report" });
    expect(fetchFilePreview).toHaveBeenCalledTimes(3);
  });

  it("opens the sidebar image in the shared zoomable viewer and returns to the preview", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      kind: "image", path: "/workspace/chart.png", display_path: "chart.png",
      project_path: "/workspace", size: 42, mime_type: "image/png", data_url: "data:image/png;base64,example",
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
      project_path: "/Users/hr/workspace",
      size: 11,
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
    const cached = { path: "notes.txt", display_path: "notes.txt", project_path: "/workspace", size: 6, language: "text", content: "Cached", truncated: false };
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
    const cached = { path: "notes.txt", display_path: "notes.txt", project_path: "/workspace", size: 6, language: "text", content: "Cached", truncated: false };
    render(<FilePreviewPanel sessionKey="a" path="notes.txt" token="test" initialPreview={cached}
      loadPreview={vi.fn().mockRejectedValue(new Error("Forbidden"))} />);
    await screen.findByText("Could not preview this file.");
    expect(screen.queryByText("Cached")).not.toBeInTheDocument();
  });

  it("does not repaint a cache hit twice after its initial synchronous paint", async () => {
    const cached = { path: "notes.txt", display_path: "notes.txt", project_path: "/workspace", size: 6, language: "text", content: "Cached", truncated: false };
    const loadPreview = vi.fn().mockResolvedValue(cached);
    render(<FilePreviewPanel sessionKey="a" path="notes.txt" token="test"
      initialPreview={cached} loadPreview={loadPreview} />);
    await act(async () => { await Promise.resolve(); });
    expect(loadPreview).toHaveBeenCalledOnce();
    expect(CodeBlock).toHaveBeenCalledOnce();
  });

  it("updates translated chrome without refetching the open file", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      project_path: "/workspace",
      size: 7,
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

    await screen.findByRole("heading", { name: "Notes" });
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);

    await act(async () => {
      await setAppLanguage("zh-CN");
    });

    expect(screen.getByRole("button", { name: "预览" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "原文" })).toBeInTheDocument();
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });

  it("defaults old Markdown payloads to preview and switches to exact source without another read", async () => {
    const content = "# Report\n\n**Done**\n\n| Item | Status |\n| --- | --- |\n| Copy | OK |\n";
    vi.mocked(fetchFilePreview).mockResolvedValue({ path: "/workspace/REPORT.md", display_path: "REPORT.md",
      project_path: "/workspace", size: new TextEncoder().encode(content).byteLength,
      language: "markdown", content, truncated: true });
    render(<FilePreviewPanel sessionKey="a" path="REPORT.md" token="test" />);
    await screen.findByRole("heading", { name: "Report" });
    expect(screen.getByRole("table")).toHaveTextContent("CopyOK");
    const notice = "Preview is truncated because this file is large.";
    expect(screen.getByText(notice)).toBeInTheDocument();
    const source = screen.getByRole("button", { name: "Source" });
    source.focus();
    fireEvent.click(source);
    expect(source).toHaveFocus();
    expect(source).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("mock-code-block").textContent).toBe(content);
    expect(CodeBlock).toHaveBeenLastCalledWith(expect.objectContaining({
      code: content, chrome: "none", showLineNumbers: true, wrapLongLines: false, viewportHighlight: true,
    }), expect.anything());
    expect(screen.getByText(notice)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("heading", { name: "Report" });
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });

  it("resets the display for another file or session but keeps source on credential renewal", async () => {
    const payload = { path: "/workspace/notes.md", display_path: "notes.md", language: "markdown",
      project_path: "/workspace", size: 7, content: "# Notes", truncated: false };
    vi.mocked(fetchFilePreview).mockResolvedValue(payload);
    const view = (path: string, sessionKey = "a", token = "old") =>
      <FilePreviewPanel sessionKey={sessionKey} path={path} token={token} />;
    const { rerender } = render(view("notes.md"));
    await screen.findByRole("heading", { name: "Notes" });
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    rerender(view("notes.md", "a", "new"));
    expect(screen.getByRole("button", { name: "Source" })).toHaveAttribute("aria-pressed", "true");
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
    rerender(view("other.md"));
    await screen.findByRole("heading", { name: "Notes" });
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    rerender(view("other.md", "b"));
    await screen.findByRole("heading", { name: "Notes" });
    expect(fetchFilePreview).toHaveBeenCalledTimes(3);
  });

  it("keeps document resources inert and opens relative links through the session preview callback", async () => {
    const open = vi.fn();
    const content = [
        "# Report", "[Local](../notes%20one.md)", "![Chart](https://example.com/chart.png)",
        "- Reference — [Website](https://example.com)", "[Section](#details)", "[Chat](#/chat/websocket:other)",
        "[Unsafe](javascript:alert(1))", '<img src="https://example.com/raw.png" onerror="alert(1)">',
        '<iframe src="https://example.com/frame"></iframe>', '<script>alert(1)</script>',
        "`skills/cron/SKILL.md`", "<CustomComponent />",
    ].join("\n\n");
    vi.mocked(fetchFilePreview).mockResolvedValue({ path: "/workspace/reports/REPORT.mdx", display_path: "reports/REPORT.mdx",
      project_path: "/workspace", size: new TextEncoder().encode(content).byteLength,
      language: "markdown", truncated: false, content });
    const { container } = render(<FilePreviewPanel sessionKey="a" path="reports/REPORT.mdx" token="test" onOpenFilePreview={open} />);
    await screen.findByRole("heading", { name: "Report" });
    expect(container.querySelector("img, iframe, script, video, audio")).toBeNull();
    expect(screen.getByRole("link", { name: "Chart" })).toHaveAttribute("href", "https://example.com/chart.png");
    expect(screen.getByRole("link", { name: "Website" })).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.queryByRole("link", { name: /Section|Chat|Unsafe/ })).not.toBeInTheDocument();
    expect(container.querySelector("code")?.textContent).toBe("skills/cron/SKILL.md");
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "/workspace/reports/../notes one.md" }));
    expect(open).toHaveBeenCalledWith("/workspace/reports/../notes one.md");
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });

  it("preserves the open image and zoom on token renewal, using the current token for the next file", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      kind: "image", path: "/workspace/chart.png", display_path: "chart.png",
      project_path: "/workspace", size: 42, mime_type: "image/png", data_url: "data:image/png;base64,example",
    });
    const view = (token: string, path = "chart.png") =>
      <FilePreviewPanel sessionKey="websocket:a" path={path} token={token} />;
    const { rerender } = render(view("old"));
    fireEvent.click(await screen.findByRole("button", { name: "View image: chart.png" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    rerender(view("renewed"));
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(within(dialog).getByRole("button", { name: "Fit image" })).toHaveTextContent("150%");
    rerender(view("renewed", "second.png"));
    await waitFor(() => expect(fetchFilePreview).toHaveBeenLastCalledWith("renewed", "websocket:a", "second.png"));
  });
});
