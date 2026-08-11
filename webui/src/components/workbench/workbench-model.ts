export const WORKBENCH_STORAGE_KEY = "nanobot.webui.workbench.v2";
export const MAX_WORKBENCH_PANES = 4;

export const WORKBENCH_LAYOUTS = [
  "columns",
  "rows",
  "grid",
  "main-stack",
  "monocle",
] as const;

export type WorkbenchLayout = (typeof WORKBENCH_LAYOUTS)[number];

export interface WorkbenchTabState {
  paneKeys: string[];
  activePaneKey: string;
  layout: WorkbenchLayout;
}

export interface WorkbenchState {
  version: 2;
  tabs: Record<string, WorkbenchTabState>;
}

export const EMPTY_WORKBENCH_STATE: WorkbenchState = {
  version: 2,
  tabs: {},
};

function isLayout(value: unknown): value is WorkbenchLayout {
  return typeof value === "string"
    && (WORKBENCH_LAYOUTS as readonly string[]).includes(value);
}

function uniqueKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(new Set(
    value.filter((key): key is string => typeof key === "string" && key.length > 0),
  ));
}

function insertPaneBefore(
  paneKeys: string[],
  paneKey: string,
  beforePaneKey?: string | null,
): string[] {
  const next = paneKeys.filter((key) => key !== paneKey);
  const requestedIndex = beforePaneKey && beforePaneKey !== paneKey
    ? next.indexOf(beforePaneKey)
    : -1;
  next.splice(requestedIndex < 0 ? next.length : requestedIndex, 0, paneKey);
  return next;
}

function normalizeTab(value: unknown, tabKey: string): WorkbenchTabState {
  const candidate = value && typeof value === "object"
    ? value as Partial<WorkbenchTabState>
    : {};
  const paneKeys = uniqueKeys(candidate.paneKeys);
  const normalizedPaneKeys = (paneKeys.includes(tabKey)
    ? paneKeys
    : [tabKey, ...paneKeys]).slice(0, MAX_WORKBENCH_PANES);
  return {
    paneKeys: normalizedPaneKeys,
    activePaneKey:
      typeof candidate.activePaneKey === "string"
      && normalizedPaneKeys.includes(candidate.activePaneKey)
        ? candidate.activePaneKey
        : normalizedPaneKeys[0],
    layout: isLayout(candidate.layout) ? candidate.layout : "columns",
  };
}

export function parseWorkbenchState(serialized: string | null): WorkbenchState {
  if (!serialized) return EMPTY_WORKBENCH_STATE;
  try {
    const parsed = JSON.parse(serialized) as { version?: unknown; tabs?: unknown };
    if (
      parsed.version !== 2
      || !parsed.tabs
      || typeof parsed.tabs !== "object"
      || Array.isArray(parsed.tabs)
    ) {
      return EMPTY_WORKBENCH_STATE;
    }
    const tabs = Object.fromEntries(
      Object.entries(parsed.tabs).map(([tabKey, tab]) => [tabKey, normalizeTab(tab, tabKey)]),
    );
    return { version: 2, tabs };
  } catch {
    return EMPTY_WORKBENCH_STATE;
  }
}

export function defaultWorkbenchTab(tabKey: string): WorkbenchTabState {
  return {
    paneKeys: [tabKey],
    activePaneKey: tabKey,
    layout: "columns",
  };
}

export function workbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchTabState {
  return state.tabs[tabKey] ?? defaultWorkbenchTab(tabKey);
}

function updateTab(
  state: WorkbenchState,
  tabKey: string,
  update: (tab: WorkbenchTabState) => WorkbenchTabState,
): WorkbenchState {
  const current = workbenchTab(state, tabKey);
  const next = update(current);
  if (state.tabs[tabKey] === next) return state;
  return {
    version: 2,
    tabs: {
      ...state.tabs,
      [tabKey]: next,
    },
  };
}

export function ensureWorkbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchState {
  if (state.tabs[tabKey]) return state;
  return updateTab(state, tabKey, (tab) => tab);
}

export function addWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => {
    if (tab.paneKeys.includes(paneKey)) {
      if (tab.activePaneKey === paneKey) return tab;
      return { ...tab, activePaneKey: paneKey };
    }
    if (tab.paneKeys.length >= MAX_WORKBENCH_PANES) return tab;
    return {
      ...tab,
      paneKeys: [...tab.paneKeys, paneKey],
      activePaneKey: paneKey,
    };
  });
}

export function focusWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => (
    tab.paneKeys.includes(paneKey) && tab.activePaneKey !== paneKey
      ? { ...tab, activePaneKey: paneKey }
      : tab
  ));
}

