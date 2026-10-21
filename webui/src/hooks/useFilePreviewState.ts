import { useCallback, useState, useSyncExternalStore } from "react";

export interface PreviewTab {
  id: string;
  kind: "file" | "web";
  value: string;
  canonicalPath?: string;
}

export interface FilePreviewState {
  tabs: PreviewTab[];
  activeId: string | null;
  width: number;
}

const EMPTY_PREVIEW: FilePreviewState = { tabs: [], activeId: null, width: 544 };

/** App-lifetime view state only. Never stores file contents or writes to browser storage. */
export class FilePreviewStore {
  private states = new Map<string, FilePreviewState>();
  private listeners = new Set<() => void>();

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  get(key: string | null): FilePreviewState {
    return key ? this.states.get(key) ?? EMPTY_PREVIEW : EMPTY_PREVIEW;
  }

  update(key: string, patch: Partial<FilePreviewState>) {
    const previous = this.get(key);
    const next = { ...previous, ...patch };
    if (previous.tabs === next.tabs && previous.width === next.width && previous.activeId === next.activeId) return;
    this.states.set(key, next);
    this.listeners.forEach((listener) => listener());
  }

  open(key: string, kind: PreviewTab["kind"], value: string) {
    const previous = this.get(key);
    const id = `${kind}:${value}`;
    const tabs = previous.tabs.some((tab) => tab.id === id)
      ? previous.tabs : [...previous.tabs, { id, kind, value }];
    this.update(key, { tabs, activeId: id });
  }

  /** Reconcile aliases only after the gateway has resolved and authorized the file. */
  resolveFile(key: string, path: string, canonicalPath: string) {
    const previous = this.get(key);
    const id = `file:${path}`;
    const current = previous.tabs.find(tab => tab.id === id);
    if (!current || current.canonicalPath === canonicalPath) return;
    const existing = previous.tabs.find(tab => tab.id !== id && tab.kind === "file"
      && tab.canonicalPath === canonicalPath);
    const tabs = existing
      ? previous.tabs.filter(tab => tab.id !== id)
      : previous.tabs.map(tab => tab.id === id ? { ...tab, canonicalPath } : tab);
    this.update(key, { tabs,
      activeId: existing && previous.activeId === id ? existing.id : previous.activeId });
  }

  select(key: string, id: string) {
    if (this.get(key).tabs.some((tab) => tab.id === id)) this.update(key, { activeId: id });
  }

  closeTab(key: string, id: string) {
    const previous = this.get(key);
    const index = previous.tabs.findIndex((tab) => tab.id === id);
    if (index < 0) return;
    const tabs = previous.tabs.filter((tab) => tab.id !== id);
    const activeId = previous.activeId === id
      ? (tabs[Math.min(index, tabs.length - 1)]?.id ?? null) : previous.activeId;
    this.update(key, { tabs, activeId });
  }

  close(key: string) {
    this.update(key, { tabs: [], activeId: null });
  }

  delete(key: string) {
    if (this.states.delete(key)) this.listeners.forEach((listener) => listener());
  }

  clear() {
    this.states.clear();
    this.listeners.forEach((listener) => listener());
  }
}

export function useFilePreviewState(key: string | null, sharedStore?: FilePreviewStore) {
  const [localStore] = useState(() => new FilePreviewStore());
  const store = sharedStore ?? localStore;
  const snapshot = useCallback(() => store.get(key), [key, store]);
  const state = useSyncExternalStore(store.subscribe, snapshot, snapshot);
  const openFile = useCallback((path: string) => {
    if (key) store.open(key, "file", path);
  }, [key, store]);
  const resolveFile = useCallback((path: string, canonicalPath: string) => {
    if (key) store.resolveFile(key, path, canonicalPath);
  }, [key, store]);
  const setWidth = useCallback((width: number) => {
    if (key) store.update(key, { width });
  }, [key, store]);
  const openWeb = useCallback((url: string) => {
    if (key) store.open(key, "web", url);
  }, [key, store]);
  const selectTab = useCallback((id: string) => {
    if (key) store.select(key, id);
  }, [key, store]);
  const closeTab = useCallback((id: string) => {
    if (key) store.closeTab(key, id);
  }, [key, store]);
  const close = useCallback(() => {
    if (key) store.close(key);
  }, [key, store]);
  return { state, openFile, resolveFile, openWeb, selectTab, closeTab, close, setWidth };
}
