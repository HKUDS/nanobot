import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
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
  it("mounts details on first expansion and preserves their state across folding", () => {
    const mounted = vi.fn();
    function Details() {
      const [count, setCount] = useState(() => { mounted(); return 0; });
      return <button onClick={() => setCount(count + 1)}>Count {count}</button>;
    }
    const shell = (expanded: boolean) => (
      <ThinkingReasoningShell active={false} expanded={expanded} label="Thought"
        viewportRef={null} contentRef={null} fadeTop={false} fadeBottom={false}
        onToggle={() => {}} onScroll={() => {}}><Details /></ThinkingReasoningShell>
    );
    const view = render(shell(false));
    expect(mounted).toHaveBeenCalledTimes(0);
    view.rerender(shell(true));
    fireEvent.click(screen.getByText("Count 0"));
    view.rerender(shell(false));
    view.rerender(shell(true));
    expect(screen.getByRole("button", { name: "Count 1" })).toBeVisible();
    expect(mounted).toHaveBeenCalledTimes(1);
  });
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
