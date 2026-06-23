import { beforeEach, describe, expect, it } from "vitest";

import { SESSION_UPDATES_STORAGE_KEY } from "@/constants";
import { useChatStore } from "@/stores/chat-store";

describe("useChatStore", () => {
  beforeEach(() => {
    window.localStorage.removeItem(SESSION_UPDATES_STORAGE_KEY);
    useChatStore.setState({ updatedChatIds: new Set() });
  });

  it("starts empty when localStorage has no entries", () => {
    expect(useChatStore.getState().updatedChatIds).toEqual(new Set());
  });

  it("hydrates from localStorage on demand", () => {
    window.localStorage.setItem(
      SESSION_UPDATES_STORAGE_KEY,
      JSON.stringify(["chat-a", "chat-b"]),
    );
    useChatStore.getState().hydrate();
    expect(useChatStore.getState().updatedChatIds).toEqual(
      new Set(["chat-a", "chat-b"]),
    );
  });

  it("addUpdated adds a chat id and persists it", () => {
    useChatStore.getState().addUpdated("chat-a");
    expect(useChatStore.getState().updatedChatIds).toEqual(new Set(["chat-a"]));
    const raw = window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY);
    expect(JSON.parse(raw ?? "[]")).toEqual(["chat-a"]);
  });

  it("addUpdated is idempotent", () => {
    useChatStore.getState().addUpdated("chat-a");
    useChatStore.getState().addUpdated("chat-a");
    expect(useChatStore.getState().updatedChatIds).toEqual(new Set(["chat-a"]));
  });

  it("removeUpdated removes a chat id and persists it", () => {
    useChatStore.getState().addUpdated("chat-a");
    useChatStore.getState().addUpdated("chat-b");
    useChatStore.getState().removeUpdated("chat-a");
    expect(useChatStore.getState().updatedChatIds).toEqual(new Set(["chat-b"]));
    const raw = window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY);
    expect(JSON.parse(raw ?? "[]")).toEqual(["chat-b"]);
  });

  it("clearUpdated empties the set and the persisted value", () => {
    useChatStore.getState().addUpdated("chat-a");
    useChatStore.getState().clearUpdated();
    expect(useChatStore.getState().updatedChatIds).toEqual(new Set());
    expect(window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY)).toEqual("[]");
  });

  it("pruneUpdated keeps only ids that are still known", () => {
    useChatStore.getState().addUpdated("chat-a");
    useChatStore.getState().addUpdated("chat-b");
    useChatStore.getState().addUpdated("chat-c");
    useChatStore.getState().pruneUpdated(new Set(["chat-a", "chat-c"]));
    expect(useChatStore.getState().updatedChatIds).toEqual(
      new Set(["chat-a", "chat-c"]),
    );
    const raw = window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY);
    expect(JSON.parse(raw ?? "[]").sort()).toEqual(["chat-a", "chat-c"]);
  });

  it("pruneUpdated is a no-op when nothing changes", () => {
    useChatStore.getState().addUpdated("chat-a");
    const before = useChatStore.getState().updatedChatIds;
    useChatStore.getState().pruneUpdated(new Set(["chat-a", "chat-b"]));
    expect(useChatStore.getState().updatedChatIds).toBe(before);
  });
});