import { describe, expect, it } from "vitest";

import {
  EMPTY_WORKBENCH_STATE,
  MAX_WORKBENCH_PANES,
  addWorkbenchPane,
  attachWorkbenchPane,
  detachWorkbenchPane,
  ensureWorkbenchTab,
  focusWorkbenchPane,
  parseWorkbenchState,
  promoteWorkbenchPane,
  reconcileWorkbench,
  setWorkbenchLayout,
  workbenchChildPaneKeys,
  workbenchTab,
} from "@/components/workbench/workbench-model";

describe("workbench model", () => {
  it("gives every topic its own one-pane tab by default", () => {
    const state = ensureWorkbenchTab(EMPTY_WORKBENCH_STATE, "topic-a");

    expect(workbenchTab(state, "topic-a")).toEqual({
      paneKeys: ["topic-a"],
      activePaneKey: "topic-a",
      layout: "columns",
    });
    expect(state.tabs["topic-b"]).toBeUndefined();
  });

  it("keeps pane membership, focus, and layout scoped to a tab", () => {
    let state = ensureWorkbenchTab(EMPTY_WORKBENCH_STATE, "topic-a");
    state = ensureWorkbenchTab(state, "topic-b");
    state = addWorkbenchPane(state, "topic-a", "topic-c");
    state = setWorkbenchLayout(state, "topic-a", "main-stack");

    expect(workbenchTab(state, "topic-a")).toEqual({
      paneKeys: ["topic-a", "topic-c"],
      activePaneKey: "topic-c",
      layout: "main-stack",
    });
    expect(workbenchTab(state, "topic-b")).toEqual({
      paneKeys: ["topic-b"],
      activePaneKey: "topic-b",
      layout: "columns",
    });
  });

  it("focuses without reordering and promotes only when asked", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "topic-a", "topic-b");
    state = addWorkbenchPane(state, "topic-a", "topic-c");
    state = focusWorkbenchPane(state, "topic-a", "topic-b");

    expect(workbenchTab(state, "topic-a").paneKeys).toEqual([
      "topic-a",
      "topic-b",
      "topic-c",
    ]);

    state = promoteWorkbenchPane(state, "topic-a", "topic-b");
    expect(workbenchTab(state, "topic-a")).toMatchObject({
      paneKeys: ["topic-b", "topic-a", "topic-c"],
      activePaneKey: "topic-b",
    });
  });

  it("detaches child panes, keeps the root, and chooses the adjacent focus", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "topic-a", "topic-b");
    state = addWorkbenchPane(state, "topic-a", "topic-c");
    state = focusWorkbenchPane(state, "topic-a", "topic-b");
    state = detachWorkbenchPane(state, "topic-a", "topic-b");

    expect(workbenchTab(state, "topic-a")).toMatchObject({
      paneKeys: ["topic-a", "topic-c"],
      activePaneKey: "topic-c",
    });

    state = detachWorkbenchPane(state, "topic-a", "topic-c");
    state = detachWorkbenchPane(state, "topic-a", "topic-a");
    expect(workbenchTab(state, "topic-a").paneKeys).toEqual(["topic-a"]);
  });

  it("moves a pane between tabs and can reattach a one-pane tab", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "topic-a", "pane-a");
    state = ensureWorkbenchTab(state, "topic-b");
    state = attachWorkbenchPane(state, "topic-b", "pane-a");

    expect(workbenchTab(state, "topic-a")).toMatchObject({
      paneKeys: ["topic-a"],
      activePaneKey: "topic-a",
    });
    expect(workbenchTab(state, "topic-b")).toMatchObject({
      paneKeys: ["topic-b", "pane-a"],
      activePaneKey: "pane-a",
    });

    state = ensureWorkbenchTab(state, "topic-c");
    state = attachWorkbenchPane(state, "topic-b", "topic-c");
    expect(state.tabs["topic-c"]).toBeUndefined();
    expect(workbenchTab(state, "topic-b").paneKeys).toEqual([
      "topic-b",
      "pane-a",
      "topic-c",
    ]);
  });

  it("does not collapse a multi-pane tab into another tab", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "topic-a", "pane-a");
    state = ensureWorkbenchTab(state, "topic-b");

    expect(attachWorkbenchPane(state, "topic-b", "topic-a")).toBe(state);
  });

  it("caps every tab at four panes", () => {
    let state = EMPTY_WORKBENCH_STATE;
    for (let index = 1; index <= MAX_WORKBENCH_PANES; index += 1) {
      state = addWorkbenchPane(state, "topic-a", `pane-${index}`);
    }
    expect(workbenchTab(state, "topic-a").paneKeys).toEqual([
      "topic-a",
      "pane-1",
      "pane-2",
      "pane-3",
    ]);

    const beforeAttach = state;
    state = attachWorkbenchPane(state, "topic-a", "standalone");
    expect(state).toBe(beforeAttach);
  });

  it("identifies only sessions attached beneath another topic", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "topic-a", "pane-a");
    state = addWorkbenchPane(state, "topic-b", "pane-b");

    expect(workbenchChildPaneKeys(state)).toEqual(new Set(["pane-a", "pane-b"]));

    state = detachWorkbenchPane(state, "topic-a", "pane-a");
    expect(workbenchChildPaneKeys(state)).toEqual(new Set(["pane-b"]));
  });

  it("repairs persisted state and removes deleted sessions", () => {
    const parsed = parseWorkbenchState(JSON.stringify({
      version: 2,
      tabs: {
        "topic-a": {
          paneKeys: ["topic-a", "topic-b", "topic-b", 9],
          activePaneKey: "missing",
          layout: "unknown",
        },
        deleted: {
          paneKeys: ["deleted"],
          activePaneKey: "deleted",
          layout: "grid",
        },
      },
    }));
    const reconciled = reconcileWorkbench(parsed, new Set(["topic-a"]));

    expect(reconciled).toEqual({
      version: 2,
      tabs: {
        "topic-a": {
          paneKeys: ["topic-a"],
          activePaneKey: "topic-a",
          layout: "columns",
        },
      },
    });
    expect(parseWorkbenchState(JSON.stringify({ version: 1, tabs: {} })))
      .toEqual(EMPTY_WORKBENCH_STATE);
    expect(parseWorkbenchState("not-json")).toEqual(EMPTY_WORKBENCH_STATE);
  });
});
