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

function normalizeSplitRatios(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((ratio): ratio is number => typeof ratio === "number" && Number.isFinite(ratio))
    .slice(0, MAX_WORKBENCH_PANES - 1)
    .map((ratio) => Number(Math.min(0.95, Math.max(0.05, ratio)).toFixed(4)));
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
    layout: isLayout(candidate.layout) ? candidate.layout : "columns",
    splitRatios: normalizeSplitRatios(candidate.splitRatios),
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
    layout: "columns",
    splitRatios: [],
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
      Object.entries(parsed.tabs)
        .map(([tabKey, tab]) => [tabKey, normalizeTab(tab)] as const)
        .filter(([, tab]) => tab.paneKeys.length > 1 || tab.explicit),
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
  anchorPaneKey: string,
  paneKey: string,
): WorkbenchState {
  if (!anchorPaneKey || !paneKey || anchorPaneKey === paneKey) return state;
  const target = workbenchTabForPane(state, anchorPaneKey);
  if (state.tabs[target.tabKey]) return attachWorkbenchPane(state, target.tabKey, paneKey);
  const withTarget = {
    version: 1 as const,
    tabs: {
      ...state.tabs,
      [target.tabKey]: target.tab,
    },
  };
  return attachWorkbenchPane(withTarget, target.tabKey, paneKey);
}

export function createWorkbenchTab(
  state: WorkbenchState,
  paneKey: string,
): WorkbenchState {
  if (!paneKey) return state;
  const match = workbenchTabForPane(state, paneKey);
  const persisted = state.tabs[match.tabKey];
  if (persisted) {
    return updateTab(state, match.tabKey, (tab) => (
      tab.explicit ? tab : { ...tab, explicit: true }
    ));
  }
  return {
    version: 1,
    tabs: {
      ...state.tabs,
      [match.tabKey]: { ...match.tab, explicit: true },
    },
  };
}

export function detachWorkbenchPane(
  state: WorkbenchState,
  tabKey: string,
  paneKey: string,
): WorkbenchState {
  const tab = state.tabs[tabKey];
  if (!tab || !tab.paneKeys.includes(paneKey)) return state;
  if (tab.paneKeys.length === 1) {
    const tabs = { ...state.tabs };
    delete tabs[tabKey];
    return { version: 1, tabs };
  }

  const paneKeys = tab.paneKeys.filter((key) => key !== paneKey);
  const layoutPaneKeys = tab.layoutPaneKeys.filter((key) => key !== paneKey);
  const tabs = { ...state.tabs };
  const nextTab = {
    ...tab,
    paneKeys,
    layoutPaneKeys,
    splitRatios: [],
  };
  if (nextTab.explicit || paneKeys.length > 1) tabs[tabKey] = nextTab;
  else delete tabs[tabKey];
  return {
    version: 1,
    tabs,
  };
}

export function dissolveWorkbenchTab(
  state: WorkbenchState,
  tabKey: string,
): WorkbenchState {
  const tab = state.tabs[tabKey];
  if (!tab) return state;
  const tabs = { ...state.tabs };
  delete tabs[tabKey];
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
    return state;
  }
  if (!target.paneKeys.includes(paneKey) && target.paneKeys.length >= MAX_WORKBENCH_PANES) {
    return state;
  }

  const tabs = { ...state.tabs };
  if (sourceTabKey && sourceTab) {
    const sourcePaneKeys = sourceTab.paneKeys.filter((key) => key !== paneKey);
    const sourceLayoutPaneKeys = sourceTab.layoutPaneKeys.filter((key) => key !== paneKey);
    if (sourcePaneKeys.length === 0 || (!sourceTab.explicit && sourcePaneKeys.length === 1)) {
      delete tabs[sourceTabKey];
    } else {
      tabs[sourceTabKey] = {
        ...sourceTab,
        paneKeys: sourcePaneKeys,
        layoutPaneKeys: sourceLayoutPaneKeys,
        splitRatios: [],
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
    splitRatios: [],
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
    tab.layout === layout ? tab : { ...tab, layout, splitRatios: [] }
  ));
}

export function setWorkbenchSplitRatios(
  state: WorkbenchState,
  tabKey: string,
  splitRatios: readonly number[],
): WorkbenchState {
  return updateTab(state, tabKey, (tab) => {
    const normalized = normalizeSplitRatios(splitRatios);
    return normalized.length === tab.splitRatios.length
      && normalized.every((ratio, index) => ratio === tab.splitRatios[index])
      ? tab
      : { ...tab, splitRatios: normalized };
  });
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
    const nextTab = {
      ...tab,
      paneKeys,
      layoutPaneKeys: [
        ...tab.layoutPaneKeys.filter((key) => paneKeys.includes(key)),
        ...paneKeys.filter((key) => !tab.layoutPaneKeys.includes(key)),
      ],
      splitRatios: paneKeys.length === tab.paneKeys.length
        && paneKeys.every((key, index) => key === tab.paneKeys[index])
        ? tab.splitRatios
        : [],
    };
    if (!nextTab.explicit && paneKeys.length === 1) continue;
    for (const paneKey of paneKeys) claimedPaneKeys.add(paneKey);
    tabs[tabKey] = nextTab;
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
  const projectedTabs = { ...reconciled.tabs };
  const claimedPaneKeys = new Set(
    Object.values(projectedTabs).flatMap((tab) => tab.paneKeys),
  );
  for (const paneKey of orderedSessionKeys) {
    if (claimedPaneKeys.has(paneKey)) continue;
    const tabKey = availableStandaloneTabKey(projectedTabs, paneKey);
    projectedTabs[tabKey] = defaultWorkbenchTab(paneKey);
  }
  const tabs = Object.entries(projectedTabs).map(([tabKey, tab]) => {
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
