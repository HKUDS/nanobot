export interface ThreadReadingAnchor {
  sources: string[];
  fallback?: string;
  /** Display-unit top relative to the scrollport, excluding transient history UI. */
  relativeOffset: number;
  /** Used only when the stable display unit is no longer available. */
  scrollTop: number;
}

export interface ThreadReadingState {
  anchor: ThreadReadingAnchor | null;
  visibleMessageCount: number;
  followTail: boolean;
}

function copyState(state: ThreadReadingState): ThreadReadingState {
  return {
    ...state,
    anchor: state.anchor ? { ...state.anchor, sources: [...state.anchor.sources] } : null,
  };
}

/** Caller-owned scope (for example, one host/pane); keys are conversation keys. */
export class ThreadReadingStateStore {
  private readonly states = new Map<string, ThreadReadingState>();
  private readonly listeners = new Set<() => void>();

  constructor(entries: Iterable<readonly [string, ThreadReadingState]> = []) {
    for (const [key, state] of entries) this.set(key, state);
  }

  get(key: string): ThreadReadingState | undefined {
    const state = this.states.get(key);
    return state ? copyState(state) : undefined;
  }

  set(key: string, state: ThreadReadingState): void {
    this.states.delete(key);
    this.states.set(key, copyState(state));
    while (this.states.size > 128) this.states.delete(this.states.keys().next().value!);
    this.notify();
  }

  delete(key: string): void {
    if (this.states.delete(key)) this.notify();
  }

  clear(): void {
    if (!this.states.size) return;
    this.states.clear();
    this.notify();
  }

  entries(): [string, ThreadReadingState][] {
    return Array.from(this.states, ([key, state]) => [key, copyState(state)]);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
