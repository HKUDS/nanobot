import { describe, expect, it } from "vitest";

import {
  paneDropSlotForRow,
  paneTabDragLayout,
  samePaneDropSlot,
  type PaneTabDragState,
} from "@/components/pane-tab-drag";

function drag(overrides: Partial<PaneTabDragState> = {}): PaneTabDragState {
  return {
    origin: "pane",
    item: { paneKey: "pane-a", sourceTabKey: "tab-a" },
    height: 32,
    slot: null,
    ...overrides,
  };
}

describe("Pane tab drag state", () => {
  it("turns a pointer edge into one stable insertion slot", () => {
    const before = paneDropSlotForRow(
      "tab-a",
      ["pane-a", "pane-b", "pane-c"],
      "pane-a",
      "pane-b",
      "before",
    );
    const after = paneDropSlotForRow(
      "tab-a",
      ["pane-a", "pane-b", "pane-c"],
      "pane-a",
      "pane-b",
      "after",
    );

    expect(before).toEqual({ tabKey: "tab-a", beforePaneKey: "pane-b" });
    expect(after).toEqual({ tabKey: "tab-a", beforePaneKey: "pane-c" });
    expect(samePaneDropSlot(after, { ...after })).toBe(true);
  });

  it("moves the dragged slot and repels siblings inside one tab", () => {
    const layout = paneTabDragLayout(
      ["pane-a", "pane-b", "pane-c"],
      "tab-a",
      drag({ slot: { tabKey: "tab-a", beforePaneKey: "pane-c" } }),
    );

    expect(layout.slotIndex).toBe(1);
    expect(Object.fromEntries(layout.offsets)).toEqual({
      "pane-b": -34,
    });
  });

  it("does not expose a slot in another tab", () => {
    const layout = paneTabDragLayout(
      ["pane-x", "pane-y"],
      "tab-b",
      drag({ slot: { tabKey: "tab-b", beforePaneKey: "pane-y" } }),
    );

    expect(layout.slotIndex).toBe(-1);
    expect(Object.fromEntries(layout.offsets)).toEqual({});
  });
});
