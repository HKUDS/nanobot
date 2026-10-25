import { createContext, useContext, useMemo, type ReactNode } from "react";

export const MarkdownCodeContext = createContext({ streaming: false, highlight: true });
const ScopeContext = createContext<object | null>(null);

// Context invalidates resource effects even through memoized Markdown fences.
export function DiagramScope({ identity, children }: { identity: string | null; children: ReactNode }) {
  const scope = useMemo(() => ({ identity }), [identity]);
  return <ScopeContext.Provider value={scope}>{children}</ScopeContext.Provider>;
}

export function useDiagramScope() {
  return useContext(ScopeContext);
}
