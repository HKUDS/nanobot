import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FileActions, FileActionsProvider } from "@/components/FileActions";
import { FileReferenceChip } from "@/components/FileReferenceChip";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { FileReferenceMetadata } from "@/lib/types";

vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn() }));
const details = { path: "/workspace/notes.md", relative_path: "notes.md" };

describe("File actions", () => {
  beforeEach(() => vi.mocked(copyTextToClipboard).mockReset().mockResolvedValue(true));

  it("resolves paths only when opened and uses the same menu for both copies", async () => {
    const user = userEvent.setup();
    const resolveMetadata = vi.fn().mockResolvedValue(details);
    const openPreview = vi.fn();
    render(<FileActionsProvider value={{ resolveMetadata, openPreview }}>
      <FileReferenceChip path="notes.md:12" onOpen={vi.fn()} />
    </FileActionsProvider>);
    expect(resolveMetadata).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "File actions for notes.md:12" }));
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Copy absolute path" })).not.toHaveAttribute("data-disabled"));
    expect(resolveMetadata).toHaveBeenCalledWith("notes.md:12");
    await user.click(screen.getByRole("menuitem", { name: "Copy absolute path" }));
    expect(copyTextToClipboard).toHaveBeenLastCalledWith(details.path);
    expect(await screen.findByText("Copied")).toBeVisible();
    await user.click(screen.getByRole("menuitem", { name: "Copy relative path" }));
    expect(copyTextToClipboard).toHaveBeenLastCalledWith("notes.md");
    await user.click(screen.getByRole("menuitem", { name: "Preview" }));
    expect(openPreview).toHaveBeenCalledWith("notes.md:12");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("keeps primary click working and supports context menu and Shift+F10", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<FileReferenceChip path="src/app.ts" onOpen={onOpen} />);
    const reference = screen.getByRole("button", { name: "src/app.ts" });
    await user.click(reference);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith("src/app.ts");
    fireEvent.contextMenu(reference);
    expect(await screen.findByRole("menuitem", { name: "Preview" })).toBeVisible();
    await user.keyboard("{Escape}");
    fireEvent.keyDown(reference, { key: "F10", shiftKey: true });
    expect(await screen.findByRole("menuitem", { name: "Copy reference" })).toBeVisible();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("does not invent a relative path for files outside the project", async () => {
    const user = userEvent.setup();
    render(<FileActions path="/media/image.png" metadata={{ path: "/media/image.png", relative_path: null }} />);
    await user.click(screen.getByRole("button", { name: "File actions for image.png" }));
    expect(screen.getByRole("menuitem", { name: "Copy relative path" })).toHaveAttribute("data-disabled");
    expect(screen.queryByRole("menuitem", { name: "Preview" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Copy absolute path" }));
    expect(copyTextToClipboard).toHaveBeenCalledWith("/media/image.png");
  });

  it("retains the original reference if resolution fails and reports clipboard errors", async () => {
    const user = userEvent.setup();
    vi.mocked(copyTextToClipboard).mockResolvedValue(false);
    render(<FileActionsProvider value={{ resolveMetadata: vi.fn().mockRejectedValue(new Error("404")), openPreview: vi.fn() }}>
      <FileReferenceChip path="missing.txt" onOpen={vi.fn()} />
    </FileActionsProvider>);
    await user.click(screen.getByRole("button", { name: "File actions for missing.txt" }));
    expect(await screen.findByText(/Could not resolve this file/)).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Copy absolute path" })).toHaveAttribute("data-disabled");
    await user.click(screen.getByRole("menuitem", { name: "Copy reference" }));
    expect(copyTextToClipboard).toHaveBeenCalledWith("missing.txt");
    expect(await screen.findByText("Could not copy. Please try again.")).toBeVisible();
  });

  it("ignores late metadata from a previous session", async () => {
    const user = userEvent.setup();
    let resolveOld!: (value: FileReferenceMetadata) => void;
    const previous = { resolveMetadata: () => new Promise<FileReferenceMetadata>((resolve) => { resolveOld = resolve; }), openPreview: vi.fn() };
    const current = { resolveMetadata: vi.fn().mockResolvedValue({ path: "/new/notes.md", relative_path: "notes.md" }), openPreview: vi.fn() };
    const view = (value: typeof current | typeof previous) => <FileActionsProvider value={value}><FileReferenceChip path="notes.md" onOpen={vi.fn()} /></FileActionsProvider>;
    const { rerender } = render(view(previous));
    await user.click(screen.getByRole("button", { name: "File actions for notes.md" }));
    rerender(view(current));
    await waitFor(() => expect(current.resolveMetadata).toHaveBeenCalled());
    await act(async () => resolveOld(details));
    await user.click(screen.getByRole("menuitem", { name: "Copy absolute path" }));
    expect(copyTextToClipboard).toHaveBeenCalledWith("/new/notes.md");
  });

  it("degrades to the original reference on an older gateway response", async () => {
    const user = userEvent.setup();
    render(<FileActionsProvider value={{ resolveMetadata: vi.fn().mockResolvedValue({ path: "/workspace/notes.md", content: "old preview response" }), openPreview: vi.fn() }}>
      <FileReferenceChip path="notes.md" onOpen={vi.fn()} />
    </FileActionsProvider>);
    await user.click(screen.getByRole("button", { name: "File actions for notes.md" }));
    expect(await screen.findByText(/Could not resolve this file/)).toBeVisible();
    expect(screen.getByRole("menuitem", { name: "Copy absolute path" })).toHaveAttribute("data-disabled");
    await user.click(screen.getByRole("menuitem", { name: "Copy reference" }));
    expect(copyTextToClipboard).toHaveBeenCalledWith("notes.md");
  });
});
