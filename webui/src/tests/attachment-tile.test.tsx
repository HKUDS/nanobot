import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";

import { AttachmentTile } from "@/components/AttachmentTile";
import { MessageBubble } from "@/components/MessageBubble";
import { preloadMarkdownText } from "@/components/MarkdownText";

beforeAll(preloadMarkdownText);

describe("attachment download cards", () => {
  it("keeps named download actions distinct and shows the file extension", () => {
    render(<>
      <AttachmentTile attachment={{ kind: "file", name: "猫咪图鉴完整包.zip", url: "/api/media/signed/archive" }} />
      <AttachmentTile attachment={{ kind: "file", name: "source.tar.gz", url: "/api/media/signed/source" }} />
    </>);

    const archive = screen.getByRole("link", { name: "Download 猫咪图鉴完整包.zip" });
    expect(archive).toHaveAttribute("download", "猫咪图鉴完整包.zip");
    expect(archive).toHaveAttribute("href", "/api/media/signed/archive");
    expect(archive).toHaveAttribute("title", "猫咪图鉴完整包.zip");
    expect(archive.closest("[data-file-attachment]")).toHaveTextContent("ZIP");
    expect(archive.querySelector(".lucide-download")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("link", { name: "Download source.tar.gz" }).closest("[data-file-attachment]")).toHaveTextContent("TAR.GZ");
  });

  it("changes a pending file to a download only after its URL arrives", () => {
    const attachment = { kind: "file" as const, name: "report.pdf" };
    const { rerender } = render(<AttachmentTile attachment={attachment} pending />);
    expect(screen.getByText("Sending")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    rerender(<AttachmentTile attachment={{ ...attachment, url: "/api/media/signed/report" }} />);
    expect(screen.getByRole("link", { name: "Download report.pdf" })).toHaveAttribute("href", "/api/media/signed/report");
    expect(screen.getByText("PDF")).toBeVisible();

    rerender(<AttachmentTile attachment={attachment} />);
    expect(screen.getByText("Attachment unavailable")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps unnamed and extensionless attachments identifiable", () => {
    render(<>
      <AttachmentTile attachment={{ kind: "file", url: "/api/media/signed/archive.zip?signature=example#payload.txt" }} />
      <AttachmentTile attachment={{ kind: "file", name: "LICENSE", url: "/api/media/signed/license" }} />
    </>);
    const unnamed = screen.getByRole("link", { name: "Download File attachment" });
    expect(unnamed).toHaveAttribute("download", "File attachment");
    expect(unnamed.closest("[data-file-attachment]")).toHaveTextContent("ZIP");
    expect(screen.getByRole("link", { name: "Download LICENSE" }).closest("[data-file-attachment]")).toHaveTextContent("File attachment");
  });
});

describe("delivered file type cards", () => {
  it.each(["user", "assistant"] as const)("keeps %s file information and named downloads separate", async (role) => {
    const user = userEvent.setup();
    const { container } = render(<MessageBubble message={{ id: `files-${role}`, role, content: "Files ready", createdAt: 1,
      media: [
        { kind: "file", name: "render-config.json", url: "/api/media/signed/first" },
        { kind: "file", name: "another-config.json", url: "/api/media/signed/second" },
      ] }} />);
    const cards = container.querySelectorAll("[data-file-attachment]");
    expect(Array.from(cards).map((card) => card.textContent)).toEqual(["JSON", "JSON"]);
    const first = within(cards[0] as HTMLElement);
    const download = first.getByRole("link", { name: "Download render-config.json" });
    expect(download).toHaveAttribute("href", "/api/media/signed/first");
    expect(download).toHaveAttribute("download", "render-config.json");
    await user.click(first.getByRole("button", { name: "render-config.json" }));
    expect(await screen.findByRole("dialog", { name: "render-config.json" })).toHaveTextContent("render-config.json");
    await user.keyboard("{Escape}");
    expect(first.getByRole("button", { name: "render-config.json" })).toHaveFocus();
    expect(within(cards[1] as HTMLElement).getByRole("link", { name: "Download another-config.json" })).toHaveAttribute("href", "/api/media/signed/second");
  });

  it("keeps a file link inside its paragraph instead of extracting it into an attachment card", async () => {
    const { container } = render(<MessageBubble message={{ id: "inline-file", role: "assistant", createdAt: 1,
      content: "Before [notes.txt](https://example.com/notes.txt) after.",
      media: [{ kind: "file", name: "report.pdf", url: "/api/media/signed/report" }] }} />);
    const link = await screen.findByRole("link", { name: "notes.txt" });
    expect(link.closest("p")).toHaveTextContent("Before notes.txt after.");
    expect(link).toHaveAttribute("href", "https://example.com/notes.txt");
    expect(container.querySelectorAll("[data-file-attachment]")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Download report.pdf" })).toHaveAttribute("download", "report.pdf");
  });
});
