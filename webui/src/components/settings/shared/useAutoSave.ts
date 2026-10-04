import { useEffect, useRef } from "react";

/** Save a valid draft once per edit; failures wait for another edit or explicit retry. */
export function useAutoSave(value: unknown, dirty: boolean, saving: boolean, onSave: () => void, enabled = true) {
  const latest = useRef(onSave);
  latest.current = onSave;
  const attempted = useRef<string | null>(null);
  const signature = JSON.stringify(value);
  useEffect(() => {
    if (!dirty) { attempted.current = null; return; }
    if (!enabled || saving || attempted.current === signature) return;
    const timer = window.setTimeout(() => {
      attempted.current = signature;
      latest.current();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [signature, dirty, saving, enabled]);
}
