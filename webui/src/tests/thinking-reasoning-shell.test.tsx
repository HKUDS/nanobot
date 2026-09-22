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
      onToggle={vi.fn()}
    >
      <button type="button">Hidden action</button>
    </ThinkingReasoningShell>,
  );
}

describe("ThinkingReasoningShell", () => {
  it.each([false, true])("shows activity without clipping or edge fades (active: %s)", (active) => {
    render(
      <ThinkingReasoningShell
        active={active}
        expanded
        label={active ? "Working" : "Worked"}
        onToggle={vi.fn()}
      >
        {Array.from({ length: 16 }, (_, index) => <div key={index}>Activity {index + 1}</div>)}
      </ThinkingReasoningShell>
    );
    const content = screen.getByTestId("agent-activity-content");
    expect(content).not.toHaveClass("max-h-[180px]");
    expect(content).not.toHaveClass("overflow-y-auto");
    expect(screen.queryByTestId("activity-scroll-fade-top")).not.toBeInTheDocument();
    expect(screen.queryByTestId("activity-scroll-fade-bottom")).not.toBeInTheDocument();
    expect(screen.getByText("Activity 1")).toBeVisible();
    expect(screen.getByText("Activity 16")).toBeVisible();
  });

  it("keeps the same header and content layout when live activity completes", () => {
    const shell = (active: boolean) => (
      <ThinkingReasoningShell active={active} expanded label={active ? "Working" : "Worked"}
        collapseLabel="Collapse activity details" onToggle={vi.fn()}>
        <p>A processing step</p>
      </ThinkingReasoningShell>
    );
    const view = render(shell(true));
    const button = screen.getByRole("button", { name: "Working · Collapse activity details" });
    const content = screen.getByTestId("agent-activity-content");
    const headerClass = button.className;
    const contentClass = content.className;
    expect(button.querySelector("svg")).toHaveClass("lucide-activity");
    expect(view.container.querySelector("[data-contextual-activity-guide]")).toBeInTheDocument();

    view.rerender(shell(false));

    expect(screen.getByRole("button", { name: "Worked · Collapse activity details" })).toBe(button);
    expect(button.className).toBe(headerClass);
    expect(screen.getByTestId("agent-activity-content")).toBe(content);
    expect(content.className).toBe(contentClass);
  });

  it("aligns the waiting status with the disclosure shown when details arrive", () => {
    const shell = (hasDetails: boolean) => (
      <ThinkingReasoningShell active expanded hasDetails={hasDetails} label="Working"
        onToggle={vi.fn()}><p>A processing step</p></ThinkingReasoningShell>
    );
    const view = render(shell(false));
    const status = screen.getByRole("status", { name: "Working" });
    expect(status).toHaveClass("touch-target", "h-7", "px-1.5");
    expect(status.querySelector("svg")).toHaveClass("lucide-activity");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    view.rerender(shell(true));
    expect(screen.getByRole("button", { name: "Working" })).toHaveClass(...status.classList);
  });

  it("mounts details on first expansion and preserves their state across folding", () => {
    const mounted = vi.fn();
    function Details() {
      const [count, setCount] = useState(() => { mounted(); return 0; });
      return <button onClick={() => setCount(count + 1)}>Count {count}</button>;
    }
    const shell = (expanded: boolean) => (
      <ThinkingReasoningShell active={false} expanded={expanded} label="Thought"
        onToggle={() => {}}><Details /></ThinkingReasoningShell>
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
    const collapsible = disclosure.parentElement?.nextElementSibling;

    expect(collapsible).toHaveAttribute("inert");
    expect(collapsible).toHaveAttribute("aria-hidden", "true");

    rerender(
      <ThinkingReasoningShell
        active={false}
        expanded
        label="Thought"
        onToggle={vi.fn()}
      >
        <button type="button">Hidden action</button>
      </ThinkingReasoningShell>,
    );

    const expandedCollapsible = disclosure.parentElement?.nextElementSibling;
    expect(expandedCollapsible).not.toHaveAttribute("inert");
    expect(expandedCollapsible).toHaveAttribute("aria-hidden", "false");
  });
});
