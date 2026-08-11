import type {
  WorkbenchLayout,
  WorkbenchState,
  WorkbenchTabState,
} from "@/lib/types";

export type {
  WorkbenchLayout,
  WorkbenchState,
  WorkbenchTabState,
} from "@/lib/types";

export const MAX_WORKBENCH_PANES = 4;

export const WORKBENCH_LAYOUTS = [
  "columns",
  "rows",
  "grid",
  "bsp",
  "main-stack",
] as const;

export interface WorkbenchTabMatch {
  tabKey: string;
  tab: WorkbenchTabState;
}

export interface OrderedWorkbenchTab extends WorkbenchTabMatch {
  paneKeys: string[];
  updatedAt: string | null;
}

export const EMPTY_WORKBENCH_STATE: WorkbenchState = {
  version: 1,
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

function normalizeTitle(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const title = value.trim();
  return title || null;
}

function normalizeTab(value: unknown): WorkbenchTabState {
  const candidate = value && typeof value === "object"
    ? value as Partial<WorkbenchTabState>
    : {};
  const paneKeys = uniqueKeys(candidate.paneKeys).slice(0, MAX_WORKBENCH_PANES);
  const requestedLayoutPaneKeys = uniqueKeys(candidate.layoutPaneKeys)
    .filter((key) => paneKeys.includes(key));
  const layoutPaneKeys = [
    ...requestedLayoutPaneKeys,
    ...paneKeys.filter((key) => !requestedLayoutPaneKeys.includes(key)),
  ];
  return {
    explicit: candidate.explicit === true,
    title: normalizeTitle(candidate.title),
    paneKeys,
    layoutPaneKeys,
    activePaneKey:
      typeof candidate.activePaneKey === "string"
      && paneKeys.includes(candidate.activePaneKey)
        ? candidate.activePaneKey
        : paneKeys[0] ?? "",
    layout: isLayout(candidate.layout) ? candidate.layout : "columns",
  };
}

function standaloneTabKeyBase(paneKey: string): string {
  return `tab:${paneKey}`;
}

function availableStandaloneTabKey(
  tabs: Readonly<Record<string, WorkbenchTabState>>,
  paneKey: string,
): string {
  const base = standaloneTabKeyBase(paneKey);
  if (!tabs[base]) return base;
  let suffix = 2;
  while (tabs[`${base}:${suffix}`]) suffix += 1;
  return `${base}:${suffix}`;
}

function defaultWorkbenchTab(
  paneKey: string,
  title: string | null = null,
): WorkbenchTabState {
  return {
    explicit: false,
    title: normalizeTitle(title),
    paneKeys: [paneKey],
    layoutPaneKeys: [paneKey],
    activePaneKey: paneKey,
    layout: "columns",
  };
}

export function normalizeWorkbenchState(raw: unknown): WorkbenchState {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return EMPTY_WORKBENCH_STATE;
  }
  const parsed = raw as { version?: unknown; tabs?: unknown };
  if (parsed.version !== 1 || !parsed.tabs
    || typeof parsed.tabs !== "object" || Array.isArray(parsed.tabs)) {
    return EMPTY_WORKBENCH_STATE;
  }
  return {
    version: 1,
    tabs: Object.fromEntries(
      Object.entries(parsed.tabs).map(([tabKey, tab]) => [tabKey, normalizeTab(tab)]),
    ),
  };
}

export function workbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchTabState | null {
  return state.tabs[tabKey] ?? null;
}

export function workbenchTabForPane(
  state: WorkbenchState,
  paneKey: string,
): WorkbenchTabMatch {
  const match = Object.entries(state.tabs).find(([, tab]) => tab.paneKeys.includes(paneKey));
  if (match) return { tabKey: match[0], tab: match[1] };
  return {
    tabKey: availableStandaloneTabKey(state.tabs, paneKey),
    tab: defaultWorkbenchTab(paneKey),
  };
}

export function ensureWorkbenchPaneTab(
  state: WorkbenchState,
  paneKey: string,
  title: string | null = null,
): WorkbenchState {
  if (!paneKey || Object.values(state.tabs).some((tab) => tab.paneKeys.includes(paneKey))) {
    return state;
  }
  const tabKey = availableStandaloneTabKey(state.tabs, paneKey);
  return {
    version: 1,
    tabs: {
      ...state.tabs,
      [tabKey]: defaultWorkbenchTab(paneKey, title),
    },
  };
}

