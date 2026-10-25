import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AttachmentTile } from "@/components/AttachmentTile";

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
    expect(archive).toHaveTextContent("ZIP");
    expect(archive.querySelector(".lucide-download")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("link", { name: "Download source.tar.gz" })).toHaveTextContent("TAR.GZ");
  });

  it("changes a pending file to a download only after its URL arrives", () => {
    const attachment = { kind: "file" as const, name: "report.pdf" };
    const { rerender } = render(<AttachmentTile attachment={attachment} pending />);
    expect(screen.getByText("Sending…")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    rerender(<AttachmentTile attachment={{ ...attachment, url: "/api/media/signed/report" }} />);
    expect(screen.getByRole("link", { name: "Download report.pdf" })).toHaveTextContent("PDF");

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
    expect(unnamed).toHaveTextContent("File attachment");
    expect(unnamed.querySelector(".lucide-file-archive")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download LICENSE" })).toHaveTextContent("File attachment");
  });
});
