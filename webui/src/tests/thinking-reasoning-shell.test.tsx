import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThinkingReasoningShell } from "@/components/thread/activity/ThinkingReasoningShell";

function renderShell(expanded: boolean) {
  return render(
    <ThinkingReasoningShell
      active={false}
      expanded={expanded}
      label="Thought"
      viewportRef={() => undefined}
      contentRef={() => undefined}
      fadeTop={false}
      fadeBottom={false}
      onToggle={vi.fn()}
      onScroll={vi.fn()}
    >
      <button type="button">Hidden action</button>
    </ThinkingReasoningShell>,
  );
}

describe("ThinkingReasoningShell", () => {
  it("makes collapsed descendants inert as well as visually hidden", () => {
    const { rerender } = renderShell(false);
    const disclosure = screen.getByRole("button", { name: "Thought" });
    const collapsible = disclosure.nextElementSibling;

    expect(collapsible).toHaveAttribute("inert");
    expect(collapsible).toHaveAttribute("aria-hidden", "true");

    rerender(
      <ThinkingReasoningShell
        active={false}
        expanded
        label="Thought"
        viewportRef={() => undefined}
        contentRef={() => undefined}
        fadeTop={false}
        fadeBottom={false}
        onToggle={vi.fn()}
        onScroll={vi.fn()}
      >
        <button type="button">Hidden action</button>
      </ThinkingReasoningShell>,
    );

    expect(disclosure.nextElementSibling).not.toHaveAttribute("inert");
    expect(disclosure.nextElementSibling).toHaveAttribute("aria-hidden", "false");
  });
});
