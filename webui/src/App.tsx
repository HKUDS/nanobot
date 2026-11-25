import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { ArrowRight, CircleHelp, Eye, EyeOff, Loader2 } from "lucide-react";
import { ThemeToggleIcon } from "@/components/icons/ThemeToggleIcon";
import { Trans, useTranslation } from "react-i18next";
import { localeDirection } from "@/i18n/config";
import { ChannelPairing } from "@/components/pairing/ChannelPairing";
import { StarPrompt } from "@/components/StarPrompt";
import { Sidebar } from "@/components/Sidebar";
import { RemoteInstances } from "@/components/remote/RemoteInstances";
import { useRemoteConnections } from "@/components/remote/remote-context";
import { LazyRemoteConnectionsPage } from "@/components/remote/LazyRemoteConnectionsPage";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SidebarResizeHandle, SIDEBAR_MIN_WIDTH, SIDEBAR_MAX_WIDTH } from "@/components/SidebarResizeHandle";
import { matchSidebarShortcut } from "@/lib/sidebar-shortcuts";
import { invalidateToolsCatalog } from "@/lib/tools-catalog-cache";
import type { SidebarDeleteItem } from "@/components/ChatList";
import type { SettingsSectionKey } from "@/components/settings/SettingsView";
import { StartupShell } from "@/components/StartupShell";
import { ComposerDraftStore } from "@/lib/composer-draft";
import { ThreadVisibilityContext } from "@/hooks/useThreadVisibility";
import { isAppsSection, type SettingsExitGuard, type SettingsFocusTarget } from "@/components/settings/contracts";
import {
  RESTART_ROUTE_KEY,
  RESTART_STARTED_KEY,
  changesSettingsSurface,
  defaultShellRoute,
  readShellRoute,
  rememberRestartRoute,
  shellViewForSettingsSection,
  writeShellRoute,
  type ShellRoute,
  type ShellView,
} from "@/shell-route";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import { transitionSession } from "@/components/thread/session-transition";
import {
  MAX_WORKBENCH_PANES,
  addWorkbenchPane,
  attachWorkbenchPane,
  createWorkbenchTab,
  detachWorkbenchPane,
  dissolveWorkbenchTab,
  orderWorkbenchTabs,
  reconcileWorkbench,
  renameWorkbenchTab,
  setWorkbenchLayout,
  setWorkbenchPaneLayoutOrder,
  setWorkbenchSplitRatios,
  workbenchTab,
  workbenchTabForPane,
  type WorkbenchState,
} from "@/components/workbench/workbench-model";
import { ToastProvider, useToast, type ToastNotice } from "@/components/ui/toast";
import {
  AutomationDeleteToastDetails,
  type AutomationDeleteSessionGroup,
} from "@/components/AutomationDeleteToastDetails";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

import { useLocalGateway } from "@/hooks/useLocalGateway";
import { useSessions } from "@/hooks/useSessions";
import { useReconnectRuns } from "@/hooks/useReconnectRuns";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { useSidebarState } from "@/hooks/useSidebarState";
import { useSkills } from "@/hooks/useSkills";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useAppViewport } from "@/hooks/useAppViewport";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { useReadingTypography } from "@/hooks/useReadingTypography";
import { cn } from "@/lib/utils";
import { displayTitle, sortSessions } from "@/lib/chat-groups";
import { deriveTitle } from "@/lib/format";
import { BrowserNotifications, useBrowserNotificationLifecycle } from "@/components/BrowserNotifications";
import { switchModelPreset } from "@/lib/switch-model-preset";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { FilePreviewStore } from "@/hooks/useFilePreviewState";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import { BackgroundProvider } from "@/providers/BackgroundProvider";
import { useVersionCheck } from "@/providers/VersionCheckProvider";
import { useUpdateFlow } from "@/providers/UpdateFlowProvider";
import type {
  ChatSummary,
  RuntimeSurface,
  SessionAutomationJob,
  SettingsPayload,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { HoverHint } from "@/components/ui/hover-hint";
import { fetchSettings, fetchWorkspaces } from "@/lib/api";
import { isNativeRuntime } from "@/lib/runtime";
import { projectNameFromPath, scopeWithAccessMode } from "@/lib/workspace";
import {
  createTemporaryChatSession,
  deriveTemporaryChatTitle,
} from "@/lib/temporary-chat";

const SIDEBAR_STORAGE_KEY = "nanobot-webui.sidebar";
const SESSION_UPDATES_STORAGE_KEY = "nanobot-webui.sidebar.session-updates.v1";
const LEGACY_COMPLETED_RUNS_STORAGE_KEY = "nanobot-webui.sidebar.completed-runs.v1";
const SIDEBAR_WIDTH = 272;
const SIDEBAR_WIDTH_STORAGE_KEY = "nanobot-webui.sidebar.width";
const SIDEBAR_RAIL_WIDTH = 56;
const MOBILE_SIDEBAR_WIDTH = `min(${SIDEBAR_WIDTH}px, calc(100vw - 0.75rem))`;
const loadThreadShell = () => import("@/components/thread/ThreadShell");
const ThreadShell = lazy(() => loadThreadShell().then(
  (module) => ({ default: module.ThreadShell }),
));
const loadSettingsView = () => import("@/components/settings/SettingsView");
const SettingsView = lazy(async () => {
  const module = await loadSettingsView();
  return { default: module.SettingsView };
});
const SessionSearchDialog = lazy(async () => {
  const module = await import("@/components/SessionSearchDialog");
  return { default: module.SessionSearchDialog };
});
const RenameDialog = lazy(async () => {
  const module = await import("@/components/RenameDialog");
  return { default: module.RenameDialog };
});

function AuthForm({ onSecret }: {
  onSecret: (secret: string, onAuthRejected: () => void) => void;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<"required" | "invalid" | null>(null);
  const helpTitle = t("app.auth.helpTitle");
  const passwordLabel = t("app.auth.label");
  const requiredMessage = t("app.auth.required");
  const invalidMessage = t("app.auth.invalid");
  const errorMessage = validationError === "required" ? requiredMessage
    : validationError === "invalid" ? invalidMessage : null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    const secret = value.trim();
    if (!secret) {
      setValue("");
      setValidationError("required");
      inputRef.current?.focus();
      return;
    }
    setSubmitting(true);
    onSecret(secret, () => {
      setValue("");
      setPasswordVisible(false);
      setSubmitting(false);
      setValidationError("invalid");
      inputRef.current?.focus();
    });
  };

  return (
    <main className="flex h-full w-full flex-col overflow-y-auto bg-background">
      <div className="mx-5 mt-3.5 flex shrink-0 items-center gap-2 self-end sm:mx-8">
        <LanguageSwitcher className="h-8 min-w-0 gap-2 px-3 text-xs" />
        <Dialog>
          <HoverHint content={helpTitle} side="bottom" align="end">
            <DialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={helpTitle}
                className="h-11 w-11 rounded-full text-muted-foreground"
              >
                <CircleHelp className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
              </Button>
            </DialogTrigger>
          </HoverHint>
          <DialogContent className="max-w-md gap-5">
            <DialogTitle className="pe-8 leading-snug">{helpTitle}</DialogTitle>
            <div className="min-w-0 space-y-4 text-sm leading-6 text-muted-foreground">
              <div>
                <DialogDescription className="leading-6">{t("app.auth.helpConfig")}</DialogDescription>
                <code className="mt-2 block rounded-compact bg-muted px-3 py-2 font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere]">
                  ~/.nanobot/config.json
                </code>
              </div>
              <div>
                <p>{t("app.auth.helpSecret")}</p>
                <code className="mt-2 block rounded-compact bg-muted px-3 py-2 font-mono text-xs leading-5 text-foreground [overflow-wrap:anywhere]">
                  channels.websocket.tokenIssueSecret
                </code>
              </div>
              <p>
                <Trans
                  i18nKey="app.auth.helpFallback"
                  components={{ code: <code className="font-mono text-xs text-foreground [overflow-wrap:anywhere]" /> }}
                />
              </p>
            </div>
          </DialogContent>
        </Dialog>
      </div>
      <div className="flex flex-1 shrink-0 items-center justify-center px-4 pb-14 pt-6 sm:px-6 sm:pb-20">
        <section
          aria-labelledby="webui-auth-title"
          className="w-full max-w-[27rem] rounded-modal border border-border/70 bg-muted/55 px-6 pb-6 pt-12 [background-image:radial-gradient(ellipse_at_50%_0%,hsl(var(--usage-token)/0.18),transparent_66%)] sm:px-12 sm:pb-8 sm:pt-14"
        >
          <div className="text-center">
            <div className="mx-auto mb-7 grid h-24 w-24 place-items-center rounded-full bg-gradient-to-b from-card to-card/35 shadow-[0_16px_28px_hsl(var(--foreground)/0.10)] dark:shadow-[0_16px_28px_rgba(0,0,0,0.28)]">
              <img src="/brand/nanobot_mark.svg" alt="" width={56} height={56}
                draggable={false} className="h-14 w-14 select-none" />
            </div>
            <h1 id="webui-auth-title" className="text-balance text-2xl font-semibold tracking-tight text-foreground">
              {t("app.auth.title")}
            </h1>
          </div>
          <form onSubmit={handleSubmit} className="mt-8">
            <label htmlFor="webui-access-password" className="sr-only">{passwordLabel}</label>
            <div className="relative">
              <Input
                ref={inputRef}
                id="webui-access-password"
                name="webui-access-password"
                dir="ltr"
                type={passwordVisible ? "text" : "password"}
                autoComplete="current-password"
                placeholder={passwordLabel}
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setValidationError(null);
                }}
                readOnly={submitting}
                aria-invalid={validationError ? true : undefined}
                aria-describedby={validationError ? "webui-auth-error" : undefined}
                className="h-12 rounded-full border-border bg-background/85 ps-4 pe-14 text-base"
                autoFocus
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={submitting}
                aria-label={t(
                  passwordVisible ? "app.auth.hidePassword" : "app.auth.showPassword",
                )}
                aria-controls="webui-access-password"
                onClick={() => setPasswordVisible((visible) => !visible)}
                className="absolute end-0.5 top-1/2 h-11 w-11 -translate-y-1/2 rounded-full text-muted-foreground hover:text-foreground"
              >
                {passwordVisible ? (
                  <EyeOff className="h-4 w-4" strokeWidth={1.75} aria-hidden />
                ) : (
                  <Eye className="h-4 w-4" strokeWidth={1.75} aria-hidden />
                )}
              </Button>
            </div>
            <div className="mt-2 grid px-4 text-[13px] leading-5 text-destructive">
              <span aria-hidden="true" className="invisible col-start-1 row-start-1">{requiredMessage}</span>
              <span aria-hidden="true" className="invisible col-start-1 row-start-1">{invalidMessage}</span>
              {errorMessage ? (
                <p id="webui-auth-error" role="alert" className="col-start-1 row-start-1">{errorMessage}</p>
              ) : null}
            </div>
            <Button type="submit" size="lg" disabled={submitting} aria-busy={submitting || undefined}
              className="relative mt-3 w-full rounded-full px-11">
              {t("app.auth.submit")}
              {submitting ? (
                <Loader2 className="absolute end-4 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <ArrowRight className="absolute end-4 h-4 w-4 rtl:rotate-180" strokeWidth={1.75} aria-hidden />
              )}
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}

