import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThreadComposer } from "@/components/thread/ThreadComposer";

describe("ThreadComposer", () => {
  it("renders a readonly hero model composer when provided", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="claude-opus-4-5"
        placeholder="Ask anything..."
        variant="hero"
      />,
    );

    expect(screen.getByText("claude-opus-4-5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reason" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deep research" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice input" })).not.toBeInTheDocument();
    const input = screen.getByPlaceholderText("Ask anything...");
    expect(input).toBeInTheDocument();
    expect(input.className).toContain("min-h-[78px]");
    expect(input.parentElement?.className).toContain("max-w-[58rem]");
  });

  it("keeps the thread composer compact while matching the hero style", () => {
    render(
      <ThreadComposer
        onSend={vi.fn()}
        modelLabel="gpt-4o"
        placeholder="Type your message..."
      />,
    );

    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Type your message...");
    expect(input.className).toContain("min-h-[50px]");
    expect(input.parentElement?.className).toContain("max-w-[49.5rem]");
    expect(input.parentElement?.className).toContain("rounded-[22px]");
    expect(input.parentElement?.className).toContain("shadow-[0_12px_30px_rgba(15,23,42,0.07)]");
    expect(screen.getByRole("button", { name: "Attach image" }).className).toContain("bg-card");
    expect(screen.getByRole("button", { name: "Send message" }).className).toContain("bg-foreground");
  });
});
