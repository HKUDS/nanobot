import { describe, expect, it } from "vitest";

import {
  EMPTY_WORKBENCH_STATE,
  MAX_WORKBENCH_PANES,
  addWorkbenchPane,
  attachWorkbenchPane,
  createWorkbenchTab,
  detachWorkbenchPane,
  dissolveWorkbenchTab,
  normalizeWorkbenchState,
  orderWorkbenchTabs,
  reconcileWorkbench,
  renameWorkbenchTab,
  setWorkbenchLayout,
  setWorkbenchPaneLayoutOrder,
  setWorkbenchSplitRatios,
  workbenchTab,
  workbenchTabForPane,
} from "@/components/workbench/workbench-model";

describe("workbench model", () => {
  it("derives standalone panes without persisting virtual tabs", () => {
    const match = workbenchTabForPane(EMPTY_WORKBENCH_STATE, "pane-a");

    expect(match.tabKey).not.toBe("pane-a");
    expect(match.tab).toEqual({
      explicit: false,
      title: null,
      paneKeys: ["pane-a"],
      layoutPaneKeys: ["pane-a"],
      layout: "columns",
      splitRatios: [],
    });
    expect(EMPTY_WORKBENCH_STATE.tabs).toEqual({});
  });

  it("persists only a visible singleton group", () => {
    const state = createWorkbenchTab(EMPTY_WORKBENCH_STATE, "pane-a");
    const match = workbenchTabForPane(state, "pane-a");

    expect(workbenchTab(state, match.tabKey)).toMatchObject({
      explicit: true,
      paneKeys: ["pane-a"],
    });
    expect(detachWorkbenchPane(state, match.tabKey, "pane-a").tabs).toEqual({});
  });

  it("materializes a group when a pane is added", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = setWorkbenchLayout(state, tabKey, "main-stack");
    state = renameWorkbenchTab(state, tabKey, "Research");

    expect(workbenchTab(state, tabKey)).toEqual({
      explicit: true,
      title: "Research",
      paneKeys: ["pane-a", "pane-b"],
      layoutPaneKeys: ["pane-a", "pane-b"],
      layout: "main-stack",
      splitRatios: [],
    });
  });

  it("preserves a named group when a pane is detached", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = renameWorkbenchTab(state, tabKey, "Research");
    state = detachWorkbenchPane(state, tabKey, "pane-b");

    expect(workbenchTab(state, tabKey)).toEqual({
      explicit: true,
      title: "Research",
      paneKeys: ["pane-a"],
      layoutPaneKeys: ["pane-a"],
      layout: "columns",
      splitRatios: [],
    });
    expect(normalizeWorkbenchState(state)).toEqual(state);
    expect(reconcileWorkbench(state, new Set(["pane-a"]))).toEqual(state);
  });

  it("detaches a pane without persisting its standalone projection", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = createWorkbenchTab(state, "pane-a");
    state = addWorkbenchPane(state, "pane-a", "pane-c");
    state = detachWorkbenchPane(state, tabKey, "pane-a");

    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual(["pane-b", "pane-c"]);
    expect(workbenchTabForPane(state, "pane-a").tab.paneKeys).toEqual(["pane-a"]);
    expect(Object.values(state.tabs).some((tab) => tab.paneKeys.includes("pane-a"))).toBe(false);
  });

  it("dissolves a group into derived standalone panes", () => {
    const grouped = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const tabKey = workbenchTabForPane(grouped, "pane-a").tabKey;
    const state = dissolveWorkbenchTab(grouped, tabKey);

    expect(state.tabs).toEqual({});
    expect(workbenchTabForPane(state, "pane-a").tab.paneKeys).toEqual(["pane-a"]);
    expect(workbenchTabForPane(state, "pane-b").tab.paneKeys).toEqual(["pane-b"]);
  });

  it("moves panes symmetrically and removes an implicit singleton source", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const sourceTabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = createWorkbenchTab(state, "pane-c");
    const targetTabKey = workbenchTabForPane(state, "pane-c").tabKey;

    state = attachWorkbenchPane(state, targetTabKey, "pane-a");
    expect(workbenchTab(state, sourceTabKey)).toBeNull();
    expect(workbenchTab(state, targetTabKey)?.paneKeys).toEqual(["pane-c", "pane-a"]);

    state = attachWorkbenchPane(state, targetTabKey, "pane-b");
    expect(workbenchTab(state, targetTabKey)?.paneKeys).toEqual([
      "pane-c",
      "pane-a",
      "pane-b",
    ]);
  });

  it("keeps membership independent from workspace pane order", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    state = addWorkbenchPane(state, "pane-a", "pane-c");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;

    const [ordered] = orderWorkbenchTabs(
      state,
      ["pane-c", "pane-a", "pane-b"],
      new Map(),
    );
    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual(["pane-a", "pane-b", "pane-c"]);
    expect(ordered.paneKeys).toEqual(["pane-c", "pane-a", "pane-b"]);

    state = setWorkbenchPaneLayoutOrder(state, tabKey, ["pane-b", "pane-c", "pane-a"]);
    expect(workbenchTab(state, tabKey)?.layoutPaneKeys).toEqual([
      "pane-b",
      "pane-c",
      "pane-a",
    ]);
  });

  it("stores resize ratios and resets them when geometry changes", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-b");
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    state = setWorkbenchSplitRatios(state, tabKey, [0.35]);

    expect(workbenchTab(state, tabKey)?.splitRatios).toEqual([0.35]);
    state = setWorkbenchLayout(state, tabKey, "rows");
    expect(workbenchTab(state, tabKey)?.splitRatios).toEqual([]);
  });

  it("keeps groups contiguous and ranks them by their latest pane", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-c");
    state = addWorkbenchPane(state, "pane-b", "pane-d");
    const alphaTabKey = workbenchTabForPane(state, "pane-a").tabKey;
    const betaTabKey = workbenchTabForPane(state, "pane-b").tabKey;

    const tabs = orderWorkbenchTabs(
      state,
      ["pane-d", "pane-c", "pane-b", "pane-a", "pane-e"],
      new Map([
        ["pane-a", "2026-08-01T10:00:00Z"],
        ["pane-b", "2026-08-03T10:00:00Z"],
        ["pane-c", "2026-08-05T10:00:00Z"],
        ["pane-d", "2026-08-04T10:00:00Z"],
        ["pane-e", "2026-08-02T10:00:00Z"],
      ]),
    );

    expect(tabs.map(({ tabKey, paneKeys }) => ({ tabKey, paneKeys }))).toEqual([
      { tabKey: alphaTabKey, paneKeys: ["pane-c", "pane-a"] },
      { tabKey: betaTabKey, paneKeys: ["pane-d", "pane-b"] },
      { tabKey: workbenchTabForPane(state, "pane-e").tabKey, paneKeys: ["pane-e"] },
    ]);
    expect(Object.keys(state.tabs)).toHaveLength(2);
  });

  it("caps a group at four panes", () => {
    let state = addWorkbenchPane(EMPTY_WORKBENCH_STATE, "pane-a", "pane-1");
    for (let index = 2; index <= MAX_WORKBENCH_PANES; index += 1) {
      state = addWorkbenchPane(state, "pane-a", `pane-${index}`);
    }
    const tabKey = workbenchTabForPane(state, "pane-a").tabKey;
    expect(workbenchTab(state, tabKey)?.paneKeys).toEqual([
      "pane-a",
      "pane-1",
      "pane-2",
      "pane-3",
    ]);
  });

  it("repairs persisted groups without materializing missing sessions", () => {
    const state = normalizeWorkbenchState({
      version: 1,
      tabs: {
        alpha: {
          title: "Alpha",
          paneKeys: ["pane-a", "pane-b", "pane-b", 9],
          layout: "unknown",
        },
        duplicate: {
          paneKeys: ["pane-b", "deleted"],
          layout: "grid",
        },
        invisible: {
          paneKeys: ["pane-c"],
          layout: "columns",
        },
      },
    });
    const reconciled = reconcileWorkbench(
      state,
      new Set(["pane-a", "pane-b", "pane-c"]),
    );

    expect(workbenchTab(reconciled, "alpha")).toEqual({
      explicit: true,
      title: "Alpha",
      paneKeys: ["pane-a", "pane-b"],
      layoutPaneKeys: ["pane-a", "pane-b"],
      layout: "columns",
      splitRatios: [],
    });
    expect(Object.keys(reconciled.tabs)).toEqual(["alpha"]);
    expect(workbenchTabForPane(reconciled, "pane-c").tab.paneKeys).toEqual(["pane-c"]);
  });

  it("keeps persisted state sparse with thousands of standalone sessions", () => {
    const sessionKeys = Array.from({ length: 2_000 }, (_, index) => `pane-${index}`);
    const reconciled = reconcileWorkbench(EMPTY_WORKBENCH_STATE, new Set(sessionKeys));
    const ordered = orderWorkbenchTabs(reconciled, sessionKeys, new Map());

    expect(reconciled.tabs).toEqual({});
    expect(ordered).toHaveLength(2_000);
  });
});
