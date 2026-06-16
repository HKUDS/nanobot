import { useSessionStore } from "@/stores/session-store";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RESTART_STARTED_KEY, SIDEBAR_RAIL_WIDTH, SIDEBAR_WIDTH } from "../constants";
import { useDeferredTitleRefresh } from "../hooks/useDeferredTitleRefresh";
import { useSessions } from "../hooks/useSessions";
import { useSkills } from "../hooks/useSkills";
import { useSidebarState } from "../hooks/useSidebarState";
import { ThemeProvider, useTheme } from "../hooks/useTheme";
import { fetchSettings, fetchWorkspaces } from "../lib/api";
import { deriveTitle } from "../lib/format";
import { ChatSummary, RuntimeSurface, WorkspaceScopePayload } from "../lib/types";
import { cn } from "../lib/utils";
import { projectNameFromPath } from "../lib/workspace";
import { useClient } from "../providers/ClientProvider";
import { useShellStore } from "../stores/shell-store";
import { normalizeWorkspaceScope, writeCompletedRunChatIds } from "../utils/helpers";
import { defaultShellRoute, readShellRoute, ShellView, shellViewForSettingsSection } from "../utils/shell";
import { DeleteConfirm } from "./DeleteConfirm";
import { RenameChatDialog } from "./RenameChatDialog";
import { SessionSearchDialog } from "./SessionSearchDialog";
import { SettingsSectionKey, SettingsView } from "./settings/SettingsView";
import { Sidebar } from "./Sidebar";
import HostChrome from "./ThemeSwitch";
import { ThreadShell } from "./thread/ThreadShell";
import { Sheet, SheetContent, SheetTitle } from "./ui/sheet";

