import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "@/components/ui/segmented-control";

function setGeometry(
  item: HTMLElement,
  geometry: { left: number; top?: number; width: number; height?: number },
) {
  Object.defineProperties(item, {
    offsetLeft: { configurable: true, value: geometry.left },
    offsetTop: { configurable: true, value: geometry.top ?? 4 },
    offsetWidth: { configurable: true, value: geometry.width },
    offsetHeight: { configurable: true, value: geometry.height ?? 24 },
  });
}

function Example({
  mode = "buttons",
  animateIndicator = true,
}: {
  mode?: "buttons" | "tabs";
  animateIndicator?: boolean;
}) {
  const [value, setValue] = useState("summary");
  return (
    <SegmentedControl
      value={value}
      mode={mode}
      animateIndicator={animateIndicator}
      ariaLabel="File edit display"
      options={[
        { value: "summary", label: "Summary" },
        { value: "diff", label: "Diff" },
        { value: "collapsed", label: "Collapsed diff" },
      ]}
      onChange={setValue}
    />
  );
}

describe("SegmentedControl", () => {
  it("moves one shared indicator while the segment labels stay in place", () => {
    const { container } = render(<Example />);
    const summary = screen.getByRole("button", { name: "Summary" });
    const diff = screen.getByRole("button", { name: "Diff" });
    const collapsed = screen.getByRole("button", { name: "Collapsed diff" });
    setGeometry(summary, { left: 4, width: 64 });
    setGeometry(diff, { left: 72, width: 48 });
    setGeometry(collapsed, { left: 124, width: 92 });

    fireEvent(window, new Event("resize"));
    const indicator = container.querySelector<HTMLElement>(
      "[data-segmented-control-indicator]",
    );
    expect(indicator).not.toBeNull();
    expect(indicator).toHaveStyle({
      top: "4px",
      width: "64px",
      height: "24px",
      transform: "translate3d(4px, 0, 0)",
    });
    expect(indicator).toHaveAttribute("aria-hidden", "true");
    expect(indicator).toHaveAttribute("data-animate", "false");

    fireEvent.click(diff);

    expect(indicator).toHaveStyle({
      width: "48px",
      transform: "translate3d(72px, 0, 0)",
    });
    expect(indicator).toHaveAttribute("data-animate", "true");
    expect(summary).toHaveAttribute("aria-pressed", "false");
    expect(diff).toHaveAttribute("aria-pressed", "true");
  });

  it("uses roving focus and arrow-key activation for tabs", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        value="summary"
        mode="tabs"
        ariaLabel="Views"
        options={[
          { value: "summary", label: "Summary" },
          { value: "diff", label: "Diff" },
        ]}
        onChange={onChange}
      />,
    );
    const summary = screen.getByRole("tab", { name: "Summary" });
    const diff = screen.getByRole("tab", { name: "Diff" });
    expect(summary).toHaveAttribute("tabindex", "0");
    expect(diff).toHaveAttribute("tabindex", "-1");

    summary.focus();
    fireEvent.keyDown(summary, { key: "ArrowRight" });

    expect(onChange).toHaveBeenCalledWith("diff");
    expect(diff).toHaveFocus();
  });

  it("can disable motion when the set of segments is dynamic", () => {
    const { container } = render(<Example animateIndicator={false} />);
    const summary = screen.getByRole("button", { name: "Summary" });
    const diff = screen.getByRole("button", { name: "Diff" });
    setGeometry(summary, { left: 4, width: 64 });
    setGeometry(diff, { left: 72, width: 48 });

    fireEvent(window, new Event("resize"));
    fireEvent.click(diff);

    expect(
      container.querySelector("[data-segmented-control-indicator]"),
    ).toHaveAttribute("data-animate", "false");
  });
});
