import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    render(<FilePreviewPanel sessionKey="websocket:a" path="chart.png" token="test" onClose={() => {}} />);
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
    const view = (key: string) => <FilePreviewPanel key={key} sessionKey={key} path="notes.txt" token="test" onClose={() => {}} />;
    const { rerender } = render(view("a"));
    rerender(view("b"));
    await screen.findByText("session B");
    await act(async () => resolveFirst({ ...payload, content: "session A" }));
    expect(screen.queryByText("session A")).not.toBeInTheDocument();
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

    await screen.findByTestId("mock-code-block");
    expect(fetchFilePreview).toHaveBeenCalledTimes(1);

    await act(async () => {
      await setAppLanguage("zh-CN");
    });

    expect(fetchFilePreview).toHaveBeenCalledTimes(1);
  });
});
