import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import { setAppLanguage } from "@/i18n";
import { fetchFilePreview } from "@/lib/api";

const openFileMock = vi.fn(async (_path: string) => ({ ok: true }));

vi.mock("@/lib/runtime", () => ({
  getRuntimeHost: () => ({
    openFile: openFileMock,
  }),
}));

vi.mock("@/components/MarkdownText", () => ({
  MarkdownText: ({ children }: { children: string }) => (
    <div data-testid="mock-markdown-text">{children}</div>
  ),
}));

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

  it("shows a compact breadcrumb with one file name and a visible close action", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
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
        onClose={onClose}
      />,
    );

    const codeBlock = await screen.findByTestId("mock-code-block");
    expect(codeBlock).toHaveTextContent("print('ok')");
    expect(codeBlock).toHaveAttribute("data-language", "python");
    expect(codeBlock).toHaveAttribute("data-highlight", "true");
    expect(screen.getByTestId("file-preview-breadcrumb")).toHaveTextContent("...");
    expect(screen.getByTestId("file-preview-breadcrumb")).toHaveTextContent("workspace");
    expect(screen.getByTestId("file-preview-title")).toHaveTextContent("quicksort.py");
    expect(screen.getAllByText("quicksort.py")).toHaveLength(1);

    const closeButton = screen.getByRole("button", { name: "Close file preview" });
    expect(closeButton).toBeVisible();

    await user.click(closeButton);
    expect(onClose).toHaveBeenCalledTimes(1);
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
        onClose={() => {}}
      />,
    );

    await screen.findByTestId("mock-markdown-text");
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);

    await act(async () => {
      await setAppLanguage("zh-CN");
    });

    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });

  it("renders the open-in-system button only when allowed", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      project_path: "",
      language: "markdown",
      content: "# Notes",
      size: 0,
      truncated: false,
    });

    const { unmount } = render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
        canOpenSystem
        onClose={() => {}}
      />,
    );
    await screen.findByTestId("mock-markdown-text");
    expect(screen.getByTestId("file-preview-open-system")).toBeInTheDocument();
    unmount();

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
        onClose={() => {}}
      />,
    );
    await screen.findByTestId("mock-markdown-text");
    expect(screen.queryByTestId("file-preview-open-system")).not.toBeInTheDocument();
  });

  it("calls the host openFile with the resolved path", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      project_path: "",
      language: "markdown",
      content: "# Notes",
      size: 0,
      truncated: false,
    });

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
        canOpenSystem
        onClose={() => {}}
      />,
    );
    await screen.findByTestId("mock-markdown-text");
    await userEvent.click(screen.getByTestId("file-preview-open-system"));

    await waitFor(() => expect(openFileMock).toHaveBeenCalledWith("/workspace/notes.md"));
  });

  it("shows an error banner when the host cannot open the file", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      project_path: "",
      language: "markdown",
      content: "# Notes",
      size: 0,
      truncated: false,
    });
    openFileMock.mockResolvedValueOnce({ ok: false, error: "no handler" });

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
        canOpenSystem
        onClose={() => {}}
      />,
    );
    await screen.findByTestId("mock-markdown-text");
    await userEvent.click(screen.getByTestId("file-preview-open-system"));

    expect(await screen.findByTestId("file-preview-open-error")).toHaveTextContent("no handler");
  });

  it("shows a fallback error banner when openFile throws", async () => {
    vi.mocked(fetchFilePreview).mockResolvedValue({
      path: "/workspace/notes.md",
      display_path: "notes.md",
      project_path: "",
      language: "markdown",
      content: "# Notes",
      size: 0,
      truncated: false,
    });
    openFileMock.mockRejectedValueOnce(new Error("boom"));

    render(
      <FilePreviewPanel
        sessionKey="websocket:chat-1"
        path="notes.md"
        token="tok"
        canOpenSystem
        onClose={() => {}}
      />,
    );
    await screen.findByTestId("mock-markdown-text");
    await userEvent.click(screen.getByTestId("file-preview-open-system"));

    expect(await screen.findByTestId("file-preview-open-error")).toHaveTextContent("boom");
  });
});
