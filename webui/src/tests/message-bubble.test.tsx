import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageBubble } from "@/components/MessageBubble";
import type { UIMessage } from "@/lib/types";

describe("MessageBubble", () => {
  it("renders user messages as right-aligned pills", () => {
    const message: UIMessage = {
      id: "u1",
      role: "user",
      content: "hello",
      createdAt: Date.now(),
    };

    const { container } = render(<MessageBubble message={message} />);
    const row = container.firstElementChild;
    const pill = screen.getByText("hello");

    expect(row).toHaveClass("ml-auto", "flex");
    expect(pill).toHaveClass("ml-auto", "w-fit", "rounded-[18px]");
    expect(screen.queryByRole("button", { name: "Copy reply" })).not.toBeInTheDocument();
  });

  it("copies completed assistant replies from the action row", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const message: UIMessage = {
      id: "a-copy",
      role: "assistant",
      content: "I can help with the next step.",
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy reply" }));

    expect(writeText).toHaveBeenCalledWith("I can help with the next step.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copied reply" })).toBeInTheDocument(),
    );
  });

  it("does not show copy actions for streaming placeholders", () => {
    const message: UIMessage = {
      id: "a-streaming",
      role: "assistant",
      content: "",
      isStreaming: true,
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);

    expect(screen.queryByRole("button", { name: "Copy reply" })).not.toBeInTheDocument();
  });

  it("renders trace messages as collapsible tool groups", () => {
    const message: UIMessage = {
      id: "t1",
      role: "tool",
      kind: "trace",
      content: 'search "hk weather"',
      traces: ['weather("get")', 'search "hk weather"'],
      createdAt: Date.now(),
    };

    render(<MessageBubble message={message} />);
    const toggle = screen.getByRole("button", { name: /used 2 tools/i });

    expect(screen.getByText('weather("get")')).toBeInTheDocument();
    expect(screen.getByText('search "hk weather"')).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByText('weather("get")')).not.toBeInTheDocument();
  });

  it("renders video media as an inline player", () => {
    const message: UIMessage = {
      id: "a1",
      role: "assistant",
      content: "here is the clip",
      createdAt: Date.now(),
      media: [
        {
          kind: "video",
          url: "/api/media/sig/payload",
          name: "demo.mp4",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    expect(screen.getByText("here is the clip")).toBeInTheDocument();
    const video = screen.getByLabelText(/video attachment/i);
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("src", "/api/media/sig/payload");
    expect(container.querySelector("video[controls]")).toBeInTheDocument();
  });

  it("renders assistant image media as a larger generated result", () => {
    const message: UIMessage = {
      id: "a-image",
      role: "assistant",
      content: "done",
      createdAt: Date.now(),
      media: [
        {
          kind: "image",
          url: "/api/media/sig/image",
          name: "generated.png",
        },
      ],
    };

    const { container } = render(<MessageBubble message={message} />);

    const imageButton = screen.getByRole("button", { name: /view image/i });
    expect(imageButton).toHaveClass("h-56", "sm:h-72");
    expect(container.querySelector("img")).toHaveClass("object-contain");
  });
});
