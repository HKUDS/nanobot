import { afterEach, describe, expect, it, vi } from "vitest";

import { ComposerDraftStore, clearStoredComposerDrafts, type ComposerDraft } from "@/lib/composer-draft";

const key = "websocket:draft-storage-test";
const storageKey = `nanobot.composer-draft.v1.${key}`;
const draft: ComposerDraft = {
  text: "  Keep this draft\n继续编辑",
  quotedContext: "Quoted answer",
  sessionMentions: [{ name: "other", title: "Other topic", session_key: "websocket:other" }],
  files: [new File(["attachment"], "draft.txt", { type: "text/plain" })],
};

afterEach(() => {
  vi.restoreAllMocks();
  clearStoredComposerDrafts();
});

describe("composer draft storage", () => {
  it("restores text, mentions and quotes in a fresh store while keeping files in memory", () => {
    const store = new ComposerDraftStore();
    store.set(key, draft, true);
    expect(store.get(key)).toBe(draft);
    expect(new ComposerDraftStore().get(key, true)).toEqual({ ...draft, files: [] });
    expect(new ComposerDraftStore().get("websocket:other", true)).toBeUndefined();
    expect(localStorage.getItem(storageKey)).not.toContain("files");
  });

  it("requires explicit opt-in for both saving and restoring", () => {
    const store = new ComposerDraftStore();
    store.set(key, draft);
    expect(store.get(key)).toBe(draft);
    expect(localStorage.getItem(storageKey)).toBeNull();
    store.set(key, draft, true);
    expect(new ComposerDraftStore().get(key, false)).toBeUndefined();
  });

  it("removes saved text when discarded, even if attachments remain", () => {
    const store = new ComposerDraftStore();
    store.set(key, draft, true);
    store.set(key, { ...draft, text: "", quotedContext: null, sessionMentions: [] }, true);
    expect(store.get(key)?.files).toEqual(draft.files);
    expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
  });

  it("deletes saved drafts without first loading them and clears only drafts on logout", () => {
    const store = new ComposerDraftStore();
    store.set(key, draft, true);
    new ComposerDraftStore().delete(key);
    expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
    store.set(key, draft, true);
    store.set("new:chat", draft, true);
    localStorage.setItem("nanobot.test.other", "keep");
    clearStoredComposerDrafts();
    expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
    expect(new ComposerDraftStore().get("new:chat", true)).toBeUndefined();
    expect(localStorage.getItem("nanobot.test.other")).toBe("keep");
    localStorage.removeItem("nanobot.test.other");
  });

  it.each(["{", "null", '{"text":42}', '{"text":"draft","quotedContext":{},"sessionMentions":[]}'])(
    "ignores malformed saved drafts: %s", (raw) => {
      localStorage.setItem(storageKey, raw);
      expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
    },
  );

  it("drops malformed mention records without losing the draft text", () => {
    localStorage.setItem(storageKey, JSON.stringify({
      ...draft, sessionMentions: [null, { name: 42 }, ...draft.sessionMentions],
    }));
    expect(new ComposerDraftStore().get(key, true)).toEqual({ ...draft, files: [] });
  });

  it("keeps editing usable when storage is unavailable and removes stale saved text", () => {
    const store = new ComposerDraftStore();
    store.set(key, draft, true);
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new Error("quota"); });
    const updated = { ...draft, text: "latest draft" };
    store.set(key, updated, true);
    expect(store.get(key)).toBe(updated);
    expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
    vi.spyOn(localStorage, "getItem").mockImplementation(() => { throw new Error("disabled"); });
    expect(new ComposerDraftStore().get(key, true)).toBeUndefined();
  });
});
