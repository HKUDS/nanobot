import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ImageGallery } from "@/components/ImageGallery";
import { MessageBubble } from "@/components/MessageBubble";
import { FileActionsProvider } from "@/components/FileActions";
import { FileReferenceChip } from "@/components/FileReferenceChip";
import type { FilePreviewPayload, UIMessage } from "@/lib/types";

const images = Array.from({ length: 8 }, (_, index) => ({ url: `/api/media/sign/image-${index}`, name: `${index}.png` }));
const message: UIMessage = { id: "images", role: "assistant", content: "", createdAt: 1,
  media: [{ kind: "image", url: "/api/media/sign/chart", name: "chart.png" }] };

describe("image presentation", () => {
  it("bounds a large collection to four thumbnails and keeps every image in the viewer", async () => {
    const user = userEvent.setup();
    const { container } = render(<ImageGallery images={images} />);
    expect(container.querySelectorAll("img")).toHaveLength(4);
    expect(screen.getByText("+4")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "View all 8 images" }));
    expect(screen.getByText("4 / 8")).toBeVisible();
    await user.keyboard("{End}");
    expect(screen.getByText("8 / 8")).toBeVisible();
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: "7.png" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View all 8 images" })).toHaveFocus();
  });

  it("preserves an inline image's position, deduplicates its attachment, and opens the shared viewer", async () => {
    const user = userEvent.setup();
    const { container, rerender } = render(<MessageBubble message={{ ...message,
      content: "Before\n\n![Trend](/api/media/sign/chart)\n\nAfter", media: [...message.media!, ...message.media!] }} />);
    await screen.findByRole("img", { name: "Trend" });
    await waitFor(() => expect(container.querySelectorAll("img")).toHaveLength(1));
    expect(container.textContent).toMatch(/Before.*After/s);
    await user.click(screen.getByRole("button", { name: "View image: Trend" }));
    expect(await screen.findByRole("button", { name: "Zoom in" })).toBeVisible();
    await user.keyboard("{Escape}");
    // Removing inline content must restore the attachment; no global remembered suppression.
    rerender(<MessageBubble message={{ ...message, content: "File ready" }} />);
    expect(await screen.findByRole("button", { name: "View image: chart.png" })).toBeVisible();
  });

  it("does not suppress files referenced in code or links, or different images sharing a name", async () => {
    const { container } = render(<MessageBubble message={{ ...message,
      content: "```md\n![example](/api/media/sign/chart)\n```\n\n[chart.png](/api/media/sign/chart)",
      media: [...message.media!, { kind: "image", url: "/api/media/other/chart", name: "chart.png" }] }} />);
    await waitFor(() => expect(container.querySelector("pre")).toBeInTheDocument());
    expect(container.querySelectorAll("img")).toHaveLength(2);
  });

  it("keeps the attachment if an image reference is not actually rendered by the streaming renderer", async () => {
    const { container } = render(<MessageBubble message={{ ...message,
      content: "![Trend][chart]\n\n[chart]: /api/media/sign/chart" }} />);
    await screen.findByText("![Trend][chart]");
    expect(screen.getByRole("button", { name: "View image: chart.png" })).toBeVisible();
    await waitFor(() => expect(container.querySelectorAll("img")).toHaveLength(1));
  });

  it("keeps unavailable images readable, and never hides a valid image behind missing placeholders", async () => {
    const user = userEvent.setup();
    render(<ImageGallery images={[...Array.from({ length: 4 }, () => ({ name: "old.png" })), images[0]]} />);
    await user.click(screen.getByRole("button", { name: "View all 5 images" }));
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: "0.png" })).toBeVisible();
  });

  it("replaces a broken thumbnail with a quiet named placeholder", () => {
    render(<ImageGallery images={[images[0]]} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("0.png")).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("file quick look", () => {
  const preview: FilePreviewPayload = { kind: "image", path: "chart.png", display_path: "chart.png",
    project_path: "/workspace", size: 100, mime_type: "image/png", data_url: "data:image/png;base64,dGVzdA==" };
  it("loads only on deliberate hover/focus, keeps click as preview, and releases content on dismissal", async () => {
    const user = userEvent.setup();
    const loadPreview = vi.fn().mockResolvedValue(preview);
    const onOpen = vi.fn();
    const { container } = render(<FileActionsProvider value={{ resolveMetadata: vi.fn(), loadPreview }}>
      <FileReferenceChip path="chart.png" onOpen={onOpen} />
    </FileActionsProvider>);
    expect(loadPreview).not.toHaveBeenCalled();
    await user.hover(screen.getByRole("button", { name: "chart.png" }));
    expect(loadPreview).not.toHaveBeenCalled();
    await screen.findByRole("tooltip");
    await waitFor(() => expect(loadPreview).toHaveBeenCalledWith("chart.png"));
    const quickLook = screen.getByTestId("file-image-quick-look");
    expect(quickLook.textContent).toBe("");
    expect(quickLook).toHaveClass("w-max");
    expect(quickLook).not.toHaveClass("h-36", "w-full");
    expect(quickLook.querySelector("img")).toHaveClass("rounded-mark", "object-contain");
    expect(quickLook.querySelector("img")).toHaveClass("h-auto", "w-auto", "max-h-36");
    expect(screen.getByRole("tooltip")).toHaveTextContent("File preview");
    await user.click(screen.getByRole("button", { name: "chart.png" }));
    expect(onOpen).toHaveBeenCalledWith("chart.png");
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
    expect(container.querySelector("img")).not.toBeInTheDocument();
  });

  it("does not show a late image from a previous session, and shows a quiet failure instead of an empty popup", async () => {
    let resolveOld!: (payload: FilePreviewPayload) => void;
    const oldLoader = vi.fn(() => new Promise<FilePreviewPayload>((resolve) => { resolveOld = resolve; }));
    const newLoader = vi.fn().mockRejectedValue(new Error("404"));
    const view = (loadPreview: typeof oldLoader) => <FileActionsProvider value={{ resolveMetadata: vi.fn(), loadPreview }}>
      <FileReferenceChip path="chart.png" onOpen={vi.fn()} />
    </FileActionsProvider>;
    const { rerender } = render(view(oldLoader));
    fireEvent.focus(screen.getByRole("button", { name: "chart.png" }));
    await waitFor(() => expect(oldLoader).toHaveBeenCalled());
    rerender(view(newLoader));
    await act(async () => resolveOld(preview));
    expect(document.querySelector('img[src^="data:image"]')).not.toBeInTheDocument();
    expect(screen.getByText("Could not preview this file.")).toBeVisible();
    expect(screen.getByRole("button", { name: "chart.png" })).toBeVisible();
  });

  it("keeps long image paths out of the quick look while preserving the real preview target", async () => {
    const user = userEvent.setup();
    const filename = "a-long-descriptive-filename-for-a-generated-project-overview.png";
    const path = `/workspace/projects/weekly-reports/exported-charts/${filename}`;
    const loadPreview = vi.fn().mockResolvedValue(preview);
    const onOpen = vi.fn();
    render(<FileActionsProvider value={{ resolveMetadata: vi.fn(), loadPreview }}>
      <FileReferenceChip path="Project overview" tooltipPath={path} previewPath={path} onOpen={onOpen} />
    </FileActionsProvider>);
    fireEvent.focus(screen.getByRole("button", { name: path }));
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).not.toHaveTextContent(filename);
    expect(tooltip).not.toHaveTextContent("/workspace/");
    await waitFor(() => expect(loadPreview).toHaveBeenCalledWith(path));
    expect(screen.getByTestId("file-image-quick-look").textContent).toBe("");
    await user.click(screen.getByRole("button", { name: path }));
    expect(onOpen).toHaveBeenCalledWith(path);
  });

  it("replaces a broken preview image with a readable failure without repeating the filename", async () => {
    const loadPreview = vi.fn().mockResolvedValue(preview);
    render(<FileActionsProvider value={{ resolveMetadata: vi.fn(), loadPreview }}>
      <FileReferenceChip path="chart.png" onOpen={vi.fn()} />
    </FileActionsProvider>);
    fireEvent.focus(screen.getByRole("button", { name: "chart.png" }));
    await waitFor(() => expect(document.querySelector('img[src^="data:image"]')).toBeInTheDocument());
    fireEvent.error(screen.getByTestId("file-image-quick-look").querySelector("img")!);
    expect(screen.queryByTestId("file-image-quick-look")).not.toBeInTheDocument();
    expect(screen.getByText("Could not preview this file.")).toBeVisible();
    expect(screen.getAllByText("chart.png")).toHaveLength(1);
  });

  it("retains the full path tooltip for non-image file references without fetching an image", async () => {
    const path = "/workspace/projects/reports/data.json";
    const loadPreview = vi.fn();
    render(<FileActionsProvider value={{ resolveMetadata: vi.fn(), loadPreview }}>
      <FileReferenceChip path="data.json" tooltipPath={path} onOpen={vi.fn()} />
    </FileActionsProvider>);
    fireEvent.focus(screen.getByRole("button", { name: path }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(path);
    expect(loadPreview).not.toHaveBeenCalled();
  });
});
