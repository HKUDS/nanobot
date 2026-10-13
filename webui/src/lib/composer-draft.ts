import type { SessionMention } from "./types";

/** Files stay in memory, including unfinished attachments. */
export interface ComposerDraft {
  text: string;
  files: File[];
  sessionMentions: SessionMention[];
  quotedContext: string | null;
}

const STORAGE_PREFIX = "nanobot.composer-draft.v1.";
const MAX_STORED_CHARS = 512 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readDraft(raw: string): ComposerDraft | undefined {
  if (raw.length > MAX_STORED_CHARS) return undefined;
  const value: unknown = JSON.parse(raw);
  if (!isRecord(value) || typeof value.text !== "string"
    || (value.quotedContext !== null && typeof value.quotedContext !== "string")
    || !Array.isArray(value.sessionMentions)) return undefined;
  const sessionMentions = value.sessionMentions.flatMap((item: unknown): SessionMention[] => {
    if (!isRecord(item) || typeof item.name !== "string"
      || !/^[\p{L}\p{N}_-]{1,80}$/u.test(item.name)
      || typeof item.session_key !== "string" || !item.session_key.startsWith("websocket:")
      || item.session_key.length > 512 || typeof item.title !== "string") return [];
    return [{
      name: item.name,
      session_key: item.session_key,
      title: item.title.slice(0, 160),
      ...(typeof item.id === "string" && /^handle_[a-f0-9]{32}$/i.test(item.id)
        ? { id: item.id } : {}),
    }];
  }).slice(0, 8);
  return { text: value.text, quotedContext: value.quotedContext, sessionMentions, files: [] };
}

function removeStoredDraft(key: string): void {
  try { localStorage.removeItem(STORAGE_PREFIX + key); } catch { /* Storage is optional. */ }
}

export function clearStoredComposerDrafts(): void {
  try {
    for (let index = localStorage.length - 1; index >= 0; index -= 1) {
      const key = localStorage.key(index);
      if (key?.startsWith(STORAGE_PREFIX)) localStorage.removeItem(key);
    }
  } catch { /* Storage is optional. */ }
}

export class ComposerDraftStore extends Map<string, ComposerDraft> {
  override get(key: string, persist = false): ComposerDraft | undefined {
    const cached = super.get(key);
    if (cached || !persist) return cached;
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + key);
      const draft = raw ? readDraft(raw) : undefined;
      if (draft) super.set(key, draft);
      return draft;
    } catch {
      return undefined;
    }
  }

  override set(key: string, draft: ComposerDraft, persist = false): this {
    const previous = super.get(key);
    const unchanged = previous
      && previous.text === draft.text
      && previous.quotedContext === draft.quotedContext
      && previous.files.length === draft.files.length
      && previous.files.every((file, index) => file === draft.files[index])
      && previous.sessionMentions.length === draft.sessionMentions.length
      && previous.sessionMentions.every((mention, index) => mention === draft.sessionMentions[index]);
    // Restoring a composer is not an edit. Pending sends retain this identity across mounts.
    super.set(key, unchanged ? previous : draft);
    if (!persist) return this;
    if (!draft.text && !draft.quotedContext) {
      removeStoredDraft(key);
      return this;
    }
    try {
      const raw = JSON.stringify({
        text: draft.text,
        quotedContext: draft.quotedContext,
        sessionMentions: draft.sessionMentions,
      });
      if (raw.length <= MAX_STORED_CHARS) localStorage.setItem(STORAGE_PREFIX + key, raw);
      else removeStoredDraft(key);
    } catch {
      // Keep the in-memory draft, but do not restore an older saved version after refresh.
      removeStoredDraft(key);
    }
    return this;
  }

  override delete(key: string): boolean {
    removeStoredDraft(key);
    return super.delete(key);
  }
}
