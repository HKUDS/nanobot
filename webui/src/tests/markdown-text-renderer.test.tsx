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

  it("renders markdown videos as inline players", () => {
    render(<MarkdownTextRenderer>![nanobot-intro.mp4](/api/media/sig/video)</MarkdownTextRenderer>);

    const video = screen.getByLabelText("Video attachment: nanobot-intro.mp4");
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/video");
    expect(video).toHaveAttribute("controls");
    expect(screen.queryByRole("img", { name: "nanobot-intro.mp4" })).not.toBeInTheDocument();
  });
});
