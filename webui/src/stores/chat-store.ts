import { create } from "zustand";
import { readSessionUpdateChatIds, writeSessionUpdateChatIds } from "@/utils/chat";

export interface ChatStore {
  updatedChatIds: Set<string>;
  addUpdated: (chatId: string) => void;
  removeUpdated: (chatId: string) => void;
  clearUpdated: () => void;
  pruneUpdated: (knownChatIds: Set<string>) => void;
  hydrate: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  updatedChatIds: readSessionUpdateChatIds(),

  addUpdated: (chatId) =>
    set((s) => {
      if (s.updatedChatIds.has(chatId)) return s;
      const next = new Set(s.updatedChatIds);
      next.add(chatId);
      writeSessionUpdateChatIds(next);
      return { updatedChatIds: next };
    }),

  removeUpdated: (chatId) =>
    set((s) => {
      if (!s.updatedChatIds.has(chatId)) return s;
      const next = new Set(s.updatedChatIds);
      next.delete(chatId);
      writeSessionUpdateChatIds(next);
      return { updatedChatIds: next };
    }),

  clearUpdated: () => {
    writeSessionUpdateChatIds(new Set());
    set({ updatedChatIds: new Set() });
  },

  pruneUpdated: (knownChatIds) =>
    set((s) => {
      const next = new Set(
        Array.from(s.updatedChatIds).filter((id) => knownChatIds.has(id)),
      );
      if (next.size === s.updatedChatIds.size) return s;
      writeSessionUpdateChatIds(next);
      return { updatedChatIds: next };
    }),

  hydrate: () => set({ updatedChatIds: readSessionUpdateChatIds() }),
}));