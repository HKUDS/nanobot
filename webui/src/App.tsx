import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { Sidebar } from "@/components/Sidebar";
import { SettingsView } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { preloadMarkdownText } from "@/components/MarkdownText";
import { useSessions } from "@/hooks/useSessions";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";
import { deriveWsUrl, fetchBootstrap } from "@/lib/bootstrap";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider } from "@/providers/ClientProvider";
import type { ChatSummary } from "@/lib/types";

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      client: NanobotClient;
      token: string;
      modelName: string | null;
    };

const SIDEBAR_STORAGE_KEY = "nanobot-webui.sidebar";
const SIDEBAR_WIDTH = 279;
type ShellView = "chat" | "settings";

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

export default function App() {
  const { t } = useTranslation();
  const [state, setState] = useState<BootState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const boot = await fetchBootstrap();
        if (cancelled) return;
        const url = deriveWsUrl(boot.ws_path, boot.token);
        const client = new NanobotClient({
          url,
          onReauth: async () => {
            try {
              const refreshed = await fetchBootstrap();
              return deriveWsUrl(refreshed.ws_path, refreshed.token);
            } catch {
              return null;
            }
          },
        });
        client.connect();
        setState({
          status: "ready",
          client,
          token: boot.token,
          modelName: boot.model_name ?? null,
        });
      } catch (e) {
        if (cancelled) return;
        setState({ status: "error", message: (e as Error).message });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const warm = () => preloadMarkdownText();
    const win = globalThis as typeof globalThis & {
      requestIdleCallback?: (
        callback: IdleRequestCallback,
        options?: IdleRequestOptions,
      ) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (typeof win.requestIdleCallback === "function") {
      const id = win.requestIdleCallback(warm, { timeout: 1500 });
      return () => win.cancelIdleCallback?.(id);
    }
    const id = globalThis.setTimeout(warm, 250);
    return () => globalThis.clearTimeout(id);
  }, []);

  if (state.status === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
          <img
            src="/brand/nanobot_icon.png"
            alt=""
            className="h-10 w-10 animate-pulse select-none"
            aria-hidden
            draggable={false}
          />
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
            </span>
            {t("app.loading.connecting")}
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <img
            src="/brand/nanobot_icon.png"
            alt=""
            className="h-10 w-10 opacity-60 grayscale select-none"
            aria-hidden
            draggable={false}
          />
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  const handleModelNameChange = (modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  };

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      modelName={state.modelName}
    >
      <Shell onModelNameChange={handleModelNameChange} />
    </ClientProvider>
  );
}

function Shell({ onModelNameChange }: { onModelNameChange: (modelName: string | null) => void }) {
  const { t, i18n } = useTranslation();
  const { theme, toggle } = useTheme();
  const { sessions, loading, refresh, createChat, deleteChat } = useSessions();
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [view, setView] = useState<ShellView>("chat");
  const [desktopSidebarOpen, setDesktopSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const lastSessionsLen = useRef(0);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        desktopSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [desktopSidebarOpen]);

  useEffect(() => {
    if (activeKey) return;
    if (sessions.length > 0 && lastSessionsLen.current === 0) {
      setActiveKey(sessions[0].key);
    }
    lastSessionsLen.current = sessions.length;
  }, [sessions, activeKey]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);

  const closeDesktopSidebar = useCallback(() => {
    setDesktopSidebarOpen(false);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isDesktop =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isDesktop) {
      setDesktopSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, []);

  const onNewChat = useCallback(async () => {
    try {
      const chatId = await createChat();
      setActiveKey(`websocket:${chatId}`);
      setView("chat");
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      return null;
    }
  }, [createChat]);

  const onSelectChat = useCallback(
    (key: string) => {
      setActiveKey(key);
      setView("chat");
      setMobileSidebarOpen(false);
    },
    [],
  );

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    setPendingDelete(null);
    if (deletingActive) setActiveKey(fallbackKey);
    try {
      await deleteChat(key);
    } catch (e) {
      if (deletingActive) setActiveKey(key);
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, sessions]);

  const headerTitle = activeSession
    ? activeSession.preview ||
      t("chat.fallbackTitle", { id: activeSession.chatId.slice(0, 6) })
    : t("app.brand");

  useEffect(() => {
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t]);

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    theme,
    onToggleTheme: toggle,
    onNewChat: () => {
      void onNewChat();
    },
    onSelect: onSelectChat,
    onRefresh: () => void refresh(),
    onRequestDelete: (key: string, label: string) =>
      setPendingDelete({ key, label }),
    activeView: view,
    onOpenSettings: () => {
      setView("settings" as const);
      setMobileSidebarOpen(false);
    },
  };

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      {/* Desktop sidebar: in normal flow, so the thread area width stays honest. */}
      <aside
        className={cn(
          "relative z-20 hidden shrink-0 overflow-hidden lg:block",
          "transition-[width] duration-300 ease-out",
        )}
        style={{ width: desktopSidebarOpen ? SIDEBAR_WIDTH : 0 }}
      >
        <div
          className={cn(
            "absolute inset-y-0 left-0 h-full w-[279px] overflow-hidden bg-sidebar shadow-inner-right",
            "transition-transform duration-300 ease-out",
            desktopSidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <Sidebar {...sidebarProps} onCollapse={closeDesktopSidebar} />
        </div>
      </aside>

      <Sheet
        open={mobileSidebarOpen}
        onOpenChange={(open) => setMobileSidebarOpen(open)}
      >
        <SheetContent
          side="left"
          showCloseButton={false}
          className="w-[279px] p-0 sm:max-w-[279px] lg:hidden"
        >
          <Sidebar {...sidebarProps} onCollapse={closeMobileSidebar} />
        </SheetContent>
      </Sheet>

      <main className="flex h-full min-w-0 flex-1 flex-col">
        {view === "settings" ? (
          <SettingsView
            theme={theme}
            onToggleTheme={toggle}
            onBackToChat={() => setView("chat")}
            onModelNameChange={onModelNameChange}
          />
        ) : (
          <ThreadShell
            session={activeSession}
            title={headerTitle}
            onToggleSidebar={toggleSidebar}
            onGoHome={() => setActiveKey(null)}
            onNewChat={onNewChat}
            hideSidebarToggleOnDesktop={desktopSidebarOpen}
          />
        )}
      </main>

      <DeleteConfirm
        open={!!pendingDelete}
        title={pendingDelete?.label ?? ""}
        onCancel={() => setPendingDelete(null)}
        onConfirm={onConfirmDelete}
      />
    </div>
  );
}