function updateTab(
  state: WorkbenchState,
  tabKey: string,
  update: (tab: WorkbenchTabState) => WorkbenchTabState,
): WorkbenchState {
  const current = state.tabs[tabKey];
  if (!current) return state;
  const next = update(current);
  if (next === current) return state;
  return {
    version: 1,
    tabs: {
      ...state.tabs,
      [tabKey]: next,
    },
  };
}

export function addWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  return attachWorkbenchPane(state, tabKey, paneKey);
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

export function createWorkbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => (
    tab.explicit ? tab : { ...tab, explicit: true }
  ));
}

export function detachWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  const tab = state.tabs[tabKey];
  if (!tab || !tab.paneKeys.includes(paneKey)) return state;
  if (tab.paneKeys.length === 1) {
    return tab.explicit
      ? updateTab(state, tabKey, (current) => ({
          ...current,
          explicit: false,
          title: null,
          layout: "columns",
        }))
      : state;
  }

  const index = tab.paneKeys.indexOf(paneKey);
  const paneKeys = tab.paneKeys.filter((key) => key !== paneKey);
  const layoutPaneKeys = tab.layoutPaneKeys.filter((key) => key !== paneKey);
  const nextTabKey = availableStandaloneTabKey(state.tabs, paneKey);
  return {
    version: 1,
    tabs: {
      ...state.tabs,
      [tabKey]: {
        ...tab,
        paneKeys,
        layoutPaneKeys,
        activePaneKey: tab.activePaneKey === paneKey
          ? paneKeys[Math.min(index, paneKeys.length - 1)]
          : tab.activePaneKey,
      },
      [nextTabKey]: defaultWorkbenchTab(paneKey),
    },
  };
}

export function dissolveWorkbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchState {
  const tab = state.tabs[tabKey];
  if (!tab) return state;
  if (tab.paneKeys.length === 1) {
    return tab.explicit
      ? updateTab(state, tabKey, (current) => ({
          ...current,
          explicit: false,
          title: null,
          layout: "columns",
        }))
      : state;
  }

  const tabs = { ...state.tabs };
  delete tabs[tabKey];
  for (const paneKey of tab.paneKeys) {
    const standaloneTabKey = availableStandaloneTabKey(tabs, paneKey);
    tabs[standaloneTabKey] = defaultWorkbenchTab(paneKey);
  }
  return { version: 1, tabs };
}

export function attachWorkbenchPane(
  state: WorkbenchState,
  targetTabKey: string,
  paneKey: string,
): WorkbenchState {
  if (!targetTabKey || !paneKey) return state;
  const target = state.tabs[targetTabKey];
  if (!target) return state;

  const sourceEntry = Object.entries(state.tabs).find(([, tab]) => (
    tab.paneKeys.includes(paneKey)
  ));
  const sourceTabKey = sourceEntry?.[0];
  const sourceTab = sourceEntry?.[1];
  if (sourceTabKey === targetTabKey) {
    return focusWorkbenchPane(state, targetTabKey, paneKey);
  }
  if (!target.paneKeys.includes(paneKey) && target.paneKeys.length >= MAX_WORKBENCH_PANES) {
    return state;
  }

  const tabs = { ...state.tabs };
  if (sourceTabKey && sourceTab) {
    const index = sourceTab.paneKeys.indexOf(paneKey);
    const sourcePaneKeys = sourceTab.paneKeys.filter((key) => key !== paneKey);
    const sourceLayoutPaneKeys = sourceTab.layoutPaneKeys.filter((key) => key !== paneKey);
    if (sourcePaneKeys.length === 0) {
      delete tabs[sourceTabKey];
    } else {
      tabs[sourceTabKey] = {
        ...sourceTab,
        paneKeys: sourcePaneKeys,
        layoutPaneKeys: sourceLayoutPaneKeys,
        activePaneKey: sourceTab.activePaneKey === paneKey
          ? sourcePaneKeys[Math.min(index, sourcePaneKeys.length - 1)]
          : sourceTab.activePaneKey,
      };
    }
  }

  const nextTarget = tabs[targetTabKey];
  if (!nextTarget) return state;
  const paneKeys = nextTarget.paneKeys.includes(paneKey)
    ? nextTarget.paneKeys
    : [...nextTarget.paneKeys, paneKey];
  const layoutPaneKeys = nextTarget.layoutPaneKeys.includes(paneKey)
    ? nextTarget.layoutPaneKeys
    : [...nextTarget.layoutPaneKeys, paneKey];
  tabs[targetTabKey] = {
    ...nextTarget,
    paneKeys,
    layoutPaneKeys,
    activePaneKey: paneKey,
  };
  return { version: 1, tabs };
}

