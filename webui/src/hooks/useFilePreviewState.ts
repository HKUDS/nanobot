import { useCallback, useState, useSyncExternalStore } from "react";

interface FilePreviewState {
  path: string | null;
  width: number;
}

const EMPTY_PREVIEW: FilePreviewState = { path: null, width: 544 };

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
    if (previous.path === next.path && previous.width === next.width) return;
    this.states.set(key, next);
    this.listeners.forEach((listener) => listener());
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
  const setPath = useCallback((path: string | null) => {
    if (key) store.update(key, { path });
  }, [key, store]);
  const setWidth = useCallback((width: number) => {
    if (key) store.update(key, { width });
  }, [key, store]);
  return { state, setPath, setWidth };
}
