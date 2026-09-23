import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttachmentTile } from "@/components/AttachmentTile";
import { FileReferenceChip, FileReferenceIcon, fileKindForPath } from "@/components/FileReferenceChip";
import { PreviewPane } from "@/components/PreviewPane";

describe("shared file icons", () => {
  it.each([
    ["chart.png", "file-image"],
    ["chart.svg", "file-image"],
    ["chart.avif", "file-image"],
    ["index.html", "file-code2"],
    ["styles.css", "file-code2"],
    ["app.js", "file-code2"],
    ["app.ts", "file-code2"],
    ["app.tsx", "file-code2"],
    ["script.py", "file-code2"],
    ["analysis.ipynb", "file-code2"],
    ["DATA.JSON", "file-json2"],
    ["README.md", "file-text"],
    ["notes.txt", "file-text"],
    ["build.log", "file-text"],
    ["demo.mp4", "file-video2"],
    ["archive.zip", "file"],
  ])("uses a consistent monochrome file-family icon for %s", (path, icon) => {
    const { container } = render(<FileReferenceIcon kind={fileKindForPath(path)} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveClass(`lucide-${icon}`);
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveAttribute("stroke", "currentColor");
    expect(svg).toHaveAttribute("stroke-width", "1.75");
    expect(svg).toHaveAttribute("fill", "none");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveClass("h-[1em]", "w-[1em]", "shrink-0");
    expect(svg.querySelector("text, [fill], [stroke]")).toBeNull();
  });

  it.each(["chart.png", "index.html", "data.json", "script.py", "notes.md"])(
    "reuses the same glyph for %s in replies, tabs and attachments without changing actions", (path) => {
      const open = vi.fn();
      render(<>
        <FileReferenceChip path={path} onOpen={open} />
        <PreviewPane tabs={[{ id: path, kind: "file", value: path }]} activeId={path}
          width={544} isClosing={false} onSelect={() => {}} onCloseTab={() => {}}
          onClose={() => {}} onResizeStart={() => {}}><p>Preview</p></PreviewPane>
        <AttachmentTile attachment={{ kind: "file", name: path, url: `/download/${path}` }} />
      </>);
      const reference = screen.getByRole("button", { name: path });
      const tab = screen.getByRole("tab", { name: path });
      const attachment = screen.getByRole("link", { name: "File attachment" });
      const glyph = reference.querySelector("svg")!.innerHTML;
      expect(tab.querySelector("svg")!.innerHTML).toBe(glyph);
      expect(attachment.querySelector("svg")!.innerHTML).toBe(glyph);
      expect(tab.querySelector("svg")).toHaveClass("size-3.5");
      expect(attachment.querySelector("svg")).toHaveClass("size-4");
      expect(tab.querySelector("svg")).not.toHaveClass("translate-y-[0.12em]");
      expect(attachment.querySelector("svg")).not.toHaveClass("translate-y-[0.12em]");
      expect(attachment).toHaveAttribute("href", `/download/${path}`);
      expect(attachment).toHaveAttribute("download", path);
      fireEvent.click(reference);
      expect(open).toHaveBeenCalledWith(path);
    },
  );

  it.each(["image", "video"] as const)("retains %s identity when its attachment is unavailable", (kind) => {
    const { container } = render(<AttachmentTile attachment={{ kind, name: "Unavailable" }} />);
    expect(container.querySelector("svg")).toHaveClass(kind === "image" ? "lucide-file-image" : "lucide-file-video2");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Attachment unavailable")).toBeInTheDocument();
  });
});