export function renameWorkbenchTab(
  state: WorkbenchState,
  tabKey: string,
  title: string,
): WorkbenchState {
  const normalized = normalizeTitle(title);
  if (!normalized) return state;
  return updateTab(state, tabKey, (tab) => (
    tab.title === normalized ? tab : { ...tab, title: normalized }
  ));
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

export function setWorkbenchPaneLayoutOrder(
  state: WorkbenchState,
  tabKey: string,
  paneKeys: readonly string[],
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => {
    const requested = uniqueKeys(paneKeys).filter((key) => tab.paneKeys.includes(key));
    const layoutPaneKeys = [
      ...requested,
      ...tab.paneKeys.filter((key) => !requested.includes(key)),
    ];
    return layoutPaneKeys.every((key, index) => tab.layoutPaneKeys[index] === key)
      ? tab
      : { ...tab, layoutPaneKeys };
  });
}

export function reconcileWorkbench(
  state: WorkbenchState,
  validKeys: ReadonlySet<string>,
): WorkbenchState {
  const tabs: Record<string, WorkbenchTabState> = {};
  const claimedPaneKeys = new Set<string>();

  for (const [tabKey, tab] of Object.entries(state.tabs)) {
    const paneKeys = tab.paneKeys
      .filter((key) => validKeys.has(key) && !claimedPaneKeys.has(key))
      .slice(0, MAX_WORKBENCH_PANES);
    if (paneKeys.length === 0) continue;
    for (const paneKey of paneKeys) claimedPaneKeys.add(paneKey);
    tabs[tabKey] = {
      ...tab,
      paneKeys,
      layoutPaneKeys: [
        ...tab.layoutPaneKeys.filter((key) => paneKeys.includes(key)),
        ...paneKeys.filter((key) => !tab.layoutPaneKeys.includes(key)),
      ],
      activePaneKey: paneKeys.includes(tab.activePaneKey)
        ? tab.activePaneKey
        : paneKeys[0],
    };
  }

  for (const paneKey of validKeys) {
    if (claimedPaneKeys.has(paneKey)) continue;
    const tabKey = availableStandaloneTabKey(tabs, paneKey);
    tabs[tabKey] = defaultWorkbenchTab(paneKey);
  }

  return JSON.stringify(state.tabs) === JSON.stringify(tabs)
    ? state
    : { version: 1, tabs };
}

export function orderWorkbenchTabs(
  state: WorkbenchState,
  orderedSessionKeys: readonly string[],
  updatedAtByKey: ReadonlyMap<string, string | null | undefined>,
): OrderedWorkbenchTab[] {
  const rank = new Map(orderedSessionKeys.map((key, index) => [key, index]));
  const validKeys = new Set(orderedSessionKeys);
  const reconciled = reconcileWorkbench(state, validKeys);
  const tabs = Object.entries(reconciled.tabs).map(([tabKey, tab]) => {
    const paneKeys = tab.paneKeys
      .filter((key) => validKeys.has(key))
      .sort((left, right) => (rank.get(left) ?? Infinity) - (rank.get(right) ?? Infinity));
    const updatedAt = paneKeys.reduce<string | null>((latest, paneKey) => {
      const candidate = updatedAtByKey.get(paneKey) ?? null;
      return dateToTime(candidate) > dateToTime(latest) ? candidate : latest;
    }, null);
    return { tabKey, tab, paneKeys, updatedAt };
  });

  return tabs.sort((left, right) => {
    const updateOrder = dateToTime(right.updatedAt) - dateToTime(left.updatedAt);
    if (updateOrder !== 0) return updateOrder;
    const leftRank = Math.min(...left.paneKeys.map((key) => rank.get(key) ?? Infinity));
    const rightRank = Math.min(...right.paneKeys.map((key) => rank.get(key) ?? Infinity));
    return leftRank - rightRank;
  });
}

function dateToTime(value: string | null | undefined): number {
  const timestamp = Date.parse(value ?? "");
  return Number.isFinite(timestamp) ? timestamp : 0;
}
