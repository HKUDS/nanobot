import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MarkdownTextRenderer from "@/components/MarkdownTextRenderer";

describe("MarkdownTextRenderer", () => {
  it("renders markdown images as inline previews", () => {
    render(<MarkdownTextRenderer>![Diagram](/api/media/sig/payload)</MarkdownTextRenderer>);

    const image = screen.getByRole("img", { name: "Diagram" });
    expect(image).toHaveAttribute("src", "/api/media/sig/payload");
    expect(screen.getByRole("link", { name: "Open Diagram" })).toHaveAttribute(
      "href",
      "/api/media/sig/payload",
    );
    expect(screen.getByText("Diagram")).toBeInTheDocument();
  });

  it("renders markdown video references as inline players", () => {
    const { container } = render(
      <MarkdownTextRenderer>![Product intro](/api/media/sig/payload#intro.mp4)</MarkdownTextRenderer>,
    );

    const video = screen.getByLabelText("Product intro");
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/payload#intro.mp4");
    expect(container.querySelector("video[controls]")).toBeInTheDocument();
    expect(screen.getByText("Product intro")).toBeInTheDocument();
  });
});
