import { describe, expect, it } from "vitest";

import {
  EMPTY_WORKBENCH_STATE,
  MAX_WORKBENCH_PANES,
  addWorkbenchPane,
  attachWorkbenchPane,
  createWorkbenchTab,
  detachWorkbenchPane,
  dissolveWorkbenchTab,
  ensureWorkbenchPaneTab,
  focusWorkbenchPane,
  normalizeWorkbenchState,
  orderWorkbenchTabs,
  reconcileWorkbench,
  renameWorkbenchTab,
  setWorkbenchLayout,
  setWorkbenchPaneLayoutOrder,
  setWorkbenchSplitRatios,
  workbenchTab,
  workbenchTabForPane,
  type WorkbenchState,
} from "@/components/workbench/workbench-model";

function withPaneTab(
  state: WorkbenchState,
  paneKey: string,
): [WorkbenchState, string] {
  const next = ensureWorkbenchPaneTab(state, paneKey);
  return [next, workbenchTabForPane(next, paneKey).tabKey];
}

describe("workbench model", () => {
  it("creates a virtual tab whose identity is separate from its pane", () => {
    const [state, tabKey] = withPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");

    expect(tabKey).not.toBe("pane-a");
    expect(workbenchTab(state, tabKey)).toEqual({
      explicit: false,
      title: null,
      paneKeys: ["pane-a"],
      layoutPaneKeys: ["pane-a"],
      activePaneKey: "pane-a",
      layout: "columns",
      splitRatios: [],
    });
  });

  it("keeps pane membership, focus, title, and layout scoped to a tab", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const alphaTabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = ensureWorkbenchPaneTab(state, "pane-b");
    const betaTabKey = workbenchTabForPane(state, "pane-b").tabKey;
    state = addWorkbenchPane(state, alphaTabKey, "pane-c");
    state = setWorkbenchLayout(state, alphaTabKey, "main-stack");
    state = renameWorkbenchTab(state, alphaTabKey, "Research");

    expect(workbenchTab(state, alphaTabKey)).toEqual({
      explicit: false,
      title: "Research",
      paneKeys: ["pane-a", "pane-c"],
      layoutPaneKeys: ["pane-a", "pane-c"],
      activePaneKey: "pane-c",
      layout: "main-stack",
      splitRatios: [],
    });
    expect(workbenchTab(state, betaTabKey)).toEqual({
      explicit: false,
      title: null,
      paneKeys: ["pane-b"],
      layoutPaneKeys: ["pane-b"],
      activePaneKey: "pane-b",
      layout: "columns",
      splitRatios: [],
    });
  });

  it("focuses a pane without rewriting membership", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, tabKey, "pane-b");
    state = addWorkbenchPane(state, tabKey, "pane-c");
    state = focusWorkbenchPane(state, tabKey, "pane-b");

    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual([
      "pane-a",
      "pane-b",
      "pane-c",
    ]);
    expect(workbenchTab(state, tabKey)?.activePaneKey).toBe("pane-b");
  });

  it("detaches any pane into a new virtual tab", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, tabKey, "pane-b");
    state = addWorkbenchPane(state, tabKey, "pane-c");
    state = focusWorkbenchPane(state, tabKey, "pane-a");
    state = detachWorkbenchPane(state, tabKey, "pane-a");

    expect(workbenchTab(state, tabKey)).toMatchObject({
      paneKeys: ["pane-b", "pane-c"],
      activePaneKey: "pane-b",
    });
    const detached = workbenchTabForPane(state, "pane-a");
    expect(detached.tabKey).not.toBe(tabKey);
    expect(detached.tab.paneKeys).toEqual(["pane-a"]);
  });

  it("dissolves a tab into standalone panes without deleting them", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, tabKey, "pane-b");
    state = addWorkbenchPane(state, tabKey, "pane-c");
    state = dissolveWorkbenchTab(state, tabKey);

    expect(workbenchTab(state, tabKey)).toEqual({
      explicit: false,
      title: null,
      paneKeys: ["pane-a"],
      layoutPaneKeys: ["pane-a"],
      activePaneKey: "pane-a",
      layout: "columns",
      splitRatios: [],
    });
    expect(workbenchTabForPane(state, "pane-a").tab.paneKeys).toEqual(["pane-a"]);
    expect(workbenchTabForPane(state, "pane-b").tab.paneKeys).toEqual(["pane-b"]);
    expect(workbenchTabForPane(state, "pane-c").tab.paneKeys).toEqual(["pane-c"]);
    expect(Object.keys(state.tabs)).toHaveLength(3);
  });

  it("makes a singleton tab visible without changing pane membership", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;

    state = createWorkbenchTab(state, tabKey);
    expect(workbenchTab(state, tabKey)).toMatchObject({
      explicit: true,
      paneKeys: ["pane-a"],
      activePaneKey: "pane-a",
    });

    state = detachWorkbenchPane(state, tabKey, "pane-a");
    expect(workbenchTab(state, tabKey)).toEqual({
      explicit: false,
      title: null,
      paneKeys: ["pane-a"],
      layoutPaneKeys: ["pane-a"],
      activePaneKey: "pane-a",
      layout: "columns",
      splitRatios: [],
    });
  });

  it("moves every pane symmetrically and removes an empty source tab", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const alphaTabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, alphaTabKey, "pane-b");
    state = ensureWorkbenchPaneTab(state, "pane-c");
    const targetTabKey = workbenchTabForPane(state, "pane-c").tabKey;

    state = attachWorkbenchPane(state, targetTabKey, "pane-a");
    expect(workbenchTab(state, alphaTabKey)?.paneKeys).toEqual(["pane-b"]);
    expect(workbenchTab(state, targetTabKey)?.paneKeys).toEqual(["pane-c", "pane-a"]);

    state = attachWorkbenchPane(state, targetTabKey, "pane-b");
    expect(workbenchTab(state, alphaTabKey)).toBeNull();
    expect(workbenchTab(state, targetTabKey)?.paneKeys).toEqual([
      "pane-c",
      "pane-a",
      "pane-b",
    ]);
  });

  it("keeps membership independent from projected display order", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, tabKey, "pane-b");
    state = addWorkbenchPane(state, tabKey, "pane-c");

    const [ordered] = orderWorkbenchTabs(
      state,
      ["pane-c", "pane-a", "pane-b"],
      new Map(),
    );
    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual(["pane-a", "pane-b", "pane-c"]);
    expect(ordered.paneKeys).toEqual(["pane-c", "pane-a", "pane-b"]);

    state = setWorkbenchPaneLayoutOrder(state, tabKey, ["pane-b", "pane-c", "pane-a"]);
    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual(["pane-a", "pane-b", "pane-c"]);
    expect(workbenchTab(state, tabKey)?.layoutPaneKeys).toEqual([
      "pane-b",
      "pane-c",
      "pane-a",
    ]);
    expect(ordered.paneKeys).toEqual(["pane-c", "pane-a", "pane-b"]);
  });

  it("stores resize ratios in the tab and resets them when its geometry changes", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, tabKey, "pane-b");
    state = setWorkbenchSplitRatios(state, tabKey, [0.35]);

    expect(workbenchTab(state, tabKey)?.splitRatios).toEqual([0.35]);
    state = setWorkbenchLayout(state, tabKey, "rows");
    expect(workbenchTab(state, tabKey)?.splitRatios).toEqual([]);

    state = setWorkbenchSplitRatios(state, tabKey, [0.4]);
    state = detachWorkbenchPane(state, tabKey, "pane-b");
    expect(workbenchTab(state, tabKey)?.splitRatios).toEqual([]);
  });

  it("keeps each tab contiguous and ranks it by its latest updated pane", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const alphaTabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = addWorkbenchPane(state, alphaTabKey, "pane-c");
    state = ensureWorkbenchPaneTab(state, "pane-b");
    const betaTabKey = workbenchTabForPane(state, "pane-b").tabKey;
    state = addWorkbenchPane(state, betaTabKey, "pane-d");

    const tabs = orderWorkbenchTabs(
      state,
      ["pane-d", "pane-c", "pane-b", "pane-a"],
      new Map([
        ["pane-a", "2026-08-01T10:00:00Z"],
        ["pane-b", "2026-08-03T10:00:00Z"],
        ["pane-c", "2026-08-05T10:00:00Z"],
        ["pane-d", "2026-08-04T10:00:00Z"],
      ]),
    );

    expect(tabs.map(({ tabKey, paneKeys, updatedAt }) => ({
      tabKey,
      paneKeys,
      updatedAt,
    }))).toEqual([
      {
        tabKey: alphaTabKey,
        paneKeys: ["pane-c", "pane-a"],
        updatedAt: "2026-08-05T10:00:00Z",
      },
      {
        tabKey: betaTabKey,
        paneKeys: ["pane-d", "pane-b"],
        updatedAt: "2026-08-04T10:00:00Z",
      },
    ]);
  });

  it("caps every virtual tab at four panes", () => {
    let state = ensureWorkbenchPaneTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    for (let index = 1; index <= MAX_WORKBENCH_PANES; index += 1) {
      state = addWorkbenchPane(state, tabKey, `pane-${index}`);
    }
    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual([
      "pane-a",
      "pane-1",
      "pane-2",
      "pane-3",
    ]);
  });

  it("repairs duplicates, removes deleted panes, and creates missing tabs", () => {
    const state = normalizeWorkbenchState({
      version: 1,
      tabs: {
        alpha: {
          title: "Alpha",
          paneKeys: ["pane-a", "pane-b", "pane-b", 9],
          activePaneKey: "missing",
          layout: "unknown",
        },
        duplicate: {
          paneKeys: ["pane-b", "deleted"],
          activePaneKey: "pane-b",
          layout: "grid",
        },
      },
    });
    const reconciled = reconcileWorkbench(
      state,
      new Set(["pane-a", "pane-b", "pane-c"]),
    );

    expect(workbenchTab(reconciled, "alpha")).toEqual({
      explicit: false,
      title: "Alpha",
      paneKeys: ["pane-a", "pane-b"],
      layoutPaneKeys: ["pane-a", "pane-b"],
      activePaneKey: "pane-a",
      layout: "columns",
      splitRatios: [],
    });
    expect(workbenchTab(reconciled, "duplicate")).toBeNull();
    expect(workbenchTabForPane(reconciled, "pane-c").tab.paneKeys).toEqual(["pane-c"]);
  });

});