function readSidebarWidth(): number {
  try {
    const width = Number(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));
    return Number.isFinite(width) && width >= SIDEBAR_MIN_WIDTH
      ? Math.min(SIDEBAR_MAX_WIDTH, width) : SIDEBAR_WIDTH;
  } catch {
    return SIDEBAR_WIDTH;
  }
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

function readSessionUpdateChatIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw =
      window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY)
      ?? window.localStorage.getItem(LEGACY_COMPLETED_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

function writeSessionUpdateChatIds(chatIds: Set<string>): void {
  try {
    window.localStorage.setItem(
      SESSION_UPDATES_STORAGE_KEY,
      JSON.stringify(Array.from(chatIds)),
    );
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

function normalizeWorkspaceScope(scope: WorkspaceScopePayload): WorkspaceScopePayload {
  const accessMode = scope.access_mode === "restricted" ? "restricted" : "full";
  return {
    ...scope,
    project_name: scope.project_name ?? projectNameFromPath(scope.project_path),
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}

function HostChrome({
  rightAction,
}: {
  rightAction?: ReactNode;
}) {
  return (
    <header className="host-drag-region pointer-events-none absolute inset-x-0 top-0 z-40 h-11 bg-transparent text-foreground/90">
      {rightAction ? (
        <div className="host-no-drag pointer-events-auto absolute right-3 top-2">
          {rightAction}
        </div>
      ) : null}
    </header>
  );
}

function prefetchChat() {
  if (readShellRoute().view === "chat") void loadThreadShell().catch(() => {});
}

export default function App() {
  useAppViewport();
  useBrowserNotificationLifecycle();
  useReadingTypography();
  const { t } = useTranslation();
  const { state, bootstrapWithSecret, changeModelName, logout, restartEngine } = useLocalGateway(prefetchChat);

  if (state.status === "loading") {
    return <StartupShell />;
  }
  if (state.status === "auth") {
    return <AuthForm onSecret={bootstrapWithSecret} />;
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      modelName={state.modelName}
      ingressLimits={state.ingressLimits}
      webuiCapabilities={state.webuiCapabilities}
      allowUpdateFlow={state.runtimeSurface !== "native"}
    >
      <BrowserNotifications client={state.client} />
      <BackgroundProvider><RemoteInstances><ToastProvider><Shell
        runtimeSurface={state.runtimeSurface}
        onModelNameChange={changeModelName}
        onLogout={logout}
        onNativeEngineRestart={restartEngine}
      /></ToastProvider></RemoteInstances></BackgroundProvider>
    </ClientProvider>
  );
}

function restorePinOrder(pins: readonly string[], previous: readonly string[], restoring: ReadonlySet<string>) {
  const next = [...pins];
  previous.forEach((key, index) => {
    if (!restoring.has(key) || next.includes(key)) return;
    const successor = previous.slice(index + 1).find((candidate) => next.includes(candidate));
    const predecessor = previous.slice(0, index).reverse().find((candidate) => next.includes(candidate));
    const offset = successor !== undefined ? next.indexOf(successor)
      : predecessor !== undefined ? next.indexOf(predecessor) + 1 : next.length;
    next.splice(offset, 0, key);
  });
  return next;
}

function Shell({
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
  const showToast = useToast()!; // App always renders Shell inside ToastProvider.
  const remoteConnections = useRemoteConnections();
  const versionCheck = useVersionCheck();
  const updateFlow = useUpdateFlow();
  const localActive = remoteConnections?.localActive !== false;
  const managingConnections = remoteConnections?.managing === true && !remoteConnections?.activeHostId;
  const { theme, preference: themePreference, toggle, setTheme } = useTheme();
  const managementMain = useRef<HTMLElement>(null);
  const reportManagementSurface = remoteConnections?.reportManagementSurface;
  useEffect(() => {
    const main = managementMain.current;
    if (!main || !reportManagementSurface) return;
    const report = () => {
      const rect = main.getBoundingClientRect();
      reportManagementSurface({ left: rect.left, top: rect.top, width: rect.width, height: rect.height }, theme);
    };
    const observer = new ResizeObserver(report);
    observer.observe(main);
    window.addEventListener("resize", report);
    report();
    return () => { observer.disconnect(); window.removeEventListener("resize", report); };
  }, [reportManagementSurface, theme]);
  const remoteConnectionsRef = useRef(remoteConnections);
  remoteConnectionsRef.current = remoteConnections;
  const { client, getToken } = useClient();
  useReconnectRuns(client, getToken);
  const [includeArchived, setIncludeArchived] = useState(false);
  const {
    sessions,
    loading,
    archivedKeys,
    archivesLoaded,
    initialLoading: sessionsInitialLoading,
    error: sessionsError,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  } = useSessions(includeArchived);
  // Failed reads retain an empty list or partial reload cache, not proof of deletion.
  const sessionsLoaded = !loading && sessionsError === null;
  const catalogLoaded = sessionsLoaded && archivesLoaded;
  const {
    state: sidebarState,
    loading: sidebarStateLoading,
    update: updateSidebarState,
    rename: onRequestRename,
  } =
    useSidebarState(sessions, catalogLoaded);
  const initialRouteRef = useRef<ShellRoute | null>(null);
  if (!initialRouteRef.current) initialRouteRef.current = readShellRoute();
  const [activeKey, setActiveKey] = useState<string | null>(
    initialRouteRef.current.activeKey,
  );
  const [view, setView] = useState<ShellView>(initialRouteRef.current.view);
  const [chatVisited, setChatVisited] = useState(initialRouteRef.current.view === "chat");
  useEffect(() => {
    if (view === "chat") setChatVisited(true);
  }, [view]);
  useEffect(() => {
    // Normalize legacy links while retaining their return destination in history.
    if (new URLSearchParams(window.location.hash.split("?")[1]).has("chat")) {
      writeShellRoute(initialRouteRef.current!, true);
    }
  }, []);
  const [temporarySessions, setTemporarySessions] = useState<Record<string, ChatSummary>>({});
  const [temporaryChatEnabled, setTemporaryChatEnabled] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] =
    useState<SettingsSectionKey>(initialRouteRef.current.settingsSection);
  const [settingsFocus, setSettingsFocus] = useState<SettingsFocusTarget | undefined>(initialRouteRef.current.settingsFocus);
  const [preferredSidebarOpen, setPreferredSidebarOpen] = useState(readSidebarOpen);
  const [sidebarWidth, setSidebarWidth] = useState(readSidebarWidth);
  const [sidebarDragging, setSidebarDragging] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  useEffect(() => {
    // The drawer portals outside the local host panel; don't leave it over a remote view.
    if (!localActive || managingConnections) setMobileSidebarOpen(false);
  }, [localActive, managingConnections]);
  const mobileSidebarRef = useRef<HTMLDivElement>(null);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const mobileWorkbench = useMediaQuery("(max-width: 767px)");
  const workbenchState = sidebarState.workbench;
  const updateWorkbenchState = useCallback((
    updater: (current: WorkbenchState) => WorkbenchState,
  ) => {
    void updateSidebarState((current) => {
      const next = updater(current.workbench);
      return next === current.workbench ? current : { ...current, workbench: next };
    });
  }, [updateSidebarState]);
  const lastActivePaneByTabRef = useRef(new Map<string, string>());
  const [creatingPane, setCreatingPane] = useState(false);
  const [deletingKeys, setDeletingKeys] = useState<Set<string>>(() => new Set());
  const topicSessions = useMemo(() => deletingKeys.size === 0 ? sessions
    : sessions.filter((session) => !deletingKeys.has(session.key)), [deletingKeys, sessions]);
  const archiveUndoOwners = useRef(new Map<string, {
    operation: symbol; archived: boolean; observed: boolean; pinOrder?: string[];
  }>());
  const archivePending = useRef(new Set<string>());
  const archivedPaneKeys = useMemo(() => new Set(archivedKeys), [archivedKeys]);
  useEffect(() => {
    if (!sessionsLoaded || !archiveUndoOwners.current.size) return;
    const listed = new Set(sessions.map((session) => session.key));
    for (const [key, owner] of archiveUndoOwners.current) {
      // Once our change appears in the list, a subsequent change (possibly
      // from another window) ends our right to undo it or restore its pins.
      const matches = owner.archived
        ? archivesLoaded ? archivedPaneKeys.has(key) : !listed.has(key)
        : listed.has(key) && !archivedPaneKeys.has(key);
      if (matches) owner.observed = true;
      else if (owner.observed) archiveUndoOwners.current.delete(key);
    }
  }, [archivedPaneKeys, archivesLoaded, sessions, sessionsLoaded]);
  const archiveNavigation = useRef<{ topicSessions: ChatSummary[]; archivedPaneKeys: Set<string> } | null>(null);
  useEffect(() => {
    if (localActive && !managingConnections) archiveNavigation.current = { topicSessions, archivedPaneKeys };
    return () => { archiveNavigation.current = null; };
  }, [archivedPaneKeys, localActive, managingConnections, topicSessions]);
  const [pendingTabRename, setPendingTabRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [pendingProjectRename, setPendingProjectRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const restartSawDisconnectRef = useRef(false);
  const restartStartedAtRef = useRef(0);
  const [isRestarting, setIsRestarting] = useState(false);
  const [runningChatIds, setRunningChatIds] = useState<Set<string>>(() => new Set());
  const [updatedChatIds, setUpdatedChatIds] = useState<Set<string>>(readSessionUpdateChatIds);
  const [workspaces, setWorkspaces] = useState<WorkspacesPayload | null>(null);
  const { skills, loading: skillsLoading, error: skillsError } = useSkills(getToken);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsPayload | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const settingsSnapshotRef = useRef(settingsSnapshot);
  settingsSnapshotRef.current = settingsSnapshot;
  const settingsOwnsSnapshot = view !== "chat" && view !== "remote";
  const settingsRefreshGenerationRef = useRef(0);
  const [pendingAutomationMessage, setPendingAutomationMessage] = useState<{
    id: string;
    chatId: string;
    content: string;
    images?: SendAttachment[];
    options?: SendOptions;
  } | null>(null);
  const settingsExitGuardRef = useRef<SettingsExitGuard | null>(null);
  const currentShellRouteRef = useRef<ShellRoute>({ view, activeKey, settingsSection: settingsInitialSection });
  currentShellRouteRef.current = {
    view, activeKey, settingsSection: settingsInitialSection,
    settingsFocus,
    temporary: Boolean(activeKey && temporarySessions[activeKey]),
  };
  const registerSettingsExitGuard = useCallback((guard: SettingsExitGuard | null) => {
    settingsExitGuardRef.current = guard;
  }, []);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [draftWorkspaceScope, setDraftWorkspaceScope] =
    useState<WorkspaceScopePayload | null>(null);
  const [workspaceOverrides, setWorkspaceOverrides] =
    useState<Record<string, WorkspaceScopePayload>>({});
  const runningChatIdsRef = useRef<Set<string>>(new Set());
  const activeChatIdRef = useRef<string | null>(null);
  const pendingCreatedSessionKeyRef = useRef<string | null>(null);
  const temporarySessionsRef = useRef<Record<string, ChatSummary>>({});
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const showHostChrome = isNativeRuntime(effectiveRuntimeSurface);
  const showMainSidebar = view !== "settings";
  const activeTemporarySession = activeKey ? temporarySessions[activeKey] ?? null : null;
  const temporaryChatId = activeTemporarySession?.chatId ?? null;
  const temporaryChatActive = temporaryChatId !== null;
  const temporaryChatRequested = temporaryChatActive || temporaryChatEnabled;
  const temporarySessionList = useMemo(
    () => Object.values(temporarySessions).sort((a, b) => (
      Date.parse(b.createdAt ?? "") - Date.parse(a.createdAt ?? "")
    )),
    [temporarySessions],
  );
  // Start each confirmed empty period collapsed without overwriting the saved preference.
  const [emptySidebarOpen, setEmptySidebarOpen] = useState<boolean | null>(null);
  const hasSessions = sessions.length > 0 || temporarySessionList.length > 0;
  if (hasSessions && emptySidebarOpen !== null) setEmptySidebarOpen(null);
  if (!hasSessions && sessionsLoaded && emptySidebarOpen === null) setEmptySidebarOpen(false);
  const hostSidebarOpen = emptySidebarOpen ?? preferredSidebarOpen;
  const setHostSidebarOpen = emptySidebarOpen === null ? setPreferredSidebarOpen : setEmptySidebarOpen;

  const temporaryChatIds = useMemo(
    () => temporarySessionList.map((session) => session.chatId),
    [temporarySessionList],
  );
  // Pane shells can unmount during navigation. Keep replay state for this app
  // session, pinning temporary chats because they cannot reload disk history.
  const retainedTemporaryChatIdsRef = useRef(new Set<string>());
  const [draftStore] = useState(() => new ComposerDraftStore());
  const [filePreviewStore] = useState(() => new FilePreviewStore());
  const [threadMessageCache] = useState(() => new ThreadMessageCache(
    (key) => retainedTemporaryChatIdsRef.current.has(key),
  ));
  useEffect(() => {
    const retained = new Set(temporaryChatIds);
    for (const chatId of retainedTemporaryChatIdsRef.current) {
      if (!retained.has(chatId)) {
        threadMessageCache.delete(chatId);
        filePreviewStore.delete(`websocket:${chatId}`);
        draftStore.delete(`websocket:${chatId}`);
      }
    }
    retainedTemporaryChatIdsRef.current = retained;
  }, [temporaryChatIds, threadMessageCache, filePreviewStore, draftStore]);

  const commitNavigation = useCallback((route: ShellRoute, options?: { replace?: boolean }) => {
    // The visible sidebar always belongs to its existing host. Navigation
    // dismisses global management without switching to a different host.
    if (remoteConnectionsRef.current?.managing) remoteConnectionsRef.current.closeManagement();
    setActiveKey(route.activeKey);
    setView(route.view);
    setSettingsInitialSection(route.settingsSection);
    setSettingsFocus(route.settingsFocus);
    writeShellRoute({
      ...route,
      temporary: route.temporary || Boolean(route.activeKey && temporarySessionsRef.current[route.activeKey]),
    }, options?.replace);
  }, []);
  const changesVisibleSession = useCallback((current: ShellRoute, next: ShellRoute) => {
    if (current.view !== "chat" || next.view !== "chat" || current.activeKey === next.activeKey) return false;
    if (mobileWorkbench || !current.activeKey || !next.activeKey) return true;
    return workbenchTabForPane(workbenchState, current.activeKey).tabKey
      !== workbenchTabForPane(workbenchState, next.activeKey).tabKey;
  }, [mobileWorkbench, workbenchState]);
  const navigate = useCallback(
    (route: ShellRoute, options?: { replace?: boolean; animate?: boolean }) => {
      const current = currentShellRouteRef.current;
      const leave = () => transitionSession(
        () => commitNavigation(route, options),
        options?.animate !== false && changesVisibleSession(current, route),
      );
      if (changesSettingsSurface(current, route) && settingsExitGuardRef.current) {
        settingsExitGuardRef.current(leave, { promptRestart: current.view !== route.view });
      } else leave();
    },
    [commitNavigation, changesVisibleSession],
  );

  useEffect(() => {
    const applyRoute = () => {
      const route = readShellRoute();
      if (route.view === "remote") setMobileSidebarOpen(false);
      const current = currentShellRouteRef.current;
      if (changesSettingsSurface(current, route) && settingsExitGuardRef.current) {
        writeShellRoute(current, true);
        settingsExitGuardRef.current(() => {
          setActiveKey(route.activeKey);
          setView(route.view);
          setSettingsInitialSection(route.settingsSection);
          setSettingsFocus(route.settingsFocus);
          writeShellRoute(route, true);
          setWorkspaceError(null);
          if (route.view === "chat" && !route.activeKey) setDraftWorkspaceScope(null);
        }, { promptRestart: current.view !== route.view });
        return;
      }
      transitionSession(() => {
        setActiveKey(route.activeKey);
        setView(route.view);
        setSettingsInitialSection(route.settingsSection);
        setSettingsFocus(route.settingsFocus);
        setWorkspaceError(null);
        if (route.view === "chat" && !route.activeKey) {
          setDraftWorkspaceScope(null);
        }
      }, changesVisibleSession(current, route));
    };
    window.addEventListener("hashchange", applyRoute);
    window.addEventListener("popstate", applyRoute);
    return () => {
      window.removeEventListener("hashchange", applyRoute);
      window.removeEventListener("popstate", applyRoute);
    };
  }, [changesVisibleSession]);

  useEffect(() => {
    temporarySessionsRef.current = temporarySessions;
  }, [temporarySessions]);

  useEffect(() => {
    if (view === "chat" && !activeKey) return;
    setTemporaryChatEnabled(false);
  }, [activeKey, view]);

  useEffect(() => () => {
    for (const session of Object.values(temporarySessionsRef.current)) {
      client.discardTemporaryChat(session.chatId);
    }
  }, [client]);

  useEffect(() => {
    if (settingsOwnsSnapshot || settingsSnapshotRef.current !== null) {
      setSettingsLoading(false);
      return;
    }
    let cancelled = false;
    const requestGeneration = settingsRefreshGenerationRef.current;
    setSettingsLoading(true);
    fetchSettings(getToken(), "", client)
      .then((payload) => {
        if (!cancelled && requestGeneration === settingsRefreshGenerationRef.current) {
          setSettingsSnapshot(payload);
        }
      })
      .catch(() => {
        if (!cancelled && requestGeneration === settingsRefreshGenerationRef.current) {
          setSettingsSnapshot(null);
        }
      })
      .finally(() => {
        if (!cancelled) setSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, getToken, settingsOwnsSnapshot]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        preferredSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
    } catch {
      // Storage can be unavailable in private browsing.
    }
  }, [preferredSidebarOpen, sidebarWidth]);

  useEffect(() => {
    writeSessionUpdateChatIds(updatedChatIds);
  }, [updatedChatIds]);

  useEffect(() => client.onReady(() => invalidateToolsCatalog(client)), [client]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    if (temporarySessions[activeKey]) return temporarySessions[activeKey];
    return topicSessions.find((s) => s.key === activeKey) ?? null;
  }, [topicSessions, activeKey, temporarySessions]);
  const activeTabMatch = useMemo(() => (
    activeKey && !temporarySessions[activeKey]
      ? workbenchTabForPane(workbenchState, activeKey)
      : null
  ), [activeKey, temporarySessions, workbenchState]);
  const activeTabKey = activeTabMatch?.tabKey ?? null;
  const activeTabState = activeTabMatch?.tab ?? null;
  const activePaneSession = activeSession;
  useEffect(() => {
    if (!activeTabKey || !activeKey || !activeTabState?.paneKeys.includes(activeKey)) return;
    lastActivePaneByTabRef.current.set(activeTabKey, activeKey);
  }, [activeKey, activeTabKey, activeTabState]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const updatedChatIdList = useMemo(() => Array.from(updatedChatIds), [updatedChatIds]);
  const recoveryChatIdList = useMemo(
    () => sessions
      .filter((session) => (
        session.recoveryState?.status === "awaiting_user"
        || session.recoveryState?.status === "failed"
      ))
      .map((session) => session.chatId),
    [sessions],
  );
  const activeChatId = activePaneSession?.chatId ?? null;
  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (!activeChatId) return;
    setUpdatedChatIds((current) => {
      if (!current.has(activeChatId)) return current;
      const next = new Set(current);
      next.delete(activeChatId);
      return next;
    });
  }, [activeChatId]);
  const activeWorkspaceScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (temporaryChatRequested) {
      return workspaces?.default_scope
        ? normalizeWorkspaceScope(scopeWithAccessMode(workspaces.default_scope, "restricted"))
        : null;
    }
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activePaneSession?.workspaceScope) {
      return activePaneSession.workspaceScope;
    }
    return draftWorkspaceScope ?? workspaces?.default_scope ?? null;
  }, [
    activeChatId,
    activePaneSession?.workspaceScope,
    draftWorkspaceScope,
    temporaryChatRequested,
    workspaceOverrides,
    workspaces?.default_scope,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(getToken());
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [getToken]);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    if (!catalogLoaded) return;
    const knownChatIds = new Set(sessions.map((session) => session.chatId));
    setUpdatedChatIds((current) => {
      const next = new Set(
        Array.from(current).filter((chatId) => knownChatIds.has(chatId)),
      );
      return next.size === current.size ? current : next;
    });
    setWorkspaceOverrides((current) => {
      const entries = Object.entries(current).filter(([chatId]) => knownChatIds.has(chatId));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [catalogLoaded, sessions]);

  useEffect(() => {
    if (!sessionsLoaded || sidebarStateLoading) return;
    const validKeys = new Set(sessions.map((session) => session.key));
    const active = (key: string) => validKeys.has(key) && !archivedPaneKeys.has(key);
    const missingPane = Object.values(workbenchState.tabs).some(({ paneKeys }) => !paneKeys.every(active));
    setIncludeArchived(sidebarState.view.show_archived || sessionSearchOpen || missingPane
      || Boolean(activeKey && !temporarySessions[activeKey] && !active(activeKey)));
    if (archivesLoaded) updateWorkbenchState(current => reconcileWorkbench(current, validKeys));
  }, [activeKey, archivedPaneKeys, archivesLoaded, sessionSearchOpen, sessions, sessionsLoaded, sidebarState.view.show_archived,
    sidebarStateLoading, temporarySessions, updateWorkbenchState, workbenchState]);

  useEffect(() => {
    if (loading) return;
    const pendingCreatedKey = pendingCreatedSessionKeyRef.current;
    if (pendingCreatedKey && sessions.some((session) => session.key === pendingCreatedKey)) {
      pendingCreatedSessionKeyRef.current = null;
    }
    if (!activeKey) return;
    const currentRoute = readShellRoute();
    if (temporarySessions[activeKey]) return;
    if (currentRoute.temporary) {
      navigate(currentRoute.view === "chat" ? defaultShellRoute() : {
        ...currentRoute, activeKey: null, temporary: false,
      }, { replace: true });
      return;
    }
    if (topicSessions.some((session) => session.key === activeKey)) return;
    // WebKit can commit the route before useSessions' optimistic insert.
    // Keep that just-created destination valid until the session list catches up.
    if (pendingCreatedKey === activeKey || !catalogLoaded) return;
    navigate(
      currentRoute.view === "chat"
        ? defaultShellRoute()
        : {
            ...currentRoute,
            activeKey: null,
          },
      { replace: true },
    );
  }, [activeKey, catalogLoaded, loading, navigate, sessions, temporarySessions, topicSessions]);

  useEffect(() => {
    return client.onSessionUpdate((chatId, scope, workspaceScope) => {
      if (scope === "thread") {
        setUpdatedChatIds((current) => {
          const next = new Set(current);
          if (activeChatIdRef.current === chatId) {
            next.delete(chatId);
          } else {
            next.add(chatId);
          }
          return next.size === current.size && next.has(chatId) === current.has(chatId)
            ? current
            : next;
        });
      }
      if (!workspaceScope) return;
      const next = normalizeWorkspaceScope(workspaceScope);
      setWorkspaceOverrides((current) => ({
        ...current,
        [chatId]: next,
      }));
      setDraftWorkspaceScope(next);
      setWorkspaceError(null);
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces]);

  useEffect(() => {
    return client.onError((error) => {
      if (error.kind !== "workspace_scope_rejected") return;
      if (error.chatId && error.chatId !== activeChatIdRef.current) return;
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
    }
  }, [client, loading, sessions]);

  const openHostSidebar = useCallback(() => {
    setHostSidebarOpen(true);
  }, [setHostSidebarOpen]);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isNativeHost =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isNativeHost) {
      setHostSidebarOpen(!hostSidebarOpen);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, [hostSidebarOpen, setHostSidebarOpen]);

  const applyWorkspaceScope = useCallback(
    (scope: WorkspaceScopePayload) => {
      const next = normalizeWorkspaceScope(scope);
      setWorkspaceError(null);
      if (activeChatId) {
        if (temporaryChatActive) {
          setTemporarySessions((current) => {
            if (!activeKey || !current[activeKey]) return current;
            return {
              ...current,
              [activeKey]: { ...current[activeKey], workspaceScope: next },
            };
          });
        } else if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, activeKey, client, temporaryChatActive],
  );

  const onCreateChat = useCallback(async (
    workspaceScope?: WorkspaceScopePayload | null,
    _initialMessage?: string,
    modelPreset?: string | null,
  ) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      const chatId = await createChat(scope, modelPreset);
      const key = `websocket:${chatId}`;
      pendingCreatedSessionKeyRef.current = key;
      navigate({
        view: "chat",
        activeKey: key,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
      return chatId;
    } catch (e) {
      if (e instanceof Error && e.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
        return null;
      }
      throw e;
    }
  }, [activeWorkspaceScope, createChat, navigate, t]);

  const onStartAutomationChat = useCallback(async (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
    modelPreset?: string | null,
  ) => {
    const chatId = await onCreateChat(
      options?.workspaceScope ?? activeWorkspaceScope,
      content,
      modelPreset,
    );
    if (!chatId) return false;
    setPendingAutomationMessage({
      id: crypto.randomUUID(),
      chatId,
      content,
      images,
      options,
    });
    return true;
  }, [activeWorkspaceScope, onCreateChat]);

  const onPendingAutomationMessageConsumed = useCallback((id: string) => {
    setPendingAutomationMessage((current) => current?.id === id ? null : current);
  }, []);

  const onCreateTemporaryChat = useCallback(
    async (
      workspaceScope?: WorkspaceScopePayload | null,
      initialMessage?: string,
      modelPreset?: string | null,
    ) => {
      const chatId = await client.newTemporaryChat();
      const confirmedPreset = modelPreset ? await switchModelPreset(client, chatId, modelPreset).catch((error: unknown) => {
        client.discardTemporaryChat(chatId);
        throw error;
      }) : null;
      const session = createTemporaryChatSession(chatId);
      const restrictedScope = workspaceScope
        ? normalizeWorkspaceScope(scopeWithAccessMode(workspaceScope, "restricted"))
        : null;
      const nextSession: ChatSummary = {
        ...session,
        preview: initialMessage ?? "",
        modelPreset: confirmedPreset,
        ...(restrictedScope ? { workspaceScope: restrictedScope } : {}),
      };
      setTemporarySessions((current) => ({
        ...current,
        [nextSession.key]: nextSession,
      }));
      setTemporaryChatEnabled(false);
      setWorkspaceError(null);
      setSessionSearchOpen(false);
      navigate({
        view: "chat",
        activeKey: nextSession.key,
        settingsSection: "overview",
        temporary: true,
      });
      setMobileSidebarOpen(false);
      return nextSession.chatId;
    },
    [client, navigate],
  );

  const onForkChat = useCallback(async (
    sourceChatId: string,
    beforeUserIndex: number,
  ) => {
    try {
      const sourceSession = sessions.find((session) => session.chatId === sourceChatId);
      const sourceTitle = sourceSession
        ? displayTitle(sourceSession, sidebarState.title_overrides, t("chat.newChat"))
        : t("chat.newChat");
      const chatId = await forkChat(
        sourceChatId,
        beforeUserIndex,
        t("chat.forkTitle", { title: sourceTitle }),
      );
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to fork chat", e);
      return null;
    }
  }, [forkChat, navigate, sessions, sidebarState.title_overrides, t]);

  const onNewChat = useCallback(() => {
    navigate(defaultShellRoute());
    setTemporaryChatEnabled(false);
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    setSessionSearchOpen(false);
    setMobileSidebarOpen(false);
  }, [navigate]);

  const onTemporaryChatEnabledChange = useCallback((enabled: boolean) => {
    if (view !== "chat" || activeKey) return;
    setTemporaryChatEnabled(enabled);
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
  }, [activeKey, view]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
      setTemporaryChatEnabled(false);
      navigate(defaultShellRoute());
      setDraftWorkspaceScope(normalizeWorkspaceScope({
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        access_mode: base.access_mode,
        restrict_to_workspace: base.access_mode === "restricted",
      }));
      setWorkspaceError(null);
      setMobileSidebarOpen(false);
    },
    [activeWorkspaceScope, navigate, onNewChat, workspaces?.default_scope],
  );

  const onSelectChat = useCallback(
    (key: string) => {
      if (deletingKeys.has(key)) return;
      const selectedTemporary = temporarySessionsRef.current[key];
      const selected = selectedTemporary
        ?? sessions.find((session) => session.key === key);
      const selectedChatId = selected?.chatId;
      if (selectedChatId) {
        setUpdatedChatIds((current) => {
          if (!current.has(selectedChatId)) return current;
          const next = new Set(current);
          next.delete(selectedChatId);
          return next;
        });
      }
      if (selected?.workspaceScope) {
        setDraftWorkspaceScope(normalizeWorkspaceScope(selected.workspaceScope));
      } else {
        setDraftWorkspaceScope(null);
      }
      setWorkspaceError(null);
      navigate({
        view: "chat",
        activeKey: key,
        settingsSection: "overview",
        ...(selectedTemporary ? { temporary: true } : {}),
      });
      setMobileSidebarOpen(false);
    },
    [deletingKeys, navigate, sessions],
  );

  const onCloseTemporaryChat = useCallback((key: string) => {
    const session = temporarySessionsRef.current[key];
    if (!session) return;
    const remaining = temporarySessionList.filter((item) => item.key !== key);
    const nextSessions = Object.fromEntries(remaining.map((item) => [item.key, item]));
    temporarySessionsRef.current = nextSessions;
    setTemporarySessions(nextSessions);
    client.discardTemporaryChat(session.chatId);
    if (activeKey === key) {
      if (remaining.length === 0) setDraftWorkspaceScope(null);
      setWorkspaceError(null);
      // Closing invalidates the source session immediately. Commit its replacement
      // in the same batch rather than leaving cleanup an invalid active route
      // while a view-transition capture is pending.
      navigate({
        view: "chat",
        activeKey: remaining[0]?.key ?? null,
        settingsSection: "overview",
        ...(remaining[0] ? { temporary: true } : {}),
      }, { replace: true, animate: false });
    }
    setMobileSidebarOpen(false);
  }, [activeKey, client, navigate, temporarySessionList]);

  const onTogglePin = useCallback((key: string) => {
    updateSidebarState(current => ({ ...current, pinned_keys: current.pinned_keys.includes(key)
      ? current.pinned_keys.filter(pin => pin !== key) : [...current.pinned_keys, key] }));
  }, [updateSidebarState]);

  const onRequestRenameTab = useCallback((key: string, label: string) => {
    setPendingTabRename({ key, label });
  }, []);

  const onConfirmTabRename = useCallback((title: string) => {
    if (!pendingTabRename) return;
    updateWorkbenchState((current) => (
      renameWorkbenchTab(current, pendingTabRename.key, title)
    ));
    setPendingTabRename(null);
  }, [pendingTabRename, updateWorkbenchState]);

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
    setPendingProjectRename({ key, label });
  }, []);

  const onConfirmProjectRename = useCallback(
    (title: string) => {
      if (!pendingProjectRename) return;
      const key = pendingProjectRename.key;
      setPendingProjectRename(null);
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

  const titleForSession = useCallback((session: ChatSummary) => (
    sidebarState.title_overrides[session.key]
    || session.title
    || deriveTitle(session.preview, t("chat.newChat"))
  ), [sidebarState.title_overrides, t]);

  const commitArchive = useCallback(async (keys: string[], archived: boolean, onSaved: () => void) => {
    for (const key of keys) archivePending.current.add(key);
    try {
      await client.archiveSessions(keys, archived);
    } catch {
      showToast({ message: t("toast.archiveFailed"), tone: "error", dedupeKey: "archive-failed" });
      return;
    } finally {
      for (const key of keys) archivePending.current.delete(key);
    }
    onSaved();
    void refresh();
  }, [client, refresh, showToast, t]);

  const onArchiveMany = useCallback(
    (keys: string[], archive: boolean) => {
      if (sidebarStateLoading) return;
      const candidates = new Set(keys);
      const selected = topicSessions.filter((session) => candidates.has(session.key)
        && session.projectLocked !== false && archivedPaneKeys.has(session.key) !== archive
        && !archivePending.current.has(session.key)
        && archiveUndoOwners.current.get(session.key)?.archived !== archive);
      if (!selected.length) return;
      const affected = selected.map((session) => session.key);
      const operation = Symbol();
      const owned = (key: string) => archiveUndoOwners.current.get(key)?.operation === operation;
      const release = () => { for (const key of affected) if (owned(key)) archiveUndoOwners.current.delete(key); };
      setMobileSidebarOpen(false);
      void commitArchive(affected, archive, () => {
        let pinOrder: string[] = [];
        updateSidebarState((current) => {
          const pinned = new Set(current.pinned_keys);
          const removed = new Set(affected.filter(key => pinned.delete(key)));
          if (removed.size) {
            // Keep anchors from earlier archives so either Undo order works.
            pinOrder = current.pinned_keys;
            for (const [key, previous] of archiveUndoOwners.current) {
              if (previous.pinOrder) pinOrder = restorePinOrder(pinOrder, previous.pinOrder, new Set([key]));
            }
          }
          for (const key of affected) archiveUndoOwners.current.set(key, {
            operation, archived: archive, observed: false, pinOrder: removed.has(key) ? pinOrder : undefined,
          });
          return removed.size ? { ...current, pinned_keys: [...pinned] } : current;
        });
        const undo = () => {
          const restoring = affected.filter(key => owned(key) && !archivePending.current.has(key));
          const pins = new Set(restoring.filter(key => archiveUndoOwners.current.get(key)?.pinOrder));
          if (!restoring.length) return release();
          void commitArchive(restoring, !archive, () => updateSidebarState(current => ({
            ...current, pinned_keys: archive ? restorePinOrder(current.pinned_keys, pinOrder, pins)
              : current.pinned_keys.filter(key => !restoring.includes(key)),
          }))).finally(release);
        };
        showToast({
          tone: "success",
          detail: selected.length === 1 ? titleForSession(selected[0]) : undefined,
          message: archive
            ? t(selected.length === 1 ? "toast.archivedSingle" : "toast.archived", { count: selected.length })
            : t(selected.length === 1 ? "toast.unarchivedSingle" : "toast.unarchived", { count: selected.length }),
          onExpire: release,
          action: { label: t("toast.undo"), run: undo },
        });
        const route = readShellRoute();
        const live = archiveNavigation.current;
        if (archive && live && route.view === "chat" && route.activeKey && affected.includes(route.activeKey)) {
          const next = live.topicSessions.find(({ key }) =>
            !archiveUndoOwners.current.get(key)?.archived && !live.archivedPaneKeys.has(key));
          navigate({ view: "chat", activeKey: next?.key ?? null, settingsSection: "overview" }, { animate: false });
        }
      });
    },
    [archivedPaneKeys, commitArchive, navigate, showToast, sidebarStateLoading, t, titleForSession, topicSessions, updateSidebarState],
  );

  const onToggleArchive = useCallback((key: string) => {
    onArchiveMany([key], !archivedPaneKeys.has(key));
  }, [onArchiveMany, archivedPaneKeys]);

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
    setMobileSidebarOpen(false);
    setSessionSearchOpen(true);
  }, []);

  const onAddPane = useCallback(async () => {
    const tabKey = activeTabKey;
    if (
      !tabKey
      || !activeKey
      || !activeSession
      || creatingPane
      || (activeTabState?.paneKeys.length ?? 0) >= MAX_WORKBENCH_PANES
      || temporarySessionsRef.current[activeKey]
    ) return;
    setMobileSidebarOpen(false);
    setSessionSearchOpen(false);
    setCreatingPane(true);
    try {
      const scope = activeWorkspaceScope;
      const chatId = await createChat(scope);
      const paneKey = `websocket:${chatId}`;
      pendingCreatedSessionKeyRef.current = paneKey;
      updateWorkbenchState((current) => addWorkbenchPane(current, activeKey, paneKey));
      navigate({
        view: "chat",
        activeKey: paneKey,
        settingsSection: "overview",
      }, { animate: false });
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
    } catch (error) {
      console.error("Failed to create pane", error);
      if (error instanceof Error && error.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      }
    } finally {
      setCreatingPane(false);
    }
  }, [
    activeKey,
    activeSession,
    activeTabKey,
    activeTabState,
    activeWorkspaceScope,
    createChat,
    creatingPane,
    navigate,
    t,
    updateWorkbenchState,
  ]);

  const onSelectSearchResult = useCallback(
    (key: string) => {
      setSessionSearchOpen(false);
      onSelectChat(key);
    },
    [onSelectChat],
  );

  const onOpenSettings = useCallback((section: SettingsSectionKey = "overview") => {
    setSessionSearchOpen(false);
    navigate({ view: shellViewForSettingsSection(section), activeKey, settingsSection: section });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onSettingsIntent = useCallback(() => {
    void loadSettingsView();
  }, []);

  const onOpenModelSettings = useCallback(() => {
    onOpenSettings("models");
  }, [onOpenSettings]);
  const onInspectImagePreset = useCallback((name: string) => {
    setSessionSearchOpen(false);
    navigate({ view: "settings", activeKey, settingsSection: "models", settingsFocus: `image-input:${name}` });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);
  const onOpenSandboxSettings = useCallback((target: SettingsFocusTarget) => {
    setSessionSearchOpen(false);
    navigate({ view: "settings", activeKey, settingsSection: "advanced", settingsFocus: target });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenApps = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "apps", activeKey, settingsSection: "apps" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenAutomations = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "automations", activeKey, settingsSection: "automations" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  useEffect(() => {
    const actions = { newChat: onNewChat, search: onOpenSessionSearch, apps: onOpenApps,
      automations: onOpenAutomations, settings: () => onOpenSettings() };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (!localActive) return;
      const action = matchSidebarShortcut(event);
      if (!action) return;
      event.preventDefault();
      actions[action]();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [localActive, onNewChat, onOpenSessionSearch, onOpenApps, onOpenAutomations, onOpenSettings]);

  const onSettingsSectionChange = useCallback(
    (section: SettingsSectionKey) => {
      const route = { view: shellViewForSettingsSection(section), activeKey, settingsSection: section };
      // The page has completed or retained its outgoing drafts for in-page transitions.
      if (currentShellRouteRef.current.view === route.view) commitNavigation(route);
      else navigate(route);
    },
    [activeKey, commitNavigation, navigate],
  );

  const onBackToChat = useCallback(() => {
    setMobileSidebarOpen(false);
    const nextKey = (() => {
      if (!activeKey) return null;
      if (temporarySessionsRef.current[activeKey]) return activeKey;
      if (topicSessions.some((session) => session.key === activeKey)) return activeKey;
      return null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      temporary: Boolean(nextKey && temporarySessionsRef.current[nextKey]),
      settingsSection: "overview",
    });
  }, [activeKey, navigate, topicSessions]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    restartStartedAtRef.current = Date.now();
    setIsRestarting(true);
    rememberRestartRoute();
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(restartStartedAtRef.current));
    } catch {
      // ignore storage errors
    }
    void client.sendSystemCommand(chatId, "/restart").catch(() => {});
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onRunStatus((chatId, state) => {
      if (state.active) {
        const nextRunning = new Set(runningChatIdsRef.current);
        nextRunning.add(chatId);
        runningChatIdsRef.current = nextRunning;
        setRunningChatIds(nextRunning);
        setUpdatedChatIds((current) => {
          if (!current.has(chatId)) return current;
          const next = new Set(current);
          next.delete(chatId);
          return next;
        });
        return;
      }

      if (!runningChatIdsRef.current.has(chatId)) return;
      const nextRunning = new Set(runningChatIdsRef.current);
      nextRunning.delete(chatId);
      runningChatIdsRef.current = nextRunning;
      setRunningChatIds(nextRunning);
      if (
        Object.values(temporarySessionsRef.current).some(
          (session) => session.chatId === chatId,
        )
      ) return;
      setUpdatedChatIds((current) => {
        const next = new Set(current);
        if (activeChatIdRef.current === chatId) {
          next.delete(chatId);
        } else {
          next.add(chatId);
        }
        return next;
      });
    });
  }, [client]);

  useEffect(() => {
    let wasOpen = client.status === "open";
    return client.onStatus((status) => {
      if (status === "open") {
        wasOpen = true;
        return;
      }
      if (!wasOpen) return;
      wasOpen = false;
      filePreviewStore.clear();
      if (Object.keys(temporarySessionsRef.current).length === 0) return;
      temporarySessionsRef.current = {};
      setTemporarySessions({});
      if (readShellRoute().temporary) {
        navigate(defaultShellRoute(), { replace: true });
      }
    });
  }, [client, navigate, filePreviewStore]);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const refreshSettings = (generation: number, attempt = 0): void => {
      void fetchSettings(getToken(), "", client)
        .then((payload) => {
          if (!cancelled && generation === settingsRefreshGenerationRef.current) {
            setSettingsSnapshot(payload);
          }
        })
        .catch(() => {
          if (cancelled || generation !== settingsRefreshGenerationRef.current || attempt >= 3) return;
          retryTimer = window.setTimeout(() => refreshSettings(generation, attempt + 1), 250);
        });
    };
    const unsubscribe = client.onStatus((status) => {
      // Another tab can consume the reload marker before this tab reconnects.
      const startedAt = restartStartedAtRef.current || (() => {
        try {
          return Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
        } catch {
          return 0;
        }
      })();
      if (!startedAt) return;
      if (status !== "open") {
        restartStartedAtRef.current = startedAt;
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
        window.localStorage.removeItem(RESTART_ROUTE_KEY);
      } catch {
        // ignore storage errors
      }
      const refreshGeneration = ++settingsRefreshGenerationRef.current;
      restartStartedAtRef.current = 0;
      setIsRestarting(false);
      showToast({ message: t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }), tone: "success", dedupeKey: "restart-completed" });
      refreshSettings(refreshGeneration);
    });
    return () => {
      cancelled = true;
      unsubscribe();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [client, getToken, showToast, t]);

  const onTurnEnd = useDeferredTitleRefresh(
    temporaryChatActive ? null : activePaneSession,
    refresh,
  );

  const deleteContextRef = useRef({ topicSessions, activeKey, activeTabState, view });
  deleteContextRef.current = { topicSessions, activeKey, activeTabState, view };
  const checkingDeleteKeysRef = useRef<Set<string>>(new Set());
  const showAutomationConfirmRef = useRef<(
    items: SidebarDeleteItem[],
    jobsByKey: ReadonlyMap<string, SessionAutomationJob[]>,
  ) => void>(() => {});

  const prepareStagedDelete = useCallback((
    requested: SidebarDeleteItem[],
    automationKeys?: ReadonlySet<string>,
  ): ToastNotice | null => {
    const {
      topicSessions: liveSessions,
      activeKey: currentActiveKey,
      activeTabState: currentActiveTabState,
      view: currentView,
    } = deleteContextRef.current;
    const items = requested.filter((item) => liveSessions.some((session) => session.key === item.key));
    if (!items.length) return null;
    const batchKeys = new Set(items.map((item) => item.key));
    setDeletingKeys((current) => new Set([...current, ...batchKeys]));
    closeMobileSidebar();

    if (currentView === "chat" && currentActiveKey && batchKeys.has(currentActiveKey)) {
      const currentIndex = liveSessions.findIndex((session) => session.key === currentActiveKey);
      const available = new Set(liveSessions.filter((session) => !batchKeys.has(session.key)).map((session) => session.key));
      const fallbackKey = currentActiveTabState?.paneKeys.find((key) => available.has(key))
        ?? liveSessions.slice(currentIndex + 1).find((session) => available.has(session.key))?.key
        ?? liveSessions.slice(0, Math.max(0, currentIndex)).reverse().find((session) => available.has(session.key))?.key
        ?? null;
      navigate({ view: "chat", activeKey: fallbackKey, settingsSection: "overview" }, { replace: true });
    }

    const reveal = () => setDeletingKeys((current) => new Set([...current].filter((key) => !batchKeys.has(key))));
    const commit = async () => {
      let failed = 0;
      const blockedItems: SidebarDeleteItem[] = [];
      const blockedJobsByKey = new Map<string, SessionAutomationJob[]>();
      try {
        for (const item of items) {
          try {
            const result = await deleteChat(
              item.key,
              automationKeys?.has(item.key) ? { deleteAutomations: true } : undefined,
            );
            if (result.deleted) {
              filePreviewStore.delete(item.key);
              draftStore.delete(item.key);
            } else if (result.blocked_by_automations && result.automations?.length) {
              blockedItems.push(item);
              blockedJobsByKey.set(item.key, result.automations);
            } else {
              failed++;
            }
          } catch (error) {
            console.error("Failed to delete session", error);
            failed++;
          }
        }
      } finally {
        reveal();
      }
      if (blockedItems.length) {
        showAutomationConfirmRef.current(blockedItems, blockedJobsByKey);
      }
      if (failed) showToast({
        message: t(failed === 1 ? "toast.deleteFailedSingle" : "toast.deleteFailed", { count: failed }),
        tone: "error",
      });
    };
    return {
      message: t(items.length === 1 ? "toast.pendingDeleteSingle" : "toast.pendingDelete", { count: items.length }),
      detail: items.length === 1 ? items[0].label : undefined,
      tone: "pending",
      action: { label: t("toast.undo"), run: reveal },
      onExpire: () => { void commit(); },
    };
  }, [closeMobileSidebar, deleteChat, draftStore, filePreviewStore, navigate, showToast, t]);

  const buildAutomationDeleteConfirmNotice = useCallback((
    items: SidebarDeleteItem[],
    jobsByKey: ReadonlyMap<string, SessionAutomationJob[]>,
  ): ToastNotice => {
    const groups: AutomationDeleteSessionGroup[] = items.flatMap((item) => {
      const jobs = jobsByKey.get(item.key);
      return jobs?.length ? [{ item, jobs }] : [];
    });
    const automationKeys = new Set(groups.map((group) => group.item.key));
    const totalAutomations = groups.reduce((sum, group) => sum + group.jobs.length, 0);
    const detailsLabel = totalAutomations === 1
      ? t("toast.automationCountSingle")
      : t("toast.automationCount", { count: totalAutomations });
    return {
      message: items.length === 1
        ? t("toast.confirmDeleteAutomationsSingle")
        : t("toast.confirmDeleteAutomations", { count: items.length }),
      tone: "pending",
      persistent: true,
      dedupeKey: `delete-confirm:${items.map((item) => item.key).sort().join(",")}`,
      details: {
        label: detailsLabel,
        render: (controller) => (
          <AutomationDeleteToastDetails
            groups={groups}
            onExcludeSession={(excludedKey) => {
              const remainingItems = items.filter((item) => item.key !== excludedKey);
              if (!remainingItems.length) {
                controller.dismiss();
                return;
              }
              const nextJobsByKey = new Map(
                Array.from(jobsByKey.entries()).filter(([key]) => key !== excludedKey),
              );
              const stillHasAutomations = remainingItems.some(
                (item) => (nextJobsByKey.get(item.key)?.length ?? 0) > 0,
              );
              if (stillHasAutomations) {
                controller.update(buildAutomationDeleteConfirmNotice(remainingItems, nextJobsByKey));
                return;
              }
              const staged = prepareStagedDelete(remainingItems);
              if (staged) controller.update(staged);
              else controller.dismiss();
            }}
          />
        ),
      },
      secondaryAction: { label: t("common.cancel") },
      action: {
        label: t("chat.delete"),
        tone: "destructive",
        run: () => prepareStagedDelete(items, automationKeys) ?? undefined,
      },
    };
  }, [prepareStagedDelete, t]);

  const showAutomationDeleteConfirmToast = useCallback((
    items: SidebarDeleteItem[],
    jobsByKey: ReadonlyMap<string, SessionAutomationJob[]>,
  ) => {
    closeMobileSidebar();
    showToast(buildAutomationDeleteConfirmNotice(items, jobsByKey));
  }, [buildAutomationDeleteConfirmNotice, closeMobileSidebar, showToast]);
  showAutomationConfirmRef.current = showAutomationDeleteConfirmToast;

  const onRequestDeleteMany = useCallback(async (requested: SidebarDeleteItem[]) => {
    const liveKeys = new Set(deleteContextRef.current.topicSessions.map((session) => session.key));
    const uniqueItems = Array.from(new Map(
      requested
        .filter((item) => liveKeys.has(item.key) && !checkingDeleteKeysRef.current.has(item.key))
        .map((item) => [item.key, item]),
    ).values());
    if (!uniqueItems.length) return;
    for (const item of uniqueItems) checkingDeleteKeysRef.current.add(item.key);
    const jobsByKey = new Map<string, SessionAutomationJob[]>();
    try {
      const results = await Promise.allSettled(
        uniqueItems.map((item) => getSessionAutomations(item.key)),
      );
      results.forEach((result, index) => {
        if (result.status === "fulfilled" && result.value.length) {
          jobsByKey.set(uniqueItems[index].key, result.value);
        }
      });
    } finally {
      for (const item of uniqueItems) checkingDeleteKeysRef.current.delete(item.key);
    }
    const stillLiveKeys = new Set(deleteContextRef.current.topicSessions.map((session) => session.key));
    const items = uniqueItems.filter((item) => stillLiveKeys.has(item.key));
    if (!items.length) return;
    const liveJobsByKey = new Map(
      items.flatMap((item) => {
        const jobs = jobsByKey.get(item.key);
        return jobs?.length ? [[item.key, jobs] as const] : [];
      }),
    );
    if (liveJobsByKey.size > 0) {
      showAutomationDeleteConfirmToast(items, liveJobsByKey);
      return;
    }
    const notice = prepareStagedDelete(items);
    if (notice) showToast(notice);
  }, [getSessionAutomations, prepareStagedDelete, showAutomationDeleteConfirmToast, showToast]);

  const onRequestDelete = useCallback((key: string, label: string) => {
    void onRequestDeleteMany([{ key, label }]);
  }, [onRequestDeleteMany]);

  const automaticSidebarSort = sidebarState.view.sort === "manual"
    ? "updated_desc"
    : sidebarState.view.sort;
  const orderedWorkbenchTabs = useMemo(() => {
    const orderedSessions = sortSessions(
      topicSessions,
      automaticSidebarSort,
      sidebarState.title_overrides,
      sidebarState.session_order,
    );
    const updatedAtByKey = new Map(topicSessions.map((session) => [
      session.key,
      session.updatedAt ?? session.createdAt,
    ]));
    return orderWorkbenchTabs(
      workbenchState,
      orderedSessions.map((session) => session.key),
      updatedAtByKey,
    );
  }, [
    automaticSidebarSort,
    topicSessions,
    sidebarState.session_order,
    sidebarState.title_overrides,
    workbenchState,
  ]);
  const orderedWorkbenchTabsByKey = useMemo(
    () => new Map(orderedWorkbenchTabs.map((tab) => [tab.tabKey, tab])),
    [orderedWorkbenchTabs],
  );
  const sidebarTabPresentations = useMemo(() => {
    const sessionsByKey = new Map(topicSessions.map((session) => [session.key, session]));
    return orderedWorkbenchTabs.flatMap((tab) => {
      const anchorKey = tab.tab.paneKeys.find((key) => sessionsByKey.has(key))
        ?? tab.paneKeys[0];
      const anchor = sessionsByKey.get(anchorKey);
      if (!anchor) return [];
      const title = tab.tab.title ?? titleForSession(anchor);
      const visible = tab.tab.explicit || tab.paneKeys.length > 1;
      const rowKey = visible ? tab.tabKey : tab.paneKeys[0];
      return [{
        orderedTab: tab,
        rowKey,
        title,
        session: visible
          ? {
              ...anchor,
              key: tab.tabKey,
              chatId: `workbench-tab:${tab.tabKey}`,
              title,
              preview: "",
              updatedAt: tab.updatedAt,
            }
          : anchor,
      }];
    });
  }, [orderedWorkbenchTabs, topicSessions, titleForSession]);
  const sidebarTopicSessions = useMemo(
    () => sidebarTabPresentations.map((presentation) => presentation.session),
    [sidebarTabPresentations],
  );

  const headerTitle = temporaryChatActive
    ? deriveTemporaryChatTitle(activeSession?.preview, t("temporaryChat.title"))
    : activeSession
    ? titleForSession(activeSession)
    : t("app.brand");
  const workbenchPaneSessions = useMemo(() => {
    if (!activeTabState) return [];
    const byKey = new Map(topicSessions.map((session) => [session.key, session]));
    const sortedPaneKeys = activeTabKey
      ? orderedWorkbenchTabsByKey.get(activeTabKey)?.paneKeys ?? activeTabState.paneKeys
      : activeTabState.paneKeys;
    const paneKeys = [
      ...activeTabState.layoutPaneKeys.filter((key) => byKey.has(key)),
      ...sortedPaneKeys.filter((key) => !activeTabState.layoutPaneKeys.includes(key)),
    ];
    return paneKeys
      .map((key) => byKey.get(key))
      .filter((session): session is ChatSummary => session !== undefined);
  }, [activeTabKey, activeTabState, orderedWorkbenchTabsByKey, topicSessions]);
  const paneChromeEnabled = Boolean(
    activeKey && activeSession && !temporaryChatActive && activeTabState,
  );
  const activeTabVisible = Boolean(
    activeTabState
    && (activeTabState.explicit || activeTabState.paneKeys.length > 1),
  );
  const renderedWorkbenchPanes = useMemo(() => {
    if (paneChromeEnabled) {
      return workbenchPaneSessions.map((session) => ({
        key: session.key,
        reactKey: session.key === activeTabState?.paneKeys[0]
          ? "tab-root"
          : `pane:${session.key}`,
        title: titleForSession(session),
      }));
    }
    return [{
      key: activeKey ?? "new-topic",
      reactKey: "tab-root",
      title: headerTitle,
    }];
  }, [
    activeKey,
    activeTabState?.paneKeys,
    headerTitle,
    paneChromeEnabled,
    titleForSession,
    workbenchPaneSessions,
  ]);
  const renderedActivePaneKey = activeKey ?? renderedWorkbenchPanes[0].key;
  const renderedWorkbenchLayout = paneChromeEnabled && activeTabState
    ? activeTabState.layout
    : "columns";
  const renderedWorkbenchSplitRatios = paneChromeEnabled && activeTabState
    ? activeTabState.splitRatios
    : [];
  const sidebarPaneGroups = useMemo(() => {
    const sessionsByKey = new Map(sessions.map((session) => [session.key, session]));
    return Object.fromEntries(sidebarTabPresentations.map((presentation) => {
      const orderedTab = presentation.orderedTab;
      const panes = orderedTab.paneKeys
        .map((key) => sessionsByKey.get(key))
        .filter((session): session is ChatSummary => session !== undefined)
        .map((session) => ({
          key: session.key,
          chatId: session.chatId,
          title: titleForSession(session),
          handle: session.handle,
          projectLocked: session.projectLocked !== false,
        }));
      return [presentation.rowKey, {
        tabKey: orderedTab.tabKey,
        title: presentation.title,
        activePaneKey: activeKey && orderedTab.paneKeys.includes(activeKey)
          ? activeKey
          : orderedTab.paneKeys[0],
        visible: orderedTab.tab.explicit || orderedTab.paneKeys.length > 1,
        panes,
      }];
    }));
  }, [
    activeKey,
    sessions,
    sidebarTabPresentations,
    titleForSession,
  ]);
  const activePaneLimitReached = Boolean(
    activeTabState && activeTabState.paneKeys.length >= MAX_WORKBENCH_PANES,
  );

  const onActivateWorkbenchPane = useCallback((paneKey: string) => {
    onSelectChat(paneKey);
  }, [onSelectChat]);

  const onSelectSidebarTab = useCallback((tabKey: string) => {
    const tab = workbenchTab(workbenchState, tabKey);
    if (!tab) return;
    const visiblePaneKeys = tab.paneKeys.filter((key) => !deletingKeys.has(key));
    const rememberedPaneKey = lastActivePaneByTabRef.current.get(tabKey);
    const paneKey = rememberedPaneKey && visiblePaneKeys.includes(rememberedPaneKey)
      ? rememberedPaneKey
      : visiblePaneKeys[0];
    if (paneKey) onSelectChat(paneKey);
  }, [deletingKeys, onSelectChat, workbenchState]);

  const onSelectSidebarItem = useCallback((key: string) => {
    if (
      temporarySessionsRef.current[key]
      || sessions.some((session) => session.key === key)
    ) {
      onSelectChat(key);
      return;
    }
    onSelectSidebarTab(key);
  }, [onSelectChat, onSelectSidebarTab, sessions]);

  const onSelectSidebarPane = useCallback((_tabKey: string, paneKey: string) => {
    onSelectChat(paneKey);
  }, [onSelectChat]);

  const onDetachWorkbenchPane = useCallback((tabKey: string, paneKey: string) => {
    updateWorkbenchState((current) => detachWorkbenchPane(current, tabKey, paneKey));
  }, [updateWorkbenchState]);

  const onCreateWorkbenchTab = useCallback((paneKey: string) => {
    updateWorkbenchState((current) => createWorkbenchTab(current, paneKey));
  }, [updateWorkbenchState]);

  const onDissolveWorkbenchTab = useCallback((tabKey: string) => {
    updateWorkbenchState((current) => dissolveWorkbenchTab(current, tabKey));
  }, [updateWorkbenchState]);

  const onAttachWorkbenchPane = useCallback((
    paneKey: string,
    tabKey: string,
  ) => {
    updateWorkbenchState((current) => {
      const target = workbenchTab(current, tabKey);
      if (
        !target
        || (!target.explicit && target.paneKeys.length < 2)
        || (!target.paneKeys.includes(paneKey) && target.paneKeys.length >= MAX_WORKBENCH_PANES)
      ) return current;
      return attachWorkbenchPane(current, tabKey, paneKey);
    });
  }, [updateWorkbenchState]);

  useEffect(() => {
    if (!localActive) return;
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
    if (view === "automations") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.automations", { defaultValue: "Automations" }),
      });
      return;
    }
    if (view === "remote") {
      document.title = t("app.documentTitle.chat", { title: t("remote.title") });
      return;
    }
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [localActive, activeSession, headerTitle, i18n.resolvedLanguage, t, view]);

  // List and preference events can arrive separately in another window.
  // A stale pin must never promote an archived pane, including in mixed tabs.
  const visiblePins = useMemo(() => sidebarState.pinned_keys.filter((key) => !archivedPaneKeys.has(key)),
    [archivedPaneKeys, sidebarState.pinned_keys]);
  const pinnedPaneKeys = useMemo(() => new Set(visiblePins), [visiblePins]);
  const sidebarPinnedTabKeys = useMemo(() => sidebarTabPresentations
    .filter(({ orderedTab }) => orderedTab.paneKeys.some((key) => pinnedPaneKeys.has(key)))
    .map(({ rowKey }) => rowKey), [pinnedPaneKeys, sidebarTabPresentations]);
  const sidebarArchivedTabKeys = useMemo(() => sidebarTabPresentations
    .filter(({ orderedTab }) => orderedTab.paneKeys.every((key) => archivedPaneKeys.has(key)))
    .map(({ rowKey }) => rowKey), [archivedPaneKeys, sidebarTabPresentations]);
  const activeSidebarKey = activeTabKey
    ? sidebarTabPresentations.find(({ orderedTab }) => (
        orderedTab.tabKey === activeTabKey
      ))?.rowKey ?? activeKey
    : activeKey;

  const sidebarProps = {
    sessions: sidebarStateLoading ? [] : sidebarTopicSessions,
    temporarySessions: sidebarStateLoading ? [] : temporarySessionList,
    activeKey: !managingConnections && view === "chat"
      ? (temporaryChatActive ? activeKey : activeSidebarKey)
      : null,
    loading: loading || sidebarStateLoading,
    initialLoading: sessionsInitialLoading || sidebarStateLoading,
    onNewChat,
    onSelect: onSelectSidebarItem,
    onCloseTemporaryChat,
    onRequestDelete,
    onRequestDeleteMany: (items: SidebarDeleteItem[]) => { void onRequestDeleteMany(items); },
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onArchiveMany,
    onRequestRenameTab,
    paneGroups: sidebarPaneGroups,
    onSelectPane: onSelectSidebarPane,
    onCreateTab: mobileWorkbench ? undefined : onCreateWorkbenchTab,
    onDetachPane: mobileWorkbench ? undefined : onDetachWorkbenchPane,
    onDissolveTab: mobileWorkbench ? undefined : onDissolveWorkbenchTab,
    onAttachPane: mobileWorkbench ? undefined : onAttachWorkbenchPane,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenSettings,
    onOpenUpdates: () => onOpenSettings("about"),
    availableUpdate: localActive && !isNativeRuntime(effectiveRuntimeSurface)
      && versionCheck.result?.type === "update" && versionCheck.result.latestVersion !== versionCheck.dismissedVersion
      ? { version: versionCheck.result.latestVersion, onDismiss: versionCheck.dismiss, onRequestUpdate: updateFlow.open,
        installationMethod: updateFlow.pending ? null : versionCheck.installationMethod }
      : undefined,
    onOpenApps,
    onOpenAutomations,
    onSettingsIntent,
    onOpenSearch: onOpenSessionSearch,
    activeUtility: !managingConnections && (view === "apps" || view === "automations") ? view : null,
    onToggleArchived,
    pinnedKeys: sidebarPinnedTabKeys,
    archivedKeys: sidebarArchivedTabKeys,
    pinnedPaneKeys: visiblePins,
    archivedPaneKeys: archivedKeys,
    sessionOrder: sidebarState.session_order,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    updatedChatIds: updatedChatIdList,
    recoveryChatIds: recoveryChatIdList,
    viewState: { ...sidebarState.view, sort: automaticSidebarSort },
    showArchived: sidebarState.view.show_archived,
    defaultWorkspacePath: workspaces?.default_scope.project_path ?? null,
  };
  const hostSidebarFlowWidth = hostSidebarOpen ? sidebarWidth : SIDEBAR_RAIL_WIDTH;

  useEffect(() => {
    document.documentElement.classList.toggle("native-host", showHostChrome);
    return () => {
      document.documentElement.classList.remove("native-host");
    };
  }, [showHostChrome]);

  return (
    <ThemeProvider theme={theme}>
      <StarPrompt ready={localActive && !managingConnections && !loading && !sidebarStateLoading} />
      <div
        className={cn(
          "relative h-full w-full overflow-hidden",
          showHostChrome && "host-window-shell",
        )}
      >
        {showHostChrome ? (
          <HostChrome
            rightAction={
              view === "chat" ? undefined : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("thread.header.toggleTheme")}
                  onClick={toggle}
                  className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
                >
                  <ThemeToggleIcon theme={theme} />
                </Button>
              )
            }
          />
        ) : null}
        <div
          className={cn(
            "relative flex h-full w-full overflow-hidden",
          )}
        >
          {showMainSidebar ? (
            <aside
              data-testid="host-sidebar-flow"
              data-resizing={sidebarDragging || undefined}
              data-collapsed={!hostSidebarOpen || undefined}
              id="main-sidebar"
              className={cn(
                "sidebar-dock-frame group/sidebar relative z-20 hidden shrink-0 overflow-hidden bg-background lg:block",
                sidebarDragging && "select-none",
              )}
              data-theme-surface
              style={{
                width: hostSidebarFlowWidth,
                "--sidebar-open-width": `${sidebarWidth}px`,
              } as CSSProperties}
            >
              <div
                aria-hidden
                data-theme-surface
                className={cn(
                  "sidebar-dock-surface pointer-events-none absolute inset-0",
                  showHostChrome ? "host-sidebar-glass" : "bg-sidebar",
                )}
              />
              <div className="absolute inset-0">
                <Sidebar
                  {...sidebarProps}
                  collapsed={!hostSidebarOpen}
                  hostChromeInset={showHostChrome}
                  onExpand={openHostSidebar}
                  onCollapse={() => setHostSidebarOpen(false)}
                  desktopDock
                />
              </div>
              <SidebarResizeHandle
                width={sidebarWidth}
                open={hostSidebarOpen}
                onDraggingChange={setSidebarDragging}
                onResize={(width, open) => {
                  if (open) setSidebarWidth(width);
                  setHostSidebarOpen(open);
                }}
              />
            </aside>
          ) : null}

          {showMainSidebar ? (
            <Sheet
              open={mobileSidebarOpen}
              onOpenChange={(open) => setMobileSidebarOpen(open)}
            >
              <SheetContent
                ref={mobileSidebarRef}
                onEscapeKeyDown={(event) => {
                  if (event.target instanceof Element
                    && event.target.closest("[data-sidebar-topic-rename]")) {
                    event.preventDefault();
                  }
                }}
                onOpenAutoFocus={(event) => {
                  // Keep opening navigation from focusing the search tooltip trigger.
                  event.preventDefault();
                  mobileSidebarRef.current?.focus({ preventScroll: true });
                }}
                side={localeDirection(i18n.language) === "rtl" ? "right" : "left"}
                showCloseButton={false}
                aria-describedby={undefined}
                className="p-0 lg:hidden"
                style={{ width: MOBILE_SIDEBAR_WIDTH, maxWidth: MOBILE_SIDEBAR_WIDTH }}
              >
                <SheetTitle className="sr-only">{t("sidebar.navigation")}</SheetTitle>
                <Sidebar
                  {...sidebarProps}
                  onCollapse={closeMobileSidebar}
                  containActionMenus
                />
              </SheetContent>
            </Sheet>
          ) : null}

          {sessionSearchOpen ? (
            <Suspense fallback={null}>
              <SessionSearchDialog
                open
                onOpenChange={setSessionSearchOpen}
                sessions={topicSessions}
                activeKey={activeKey}
                loading={loading}
                titleOverrides={sidebarState.title_overrides}
                messageCache={threadMessageCache}
                onSelect={onSelectSearchResult}
              />
            </Suspense>
          ) : null}
        <main ref={managementMain}
          data-theme-surface
          aria-hidden={managingConnections && remoteConnections?.embeddedManagement || undefined}
          {...(managingConnections && remoteConnections?.embeddedManagement ? { inert: "" } : {})}
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
          )}
        >
          <div className={cn("absolute inset-0 flex flex-col", managingConnections && "hidden")}
            aria-hidden={managingConnections || undefined} {...(managingConnections ? { inert: "" } : {})}>
            {(view === "chat" || chatVisited) && <div
              className={cn(
                "absolute inset-0 flex flex-col",
                view !== "chat" && "hidden",
              )}
            >
              <ThreadVisibilityContext.Provider value={localActive && !managingConnections && view === "chat"}>
                <Suspense fallback={<StartupShell embedded surface="chat" sidebarExpanded={hostSidebarOpen} />}>
                  <PaneWorkbench
                    panes={renderedWorkbenchPanes}
                    activePaneKey={renderedActivePaneKey}
                    layout={renderedWorkbenchLayout}
                    splitRatios={renderedWorkbenchSplitRatios}
                    chrome={paneChromeEnabled}
                    showLayoutControl={activeTabVisible}
                    addPaneDisabled={creatingPane || activePaneLimitReached}
                    addPaneDisabledLabel={activePaneLimitReached
                      ? t("workbench.paneLimit", {
                          count: MAX_WORKBENCH_PANES,
                        })
                      : undefined}
                    onActivatePane={onActivateWorkbenchPane}
                    onAddPane={onAddPane}
                    onLayoutChange={(layout) => {
                      if (!activeTabKey) return;
                      updateWorkbenchState((current) => (
                        setWorkbenchLayout(current, activeTabKey, layout)
                      ));
                    }}
                    onPaneOrderChange={(paneKeys) => {
                      if (!activeTabKey) return;
                      updateWorkbenchState((current) => (
                        setWorkbenchPaneLayoutOrder(current, activeTabKey, paneKeys)
                      ));
                    }}
                    onSplitRatiosChange={(splitRatios) => {
                      if (!activeTabKey) return;
                      updateWorkbenchState((current) => (
                        setWorkbenchSplitRatios(current, activeTabKey, splitRatios)
                      ));
                    }}
                    renderPane={(pane, context) => {
                      if (!paneChromeEnabled) {
                        return (
                          <ThreadShell
                            session={activeSession}
                            sessions={topicSessions}
                            titleOverrides={sidebarState.title_overrides}
                            title={headerTitle}
                            temporary={temporaryChatRequested}
                            temporaryChatIds={temporaryChatIds}
                            messageCache={threadMessageCache}
                            filePreviewStore={filePreviewStore}
                            draftStore={draftStore}
                            temporaryChatEnabled={temporaryChatEnabled}
                            onTemporaryChatEnabledChange={
                              !activeKey ? onTemporaryChatEnabledChange : undefined
                            }
                            onToggleSidebar={toggleSidebar}
                            onCreateChat={
                              temporaryChatEnabled ? onCreateTemporaryChat : onCreateChat
                            }
                            pendingFirstMessage={pendingAutomationMessage}
                            onPendingFirstMessageConsumed={onPendingAutomationMessageConsumed}
                            onForkChat={temporaryChatActive ? undefined : onForkChat}
                            onTurnEnd={onTurnEnd}
                            theme={theme}
                            onToggleTheme={toggle}
                            hideSidebarToggleForHostChrome
                            hideHeader={false}
                            workspaceScope={activeWorkspaceScope}
                            workspaceDefaultScope={workspaces?.default_scope ?? null}
                            workspaceControls={workspaces?.controls ?? null}
                            workspaceScopeDisabled={activeChatRunning}
                            workspaceError={workspaceError}
                            onWorkspaceScopeChange={applyWorkspaceScope}
                            settingsSnapshot={settingsSnapshot}
                            settingsLoading={settingsLoading}
                            onOpenModelSettings={onOpenModelSettings}
                            onInspectImagePreset={onInspectImagePreset}
                            onOpenSandboxSettings={onOpenSandboxSettings}
                            skills={skills}
                          />
                        );
                      }

                      const paneSession = workbenchPaneSessions.find(
                        (session) => session.key === pane.key,
                      );
                      if (!paneSession) return null;
                      const paneScope = workspaceOverrides[paneSession.chatId]
                        ?? paneSession.workspaceScope
                        ?? workspaces?.default_scope
                        ?? null;
                      const paneRunning = runningChatIds.has(paneSession.chatId);
                      return (
                        <ThreadShell
                          session={paneSession}
                          sessions={topicSessions}
                          titleOverrides={sidebarState.title_overrides}
                          title={pane.title}
                          temporaryChatIds={temporaryChatIds}
                          messageCache={threadMessageCache}
                          filePreviewStore={filePreviewStore}
                          draftStore={draftStore}
                          onToggleSidebar={toggleSidebar}
                          onCreateChat={onCreateChat}
                          pendingFirstMessage={pendingAutomationMessage}
                          onPendingFirstMessageConsumed={onPendingAutomationMessageConsumed}
                          onForkChat={onForkChat}
                          onTurnEnd={context.active ? onTurnEnd : () => void refresh()}
                          theme={theme}
                          onToggleTheme={toggle}
                          hideSidebarToggle={!context.active}
                          hideSidebarToggleForHostChrome={context.active}
                          hideThemeButton={!context.active}
                          hideHeaderTitle
                          inlineHandle={!mobileWorkbench && workbenchPaneSessions.length > 1}
                          headerActions={context.headerActions}
                          headerPortalTarget={context.headerPortalTarget}
                          headerActive={context.active}
                          composerPortalTarget={context.composerPortalTarget}
                          navigationFrame={context.navigationFrame}
                          composerActive={context.active}
                          multiplePanes={context.multiplePanes}
                          composerInputAriaLabel={t("workbench.composerAria", {
                            title: pane.title,
                          })}
                          emptyComposerVariant="thread"
                          workspaceScope={paneScope}
                          workspaceDefaultScope={workspaces?.default_scope ?? null}
                          workspaceControls={workspaces?.controls ?? null}
                          workspaceScopeDisabled={paneRunning}
                          workspaceError={context.active ? workspaceError : null}
                          onWorkspaceScopeChange={(scope) => {
                            if (paneRunning) return;
                            const next = normalizeWorkspaceScope(scope);
                            setWorkspaceError(null);
                            setWorkspaceOverrides((current) => ({
                              ...current,
                              [paneSession.chatId]: next,
                            }));
                            client.setWorkspaceScope(paneSession.chatId, next);
                          }}
                          settingsSnapshot={settingsSnapshot}
                          settingsLoading={settingsLoading}
                          onOpenModelSettings={onOpenModelSettings}
                          onInspectImagePreset={onInspectImagePreset}
                          onOpenSandboxSettings={onOpenSandboxSettings}
                          skills={skills}
                        />
                      );
                    }}
                  />
                </Suspense>
              </ThreadVisibilityContext.Provider>
            </div>}
            {view !== "chat" && (
              <div className="absolute inset-0 flex flex-col">
                {view === "remote" ? <LazyRemoteConnectionsPage
                  mainNavigationExpanded={showMainSidebar && hostSidebarOpen}
                  hostChromeInset={showHostChrome}
                  onBackToChat={onBackToChat}
                /> : <Suspense fallback={<StartupShell embedded surface={view === "apps" && isAppsSection(settingsInitialSection) ? settingsInitialSection : view} sidebarExpanded={hostSidebarOpen} />}>
                  <SettingsView
                    registerExitGuard={registerSettingsExitGuard}
                    themePreference={themePreference}
                    initialSection={settingsInitialSection}
                    focusTarget={settingsFocus}
                    initialSettings={settingsSnapshot}
                    showSidebar={view === "settings"}
                    mainNavigationExpanded={showMainSidebar && hostSidebarOpen}
                    onChangeTheme={setTheme}
                    onBackToChat={onBackToChat}
                    onModelNameChange={onModelNameChange}
                    onSettingsChange={setSettingsSnapshot}
                    skills={skills}
                    skillsLoading={skillsLoading}
                    skillsError={skillsError}
                    onStartAutomationChat={onStartAutomationChat}
                    titleOverrides={sidebarState.title_overrides}
                    sessions={topicSessions}
                    onSectionChange={onSettingsSectionChange}
                    onLogout={onLogout}
                    onRestart={onRestart}
                    onNativeEngineRestart={onNativeEngineRestart}
                    isRestarting={isRestarting}
                    hostChromeInset={showHostChrome}
                  />
                </Suspense>}
              </div>
            )}
          </div>
          {managingConnections && !remoteConnections?.embeddedManagement && <div className="absolute inset-0 flex flex-col">
            <LazyRemoteConnectionsPage
              mainNavigationExpanded={showMainSidebar && hostSidebarOpen}
              hostChromeInset={showHostChrome}
              onBackToChat={() => remoteConnections?.closeManagement()}
            />
          </div>}
          </main>
        </div>

        {pendingTabRename ? (
          <Suspense fallback={null}>
            <RenameDialog
              open
              title={pendingTabRename.label}
              dialogTitle={t("workbench.renameGroupTitle")}
              description={t("workbench.renameGroupDescription")}
              placeholder={t("workbench.renameGroupPlaceholder")}
              onCancel={() => setPendingTabRename(null)}
              onConfirm={onConfirmTabRename}
            />
          </Suspense>
        ) : null}
        {pendingProjectRename ? (
          <Suspense fallback={null}>
            <RenameDialog
              open
              title={pendingProjectRename.label}
              dialogTitle={t("chat.renameProjectTitle")}
              description={t("chat.renameProjectDescription")}
              placeholder={t("chat.renameProjectPlaceholder")}
              onCancel={() => setPendingProjectRename(null)}
              onConfirm={onConfirmProjectRename}
            />
          </Suspense>
        ) : null}
        <ChannelPairing />
      </div>
    </ThemeProvider>
  );
}