export default function Shell({
  runtimeSurface,
  onModelNameChange,
  onLogout,
  onNativeEngineRestart,
}: {
  runtimeSurface: RuntimeSurface;
  onModelNameChange: (modelName: string | null) => void;
    onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const { t, i18n } = useTranslation();
  const { client, token } = useClient();
  const { theme, toggle } = useTheme();
  const { sessions, loading, refresh, createChat, deleteChat } = useSessions();
  const skills = useSkills(token);
  const { state: sidebarState, update: updateSidebarState } =
    useSidebarState(sessions, !loading);

  /* ── routing, sidebar, dialogs — from the store ── */
  const activeKey = useShellStore((s) => s.activeKey);
  const view = useShellStore((s) => s.view);
  const settingsInitialSection = useShellStore((s) => s.settingsSection);
  const hostSidebarOpen = useShellStore((s) => s.hostSidebarOpen);
  const [hostSidebarPreviewing, setHostSidebarPreviewing] = useState(false);
  const mobileSidebarOpen = useShellStore((s) => s.mobileSidebarOpen);
  const sessionSearchOpen = useShellStore((s) => s.sessionSearchOpen);
  const pendingDelete = useShellStore((s) => s.pendingDelete);
  const pendingRename = useShellStore((s) => s.pendingRename);
  const pendingProjectRename = useShellStore((s) => s.pendingProjectRename);
  const restartToast = useShellStore((s) => s.restartToast);
  const isRestarting = useShellStore((s) => s.isRestarting);
  const {
    navigate,
    applyRoute,
    toggleSidebar,
    closeHostSidebar,
    openHostSidebar,
    closeMobileSidebar,
    closeSessionSearch,
    closeDeleteDialog,
    closeRenameDialog,
    closeProjectRenameDialog,
    showRestartToast,
    clearRestartToast,
    setIsRestarting,
    openSessionSearch,
    openRenameDialog,
    openProjectRenameDialog,
    openDeleteDialog,
    openMobileSidebar,
  } = useShellStore();

    /* ── Session store ── */
  const runningChatIds = useSessionStore((s) => s.runningChatIds)
  const completedChatIds = useSessionStore((s) => s.completedChatIds)
  const workspaces = useSessionStore((s) => s.workspaces)
  const settingsSnapshot = useSessionStore((s) => s.settingsSnapshot)
  const workspaceError = useSessionStore((s) => s.workspaceError)
  const draftWorkspaceScope = useSessionStore((s) => s.draftWorkspaceScope)
  const workspaceOverrides = useSessionStore((s) => s.workspaceOverrides)
  const {
    addRunning, removeRunning, addCompleted, removeCompleted,
    setWorkspaces, setWorkspaceError, setDraftWorkspaceScope,
    setWorkspaceOverride, setSettingsSnapshot,
    pruneWorkspaceOverrides, pruneCompleted,
  } = useSessionStore.getState();

  /* ── local state (not yet extracted) ── */
  const restartSawDisconnectRef = useRef(false);
  const activeChatIdRef = useRef<string | null>(null);

  useEffect(() => {
    applyRoute();
    window.addEventListener("hashchange", applyRoute);
    return () => window.removeEventListener("hashchange", applyRoute);
  }, [applyRoute]);

  useEffect(() => {
    let cancelled = false;
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) setSettingsSnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) setSettingsSnapshot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  /* sidebar localStorage is handled by the store — this effect is gone */
  /* completedChatIds localStorage stays until we extract that store */

  useEffect(() => {
    writeCompletedRunChatIds(completedChatIds);
  }, [completedChatIds]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const completedChatIdList = useMemo(() => Array.from(completedChatIds), [completedChatIds]);
  const activeChatId = activeSession?.chatId ?? null;
  
  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (!activeChatId) return;
    removeCompleted(activeChatId);
  }, [activeChatId]);
  const activeWorkspaceScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activeSession?.workspaceScope) {
      return activeSession.workspaceScope;
    }
    return draftWorkspaceScope ?? workspaces?.default_scope ?? null;
  }, [
    activeChatId,
    activeSession?.workspaceScope,
    draftWorkspaceScope,
    workspaceOverrides,
    workspaces?.default_scope,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(token);
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [token]);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    if (loading) return;
    const knownChatIds = new Set(sessions.map((session) => session.chatId));
    pruneCompleted(knownChatIds);
    pruneWorkspaceOverrides(knownChatIds);
  }, [loading, sessions]);

  useEffect(() => {
    if (loading || !activeKey) return;
    if (sessions.some((session) => session.key === activeKey)) return;
    const currentRoute = readShellRoute();
    navigate(
      currentRoute.view === "chat"
        ? defaultShellRoute()
        : {
            ...currentRoute,
            activeKey: null,
          },
      { replace: true },
    );
  }, [activeKey, loading, navigate, sessions]);

  useEffect(() => {
    return client.onSessionUpdate((_chatId, _scope, workspaceScope) => {
      if (!workspaceScope) return;
      const next = normalizeWorkspaceScope(workspaceScope);
      setWorkspaceOverride(_chatId, next);
      setDraftWorkspaceScope(next);
      setWorkspaceError(null);
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces]);

  useEffect(() => {
    return client.onError((error) => {
      if (error.kind !== "workspace_scope_rejected") return;
      setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces, t]);

  useEffect(() => {
    if (loading) return;
    const activeRunIds = sessions
      .filter((session) => typeof session.runStartedAt === "number")
      .map((session) => session.chatId);
    if (activeRunIds.length === 0) return;

    for (const chatId of activeRunIds) {
      client.attach(chatId);
      addRunning(chatId);
      removeCompleted(chatId);
    }
  }, [client, loading, sessions]);

  const applyWorkspaceScope = useCallback(
    (scope: WorkspaceScopePayload) => {
      const next = normalizeWorkspaceScope(scope);
      setWorkspaceError(null);
      if (activeChatId) {
        if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, client],
  );

  const onCreateChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      const chatId = await createChat(scope);
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
        settingsSection: "overview",
      });
      closeMobileSidebar();
      if (scope) {
        setWorkspaceOverride(chatId, normalizeWorkspaceScope(scope));
      }
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      if (e instanceof Error && e.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      }
      return null;
    }
  }, [activeWorkspaceScope, createChat, navigate, t]);

  const onNewChat = useCallback(() => {
    navigate(defaultShellRoute());
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    closeSessionSearch();
    closeMobileSidebar();
  }, [navigate, closeSessionSearch, closeMobileSidebar]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
      navigate(defaultShellRoute());
      setDraftWorkspaceScope(normalizeWorkspaceScope({
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        access_mode: base.access_mode,
        restrict_to_workspace: base.access_mode === "restricted",
      }));
      setWorkspaceError(null);
      closeMobileSidebar();
    },
    [activeWorkspaceScope, navigate, onNewChat, workspaces?.default_scope],
  );

  const onSelectChat = useCallback(
    (key: string) => {
      const selected = sessions.find((session) => session.key === key);
      const selectedChatId = selected?.chatId;
      if (selectedChatId) {
        removeCompleted(selectedChatId);
      }
      if (selected?.workspaceScope) {
        setDraftWorkspaceScope(normalizeWorkspaceScope(selected.workspaceScope));
      } else {
        setDraftWorkspaceScope(null);
      }
      setWorkspaceError(null);
      navigate({ view: "chat", activeKey: key, settingsSection: "overview" });
      closeMobileSidebar();
    },
    [navigate, sessions],
  );

  const onTogglePin = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const pinned = new Set(current.pinned_keys);
        if (pinned.has(key)) {
          pinned.delete(key);
        } else {
          pinned.add(key);
        }
        return {
          ...current,
          pinned_keys: Array.from(pinned),
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRename = useCallback((key: string, label: string) => {
    openRenameDialog(key, label);
  }, [openRenameDialog]);

  const onConfirmRename = useCallback(
    (title: string) => {
      if (!pendingRename) return;
      const key = pendingRename.key;
      closeRenameDialog();
      void updateSidebarState((current) => {
        const titleOverrides = { ...current.title_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          titleOverrides[key] = cleaned;
        } else {
          delete titleOverrides[key];
        }
        return {
          ...current,
          title_overrides: titleOverrides,
        };
      });
    },
    [pendingRename, updateSidebarState],
  );

  const onToggleGroup = useCallback(
    (groupId: string) => {
      void updateSidebarState((current) => {
        const collapsedGroups = { ...current.collapsed_groups };
        if (groupId === "workspace:chats" || groupId === "date:all") {
          if (collapsedGroups[groupId] === false) {
            delete collapsedGroups[groupId];
          } else {
            collapsedGroups[groupId] = false;
          }
          return {
            ...current,
            collapsed_groups: collapsedGroups,
          };
        }
        if (collapsedGroups[groupId]) {
          delete collapsedGroups[groupId];
        } else {
          collapsedGroups[groupId] = true;
        }
        return {
          ...current,
          collapsed_groups: collapsedGroups,
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRenameProject = useCallback((key: string, label: string) => {
    openProjectRenameDialog(key, label);
  }, [openProjectRenameDialog]);

  const onConfirmProjectRename = useCallback(
    (title: string) => {
      if (!pendingProjectRename) return;
      const key = pendingProjectRename.key;
      closeProjectRenameDialog();
      void updateSidebarState((current) => {
        const projectNameOverrides = { ...current.project_name_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          projectNameOverrides[key] = cleaned;
        } else {
          delete projectNameOverrides[key];
        }
        return {
          ...current,
          project_name_overrides: projectNameOverrides,
        };
      });
    },
    [pendingProjectRename, updateSidebarState],
  );

  const onToggleArchive = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const archived = new Set(current.archived_keys);
        const pinned = current.pinned_keys.filter((item) => item !== key);
        if (archived.has(key)) {
          archived.delete(key);
        } else {
          archived.add(key);
        }
        return {
          ...current,
          pinned_keys: pinned,
          archived_keys: Array.from(archived),
        };
      });
      if (activeKey === key && !sidebarState.archived_keys.includes(key)) {
        const archived = new Set([...sidebarState.archived_keys, key]);
        const next = sessions.find((session) => !archived.has(session.key));
        navigate({
          view: "chat",
          activeKey: next?.key ?? null,
          settingsSection: "overview",
        });
      }
    },
    [activeKey, navigate, sessions, sidebarState.archived_keys, updateSidebarState],
  );

  const onToggleArchived = useCallback(() => {
    void updateSidebarState((current) => ({
      ...current,
      view: {
        ...current.view,
        show_archived: !current.view.show_archived,
      },
    }));
  }, [updateSidebarState]);

  const onOpenSessionSearch = useCallback(() => {
    closeMobileSidebar();
    openSessionSearch();
  }, [closeMobileSidebar, openSessionSearch]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const commandShiftO =
        (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey;
      if (commandShiftO && event.key.toLowerCase() === "o") {
        event.preventDefault();
        onNewChat();
        return;
      }
      const plainCommandK =
        (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
      if (!plainCommandK) return;
      if (event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      onOpenSessionSearch();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onNewChat, onOpenSessionSearch]);

  const onSelectSearchResult = useCallback(
    (key: string) => {
      closeSessionSearch();
      onSelectChat(key);
    },
    [onSelectChat, closeSessionSearch],
  );

  const onOpenPage = useCallback((page: SettingsSectionKey, shell: ShellView) => {
    closeSessionSearch();
    navigate({ view: shell, activeKey, settingsSection: page })
    closeMobileSidebar()
  }, [activeKey, navigate, closeSessionSearch, closeMobileSidebar])

  const onSettingsSectionChange = useCallback(
    (section: SettingsSectionKey) => {
      navigate({
        view: shellViewForSettingsSection(section),
        activeKey,
        settingsSection: section,
      });
    },
    [activeKey, navigate],
  );

  const onBackToChat = useCallback(() => {
    closeMobileSidebar();
    const nextKey = (() => {
      if (!activeKey) return null;
      if (sessions.some((session) => session.key === activeKey)) return activeKey;
      return sessions[0]?.key ?? null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      settingsSection: "overview",
    });
  }, [activeKey, navigate, sessions, closeMobileSidebar]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    setIsRestarting(true);
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    client.sendMessage(chatId, "/restart");
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onRunStatus((chatId, startedAt) => {
      if (startedAt != null) {
        addRunning(chatId);
        removeCompleted(chatId);
        return;
      }

      removeRunning(chatId);
      /* don't add the active chat to completed — you're looking at it */
      if (activeChatIdRef.current !== chatId) {
        addCompleted(chatId);
      }
    });
  }, [client]);

  useEffect(() => {
    return client.onStatus((status) => {
      const startedAt = (() => {
        try {
          return Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
        } catch {
          return 0;
        }
      })();
      if (!startedAt) return;
      if (status !== "open") {
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
      } catch {
        // ignore storage errors
      }
      setIsRestarting(false);
      showRestartToast(t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }));
      window.setTimeout(() => clearRestartToast(), 3_500);
    });
  }, [client, t]);

  const onTurnEnd = useDeferredTitleRefresh(activeSession, refresh);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    closeDeleteDialog();
    if (deletingActive) {
      navigate({
        view: "chat",
        activeKey: fallbackKey,
        settingsSection: "overview",
      }, { replace: true });
    }
    try {
      await deleteChat(key);
    } catch (e) {
      if (deletingActive) {
        navigate({
          view: "chat",
          activeKey: key,
          settingsSection: "overview",
        }, { replace: true });
      }
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, navigate, sessions]);

  const headerTitle = activeSession
    ? sidebarState.title_overrides[activeSession.key] ||
      activeSession.title ||
      deriveTitle(activeSession.preview, t("chat.newChat"))
    : t("app.brand");

  useEffect(() => {
    if (view === "settings") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.sidebar.title"),
      });
      return;
    }
    if (view === "apps") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.apps", { defaultValue: "Apps" }),
      });
      return;
    }
    if (view === "skills") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.skills", { defaultValue: "Skills" }),
      });
      return;
    }
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t, view]);

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    onNewChat,
    onSelect: onSelectChat,
    onRequestDelete: (key: string, label: string) =>
      openDeleteDialog(key, label),
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenSettings: () => onOpenPage("overview", "settings"),
    onOpenApps: () => onOpenPage("apps", "apps"),
    onOpenSkills: () => onOpenPage("skills", "skills"),
    onOpenSearch: onOpenSessionSearch,
    activeUtility: view === "apps" ? "apps" as const : view === "skills" ? "skills" as const : null,
    onToggleArchived,
    pinnedKeys: sidebarState.pinned_keys,
    archivedKeys: sidebarState.archived_keys,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    completedChatIds: completedChatIdList,
    viewState: sidebarState.view,
    showArchived: sidebarState.view.show_archived,
    archivedCount: sidebarState.archived_keys.length,
    defaultWorkspacePath: workspaces?.default_scope.project_path ?? null,
  };
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const isNativeHostSetupSurface = effectiveRuntimeSurface === "native";
  const showHostChrome = isNativeHostSetupSurface;
  const showMainSidebar = view !== "settings";

  useEffect(() => {
    document.documentElement.classList.toggle("native-host", showHostChrome);
    return () => {
      document.documentElement.classList.remove("native-host");
    };
  }, [showHostChrome]);

  return (
    <ThemeProvider theme={theme}>
      <div
        className={cn(
          "relative h-full w-full overflow-hidden",
          showHostChrome && "host-window-shell",
        )}
      >
        {showHostChrome ? (
          <HostChrome
            onToggleSidebar={showMainSidebar ? toggleSidebar : undefined}
            theme={theme}
            onToggleTheme={toggle}
            sidebarCollapsed={!hostSidebarOpen}
            onSidebarHoverStart={() => setHostSidebarPreviewing(true)}
            onSidebarHoverEnd={() => setHostSidebarPreviewing(false)}
          />
        ) : null}
        <div
          className={cn(
            "relative flex h-full w-full overflow-hidden",
          )}
        >
          {/* Host sidebar: in normal flow, so the thread area width stays honest. */}
          {showMainSidebar ? (
            <aside
              data-testid={showHostChrome ? "host-sidebar-flow" : undefined}
              className={cn(
                "relative z-20 hidden shrink-0 overflow-hidden lg:block",
                "transition-[width] duration-300 ease-out",
              )}
              style={{
                width: showHostChrome
                  ? (hostSidebarOpen ? SIDEBAR_WIDTH : 0)
                  : (hostSidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_RAIL_WIDTH),
              }}
            >
              <div
                aria-hidden={showHostChrome && !hostSidebarOpen ? true : undefined}
                className={cn(
                  "absolute inset-y-0 left-0 h-full w-full overflow-hidden",
                  showHostChrome
                    ? "host-sidebar-glass"
                    : "bg-sidebar shadow-inner-right",
                )}
              >
                <Sidebar
                  {...sidebarProps}
                  collapsed={!hostSidebarOpen}
                  hostChromeInset={showHostChrome}
                  onCollapse={closeHostSidebar}
                  onExpand={openHostSidebar}
                />
              </div>
            </aside>
          ) : null}

          {/* Host sidebar hover preview */}
          {showMainSidebar && showHostChrome && !hostSidebarOpen && hostSidebarPreviewing && (
            <aside
              data-testid="host-sidebar-preview"
              className="absolute inset-y-0 left-0 z-30 overflow-hidden"
              style={{ width: SIDEBAR_WIDTH }}
            >
              <div className="h-full w-full overflow-hidden host-sidebar-glass">
                <Sidebar
                  {...sidebarProps}
                  collapsed={false}
                  hostChromeInset
                  onCollapse={closeHostSidebar}
                  onExpand={openHostSidebar}
                />
              </div>
            </aside>
          )}

          {showMainSidebar ? (
            <Sheet
              open={mobileSidebarOpen}
              onOpenChange={(open) => open ? openMobileSidebar() : closeMobileSidebar()}
            >
              <SheetContent
                side="left"
                showCloseButton={false}
                aria-describedby={undefined}
                className="p-0 lg:hidden"
                style={{ width: SIDEBAR_WIDTH, maxWidth: SIDEBAR_WIDTH }}
              >
                <SheetTitle className="sr-only">{t("sidebar.mobileNavigation")}</SheetTitle>
                <Sidebar
                  {...sidebarProps}
                  onCollapse={closeMobileSidebar}
                  containActionMenus
                  ariaLabel={t("sidebar.mobileNavigation")}
                />
              </SheetContent>
            </Sheet>
          ) : null}

          <SessionSearchDialog
            open={sessionSearchOpen}
            onOpenChange={(open) => open ? openSessionSearch() : closeSessionSearch()}
            sessions={sessions}
            activeKey={activeKey}
            loading={loading}
            titleOverrides={sidebarState.title_overrides}
            onSelect={onSelectSearchResult}
          />
        <main
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
            showHostChrome && "border-l border-border/55",
          )}
        >
            <div
              className={cn(
                "absolute inset-0 flex flex-col",
                view !== "chat" && "invisible pointer-events-none",
              )}
            >
              <ThreadShell
                session={activeSession}
                title={headerTitle}
                onToggleSidebar={toggleSidebar}
                onNewChat={onNewChat}
                onCreateChat={onCreateChat}
                onTurnEnd={onTurnEnd}
                theme={theme}
                onToggleTheme={toggle}
                hideSidebarToggleForHostChrome
                hideThemeButton={showHostChrome}
                hideHeader={false}
                workspaceScope={activeWorkspaceScope}
                workspaceDefaultScope={workspaces?.default_scope ?? null}
                workspaceControls={workspaces?.controls ?? null}
                workspaceScopeDisabled={activeChatRunning}
                workspaceError={workspaceError}
                onWorkspaceScopeChange={applyWorkspaceScope}
                settingsSnapshot={settingsSnapshot}
              />
            </div>
            {view !== "chat" && (
              <div className="absolute inset-0 flex flex-col">
                <SettingsView
                  theme={theme}
                  initialSection={settingsInitialSection as SettingsSectionKey}
                  showSidebar={view === "settings"}
                  onToggleTheme={toggle}
                  onBackToChat={onBackToChat}
                  onModelNameChange={onModelNameChange}
                  onSettingsChange={setSettingsSnapshot}
                  onWorkspaceSettingsChange={refreshWorkspaces}
                  onSectionChange={onSettingsSectionChange}
                  onLogout={onLogout}
                  onRestart={onRestart}
                  onNativeEngineRestart={onNativeEngineRestart}
                  isRestarting={isRestarting}
                  hostChromeInset={showHostChrome}
                  skills={skills}
                />
              </div>
            )}
          </main>
        </div>

        <DeleteConfirm
          open={!!pendingDelete}
          title={pendingDelete?.label ?? ""}
          onCancel={closeDeleteDialog}
          onConfirm={onConfirmDelete}
        />
        <RenameChatDialog
          open={!!pendingRename}
          title={pendingRename?.label ?? ""}
          onCancel={closeRenameDialog}
          onConfirm={onConfirmRename}
        />
        <RenameChatDialog
          open={!!pendingProjectRename}
          title={pendingProjectRename?.label ?? ""}
          dialogTitle={t("chat.renameProjectTitle")}
          description={t("chat.renameProjectDescription")}
          placeholder={t("chat.renameProjectPlaceholder")}
          onCancel={closeProjectRenameDialog}
          onConfirm={onConfirmProjectRename}
        />
        {restartToast ? (
          <div
            role="status"
            className="fixed left-1/2 top-4 z-50 -translate-x-1/2 rounded-full border border-border/70 bg-popover px-4 py-2 text-sm font-medium text-popover-foreground shadow-lg"
          >
            {restartToast}
          </div>
        ) : null}
      </div>
    </ThemeProvider>
  );
}