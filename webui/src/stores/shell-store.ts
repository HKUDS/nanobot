import { create } from "zustand";
import { type ShellRoute, type ShellView, readShellRoute, writeShellRoute } from "@/utils/shell";
import { readSidebarOpen } from "@/utils/helpers";
import { SIDEBAR_STORAGE_KEY } from "@/constants";
import type { SessionAutomationJob } from "@/lib/types";

/* ── Types ───────────────────────────────────────── */

export interface PendingAction {
  key: string;
  label: string;
  automations?: SessionAutomationJob[];
}

export interface ShellStore {
  /* routing */
  activeKey: string | null;
  view: ShellView;
  settingsSection: string;

  /* sidebar */
  hostSidebarOpen: boolean;
  hostSidebarPreviewing: boolean;
  mobileSidebarOpen: boolean;

  /* dialogs */
  sessionSearchOpen: boolean;
  pendingDelete: PendingAction | null;
  pendingRename: PendingAction | null;
  pendingProjectRename: PendingAction | null;

  /* transient */
  restartToast: string | null;
  isRestarting: boolean;

  /* actions */
  navigate: (route: ShellRoute, options?: { replace?: boolean }) => void;
  applyRoute: () => void;
  toggleSidebar: () => void;
  toggleHostSidebar: () => void;
  openHostSidebar: () => void;
  closeHostSidebar: () => void;
  openHostSidebarPreview: () => void;
  scheduleHostSidebarPreviewClose: () => void;
  openMobileSidebar: () => void;
  closeMobileSidebar: () => void;
  openSessionSearch: () => void;
  closeSessionSearch: () => void;
  openDeleteDialog: (key: string, label: string, automations?: SessionAutomationJob[]) => void;
  closeDeleteDialog: () => void;
  openRenameDialog: (key: string, label: string) => void;
  closeRenameDialog: () => void;
  openProjectRenameDialog: (key: string, label: string) => void;
  closeProjectRenameDialog: () => void;
  showRestartToast: (message: string) => void;
  clearRestartToast: () => void;
  setIsRestarting: (v: boolean) => void;
}

/* ── Store ───────────────────────────────────────── */

export const useShellStore = create<ShellStore>((set) => {
  const initial = readShellRoute();

  return {
    /* routing */
    activeKey: initial.activeKey,
    view: initial.view,
    settingsSection: initial.settingsSection,

    /* sidebar */
    hostSidebarOpen: readSidebarOpen(),
    hostSidebarPreviewing: false,
    mobileSidebarOpen: false,

    /* dialogs */
    sessionSearchOpen: false,
    pendingDelete: null,
    pendingRename: null,
    pendingProjectRename: null,

    /* transient */
    restartToast: null,
    isRestarting: false,

    /* ── actions ── */

    navigate: (route, options) => {
      set({
        activeKey: route.activeKey,
        view: route.view,
        settingsSection: route.settingsSection,
      });
      writeShellRoute(route, options?.replace);
    },

    applyRoute: () => {
      const route = readShellRoute();
      set({
        activeKey: route.activeKey,
        view: route.view,
        settingsSection: route.settingsSection,
      });
    },

    toggleSidebar: () => {
      const isNativeHost =
        typeof window !== "undefined" &&
        window.matchMedia("(min-width: 1024px)").matches;
      if (isNativeHost) {
        set((s) => {
          const next = !s.hostSidebarOpen;
          try {
            window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
          } catch { /* ignore */ }
          return { hostSidebarOpen: next, hostSidebarPreviewing: false };
        });
      } else {
        set((s) => ({ mobileSidebarOpen: !s.mobileSidebarOpen }));
      }
    },

    toggleHostSidebar: () => {
      set((s) => {
        const next = !s.hostSidebarOpen;
        try {
          window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
        } catch { /* ignore */ }
        return { hostSidebarOpen: next, hostSidebarPreviewing: false };
      });
    },

    openHostSidebar: () => set({ hostSidebarOpen: true, hostSidebarPreviewing: false }),
    closeHostSidebar: () => set({ hostSidebarOpen: false, hostSidebarPreviewing: false }),

    openHostSidebarPreview: () => set({ hostSidebarPreviewing: true }),

    scheduleHostSidebarPreviewClose: () => {
      setTimeout(() => {
        set((s) => (s.hostSidebarPreviewing ? { hostSidebarPreviewing: false } : s));
      }, 120);
    },

    openMobileSidebar: () => set({ mobileSidebarOpen: true }),
    closeMobileSidebar: () => set({ mobileSidebarOpen: false }),

    openSessionSearch: () => {
      set({ mobileSidebarOpen: false, sessionSearchOpen: true });
    },
    closeSessionSearch: () => set({ sessionSearchOpen: false }),

    openDeleteDialog: (key, label, automations) =>
      set({ pendingDelete: { key, label, automations } }),
    closeDeleteDialog: () => set({ pendingDelete: null }),

    openRenameDialog: (key, label) => set({ pendingRename: { key, label } }),
    closeRenameDialog: () => set({ pendingRename: null }),

    openProjectRenameDialog: (key, label) => set({ pendingProjectRename: { key, label } }),
    closeProjectRenameDialog: () => set({ pendingProjectRename: null }),

    showRestartToast: (message) => set({ restartToast: message }),
    clearRestartToast: () => set({ restartToast: null }),

    setIsRestarting: (v) => set({ isRestarting: v }),
  };
});