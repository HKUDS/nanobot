import { useEffect, useRef, type FocusEvent, type FormEvent } from "react";

function isDraftInput(target: EventTarget) {
  return target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLInputElement && !["checkbox", "radio", "button", "submit"].includes(target.type));
}

type Draft = {
  signature: string;
  identity: string;
  revision: number;
  dirty: boolean;
  enabled: boolean;
  onSave: () => void | Promise<unknown>;
};

/** Completion belongs to the draft owner; queued saves retain that version and target. */
export function useEditCompletion(value: unknown, dirty: boolean, onSave: Draft["onSave"], enabled = true, identity = "") {
  const signature = JSON.stringify(value);
  const version = useRef({ signature, identity, revision: 0 });
  if (version.current.signature !== signature || version.current.identity !== identity) {
    version.current = { signature, identity, revision: version.current.revision + 1 };
  }
  const revision = version.current.revision;
  const latest = useRef<Draft>({ signature, dirty, enabled, onSave, identity, revision });
  latest.current = { signature, dirty, enabled, onSave, identity, revision };
  const focused = useRef(false);
  const completed = useRef(false);
  const previousIdentity = useRef(identity);
  const attempts = useRef(new Map<string, Promise<boolean>>());
  const tail = useRef(Promise.resolve(true));
  const outstanding = useRef(0);
  const queuedDraft = useRef<Draft | null>(null);
  const commitDraft = (draft: Draft): Promise<boolean> => {
    const queued = queuedDraft.current;
    const changedDuringSave = outstanding.current > 0 && queued &&
      queued.identity === draft.identity && queued.signature !== draft.signature;
    if (!draft.dirty && !changedDuringSave) return outstanding.current > 0 ? tail.current : Promise.resolve(true);
    if (!draft.enabled) return Promise.resolve(false);
    const version = `${draft.identity}:${draft.revision}`;
    const existing = attempts.current.get(version);
    if (existing) return existing;
    const request = tail.current.then(async () => {
      try {
        return (await draft.onSave()) !== false;
      } catch {
        return false;
      }
    });
    outstanding.current += 1;
    queuedDraft.current = draft;
    attempts.current.set(version, request);
    tail.current = request;
    void request.then((saved) => {
      outstanding.current -= 1;
      if (!saved || latest.current.revision !== draft.revision) attempts.current.delete(version);
    });
    return request;
  };
  const commit = async (): Promise<boolean> => {
    focused.current = false;
    const draft = latest.current;
    const saved = await commitDraft(draft);
    if (!saved) return false;
    const current = latest.current;
    if (current.identity === draft.identity && current.signature !== draft.signature) return commit();
    return true;
  };
  const commitRef = useRef(commit);
  commitRef.current = commit;
  const commitDraftRef = useRef(commitDraft);
  commitDraftRef.current = commitDraft;
  useEffect(() => {
    if (!dirty && outstanding.current === 0) attempts.current.clear();
    if (previousIdentity.current !== identity) {
      previousIdentity.current = identity;
      focused.current = false;
      return;
    }
    if ((!focused.current || completed.current) && (dirty || outstanding.current > 0)) void commitDraftRef.current(latest.current);
    completed.current = false;
  }, [signature, dirty, enabled, identity]);
  useEffect(() => () => { void commitRef.current(); }, []);
  return {
    identity,
    commit,
    complete: () => { completed.current = true; },
    onChangeCapture: (event: FormEvent<HTMLElement>) => {
      if (isDraftInput(event.target)) {
        focused.current = true;
        completed.current = false;
      } else completed.current = true;
    },
    needsCompletion: () => latest.current.dirty || outstanding.current > 0,
    onFocusCapture: (event: FocusEvent<HTMLElement>) => {
      if (isDraftInput(event.target)) focused.current = true;
    },
    onBlurCapture: (event: FocusEvent<HTMLElement>) => {
      if (!isDraftInput(event.target)) return;
      focused.current = false;
      void commitDraft(latest.current);
    },
  };
}

export type EditCompletion = ReturnType<typeof useEditCompletion>;
