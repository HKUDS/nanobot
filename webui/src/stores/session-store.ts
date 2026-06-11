import { create } from "zustand";
import { type SettingsPayload, type WorkspaceScopePayload, type WorkspacesPayload } from "../lib/types";
import { normalizeWorkspaceScope, readCompletedRunChatIds, writeCompletedRunChatIds } from "../utils/helpers";

/* ── State ────────────────────────────────────────── */

export interface SessionStore {
  /* runtime tracking */
  runningChatIds: Set<string>;
  completedChatIds: Set<string>;

  /* workspace */
  workspaces: WorkspacesPayload | null;
  workspaceError: string | null;
  draftWorkspaceScope: WorkspaceScopePayload | null;
  workspaceOverrides: Record<string, WorkspaceScopePayload>;

  /* settings */
  settingsSnapshot: SettingsPayload | null;

  /* actions */
  addRunning: (chatId: string) => void;
  removeRunning: (chatId: string) => void;
  addCompleted: (chatId: string) => void;
  removeCompleted: (chatId: string) => void;
  pruneCompleted: (knownChatIds: Set<string>) => void;
  setRunningFromSessions: (activeChatIds: string[]) => void;

  setWorkspaces: (payload: WorkspacesPayload | null) => void;
  setWorkspaceError: (msg: string | null) => void;
  setDraftWorkspaceScope: (scope: WorkspaceScopePayload | null) => void;
  setWorkspaceOverride: (chatId: string, scope: WorkspaceScopePayload) => void;
  pruneWorkspaceOverrides: (knownChatIds: Set<string>) => void;
  clearWorkspaceOverrides: () => void;

  setSettingsSnapshot: (payload: SettingsPayload | null) => void;
}

function replaceSet(prev: Set<string>, next: Set<string>): Set<string> {
  if (prev.size === next.size && Array.from(prev).every((v) => next.has(v))) return prev;
  return next;
}

/* ── Store ────────────────────────────────────────── */

export const useSessionStore = create<SessionStore>((set) => ({
  runningChatIds: new Set(),
  completedChatIds: readCompletedRunChatIds(),

  workspaces: null,
  workspaceError: null,
  draftWorkspaceScope: null,
  workspaceOverrides: {},

  settingsSnapshot: null,

  /* ── running / completed ── */

  addRunning: (chatId) =>
    set((s) => {
      if (s.runningChatIds.has(chatId)) return s;
      const next = new Set(s.runningChatIds);
      next.add(chatId);
      return { runningChatIds: next };
    }),

  removeRunning: (chatId) =>
    set((s) => {
      if (!s.runningChatIds.has(chatId)) return s;
      const next = new Set(s.runningChatIds);
      next.delete(chatId);
      return { runningChatIds: next };
    }),

  addCompleted: (chatId) =>
    set((s) => {
      if (s.completedChatIds.has(chatId)) return s;
      const next = new Set(s.completedChatIds);
      next.add(chatId);
      writeCompletedRunChatIds(next);
      return { completedChatIds: next };
    }),

  removeCompleted: (chatId) =>
    set((s) => {
      if (!s.completedChatIds.has(chatId)) return s;
      const next = new Set(s.completedChatIds);
      next.delete(chatId);
      writeCompletedRunChatIds(next);
      return { completedChatIds: next };
    }),

  pruneCompleted: (knownChatIds) =>
    set((s) => {
      const next = new Set(Array.from(s.completedChatIds).filter((id) => knownChatIds.has(id)));
      if (next.size === s.completedChatIds.size) return s;
      writeCompletedRunChatIds(next);
      return { completedChatIds: next };
    }),

  setRunningFromSessions: (activeChatIds) =>
    set((s) => {
      const next = new Set(activeChatIds);
      for (const id of s.runningChatIds) next.add(id);
      return { runningChatIds: replaceSet(s.runningChatIds, next) };
    }),

  /* ── workspace ── */

  setWorkspaces: (payload) => set({ workspaces: payload }),
  setWorkspaceError: (msg) => set({ workspaceError: msg }),

  setDraftWorkspaceScope: (scope) =>
    set({
      draftWorkspaceScope: scope ? normalizeWorkspaceScope(scope) : null,
    }),

  setWorkspaceOverride: (chatId, scope) =>
    set((s) => {
      const next = normalizeWorkspaceScope(scope);
      if (s.workspaceOverrides[chatId] === next) return s;
      return {
        workspaceOverrides: { ...s.workspaceOverrides, [chatId]: next },
      };
    }),

  pruneWorkspaceOverrides: (knownChatIds) =>
    set((s) => {
      const entries = Object.entries(s.workspaceOverrides).filter(([id]) => knownChatIds.has(id));
      if (entries.length === Object.keys(s.workspaceOverrides).length) return s;
      return { workspaceOverrides: Object.fromEntries(entries) };
    }),

  clearWorkspaceOverrides: () => set({ workspaceOverrides: {} }),

  /* ── settings ── */

  setSettingsSnapshot: (payload) => set({ settingsSnapshot: payload }),
}));