export function detachWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => {
    const index = tab.paneKeys.indexOf(paneKey);
    if (index < 0 || paneKey === tabKey || tab.paneKeys.length === 1) return tab;
    const paneKeys = tab.paneKeys.filter((key) => key !== paneKey);
    const activePaneKey = tab.activePaneKey === paneKey
      ? paneKeys[Math.min(index, paneKeys.length - 1)]
      : tab.activePaneKey;
    return { ...tab, paneKeys, activePaneKey };
  });
}

export function attachWorkbenchPane(
  state: WorkbenchState,
  targetTabKey: string,
  paneKey: string,
  beforePaneKey?: string | null,
): WorkbenchState {
  if (!targetTabKey || !paneKey || targetTabKey === paneKey) return state;

  const sourceEntry = Object.entries(state.tabs).find(([, tab]) => (
    tab.paneKeys.includes(paneKey)
  ));
  const sourceTabKey = sourceEntry?.[0];
  const sourceTab = sourceEntry?.[1];
  if (sourceTabKey === targetTabKey) {
    if (beforePaneKey === undefined) {
      return focusWorkbenchPane(state, targetTabKey, paneKey);
    }
    if (!sourceTab) return state;
    const paneKeys = insertPaneBefore(sourceTab.paneKeys, paneKey, beforePaneKey);
    if (paneKeys.every((key, index) => key === sourceTab.paneKeys[index])) return state;
    return {
      version: 2,
      tabs: {
        ...state.tabs,
        [targetTabKey]: { ...sourceTab, paneKeys },
      },
    };
  }
  if (sourceTabKey === paneKey && sourceTab && sourceTab.paneKeys.length > 1) {
    return state;
  }
  const targetBeforeMove = state.tabs[targetTabKey] ?? defaultWorkbenchTab(targetTabKey);
  if (
    !targetBeforeMove.paneKeys.includes(paneKey)
    && targetBeforeMove.paneKeys.length >= MAX_WORKBENCH_PANES
  ) {
    return state;
  }

  const tabs = { ...state.tabs };
  if (sourceTabKey && sourceTab) {
    if (sourceTabKey === paneKey) {
      delete tabs[sourceTabKey];
    } else {
      const index = sourceTab.paneKeys.indexOf(paneKey);
      const paneKeys = sourceTab.paneKeys.filter((key) => key !== paneKey);
      tabs[sourceTabKey] = {
        ...sourceTab,
        paneKeys,
        activePaneKey: sourceTab.activePaneKey === paneKey
          ? paneKeys[Math.min(index, paneKeys.length - 1)]
          : sourceTab.activePaneKey,
      };
    }
  }

  const targetTab = tabs[targetTabKey] ?? defaultWorkbenchTab(targetTabKey);
  const paneKeys = insertPaneBefore(targetTab.paneKeys, paneKey, beforePaneKey);
  tabs[targetTabKey] = {
    ...targetTab,
    paneKeys,
    activePaneKey: paneKey,
  };
  return { version: 2, tabs };
}

export function promoteWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => {
    const index = tab.paneKeys.indexOf(paneKey);
    if (index <= 0) return tab;
    return {
      ...tab,
      paneKeys: [paneKey, ...tab.paneKeys.filter((key) => key !== paneKey)],
    };
  });
}

export function setWorkbenchLayout(
  state: WorkbenchState,
  tabKey: string,
  layout: WorkbenchLayout,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => (
    tab.layout === layout ? tab : { ...tab, layout }
  ));
}

export function reconcileWorkbench(
  state: WorkbenchState,
  validKeys: ReadonlySet<string>,
): WorkbenchState {
  const tabs: Record<string, WorkbenchTabState> = {};
  for (const [tabKey, tab] of Object.entries(state.tabs)) {
    if (!validKeys.has(tabKey)) continue;
    const paneKeys = tab.paneKeys.filter((key) => validKeys.has(key));
    const normalizedPaneKeys = (paneKeys.includes(tabKey)
      ? paneKeys
      : [tabKey, ...paneKeys]).slice(0, MAX_WORKBENCH_PANES);
    tabs[tabKey] = {
      ...tab,
      paneKeys: normalizedPaneKeys,
      activePaneKey: normalizedPaneKeys.includes(tab.activePaneKey)
        ? tab.activePaneKey
        : normalizedPaneKeys[0],
    };
  }
  const serializedCurrent = JSON.stringify(state.tabs);
  const serializedNext = JSON.stringify(tabs);
  return serializedCurrent === serializedNext ? state : { version: 2, tabs };
}

export function workbenchChildPaneKeys(state: WorkbenchState): Set<string> {
  const childKeys = new Set<string>();
  for (const [tabKey, tab] of Object.entries(state.tabs)) {
    for (const paneKey of tab.paneKeys) {
      if (paneKey !== tabKey) childKeys.add(paneKey);
    }
  }
  return childKeys;
}
