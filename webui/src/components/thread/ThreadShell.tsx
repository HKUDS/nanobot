import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  BookOpen,
  ChevronRight,
  Code2,
  ImageIcon,
  LayoutGrid,
  Lightbulb,
  MoreHorizontal,
  Palette,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { useNanobotStream, type SendImage, type SendOptions } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import { listSlashCommands, fetchWebuiThreadWithRetry } from "@/lib/api";
import type { ChatSummary, SlashCommand, UIMessage } from "@/lib/types";
import { WEBUI_THREAD_SCHEMA_VERSION } from "@/lib/types";
import { mergeCanonicalHistoryPreservingLongTasks } from "@/lib/thread-history-merge";
import { normalizeLegacyLongTaskMessages } from "@/lib/thread-display-compat";
import { mergeWebuiDiskSnapshotWithHistorical } from "@/lib/thread-webui-merge";
import { useClient } from "@/providers/ClientProvider";

interface ThreadShellProps {
  session: ChatSummary | null;
  title: string;
  onToggleSidebar: () => void;
  onGoHome?: () => void;
  onNewChat?: () => void;
  onCreateChat?: () => Promise<string | null>;
  onTurnEnd?: () => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
  hideSidebarToggleOnDesktop?: boolean;
}

function toModelBadgeLabel(modelName: string | null): string | null {
  if (!modelName) return null;
  const trimmed = modelName.trim();
  if (!trimmed) return null;
  const leaf = trimmed.split("/").pop() ?? trimmed;
  return leaf || trimmed;
}

const QUICK_ACTION_KEYS = [
  { key: "plan", icon: LayoutGrid, tone: "text-[#f25b8f]" },
  { key: "analyze", icon: BarChart3, tone: "text-[#4f9de8]" },
  { key: "brainstorm", icon: Lightbulb, tone: "text-[#53c59d]" },
  { key: "code", icon: Code2, tone: "text-[#eba45d]" },
  { key: "summarize", icon: BookOpen, tone: "text-[#a877e7]" },
  { key: "more", icon: MoreHorizontal, tone: "text-muted-foreground/65" },
] as const;

const IMAGE_QUICK_ACTION_KEYS = [
  { key: "icon", icon: ImageIcon, tone: "text-[#4f9de8]" },
  { key: "sticker", icon: Sparkles, tone: "text-[#f25b8f]" },
  { key: "poster", icon: Palette, tone: "text-[#eba45d]" },
  { key: "product", icon: LayoutGrid, tone: "text-[#53c59d]" },
  { key: "portrait", icon: ImageIcon, tone: "text-[#a877e7]" },
  { key: "edit", icon: MoreHorizontal, tone: "text-muted-foreground/65" },
] as const;

interface PendingFirstMessage {
  content: string;
  images?: SendImage[];
  options?: SendOptions;
}

export function ThreadShell({
  session,
  title,
  onToggleSidebar,
  onCreateChat,
  onTurnEnd,
  theme = "light",
  onToggleTheme = () => {},
  hideSidebarToggleOnDesktop = false,
}: ThreadShellProps) {
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
  const historyKey = session?.key ?? null;
  const {
    messages: historical,
    loading,
    hasPendingToolCalls,
    refresh: refreshHistory,
    version: historyVersion,
  } = useSessionHistory(historyKey);
  const { client, modelName, token } = useClient();
  const [booting, setBooting] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const [heroImageMode, setHeroImageMode] = useState(false);
  const [scrollToBottomSignal, setScrollToBottomSignal] = useState(0);
  const pendingFirstRef = useRef<PendingFirstMessage | null>(null);
  const messageCacheRef = useRef<Map<string, UIMessage[]>>(new Map());
  /** Last chatId we associated with the in-memory thread (for cache-on-switch). */
  const prevChatIdForCacheRef = useRef<string | null>(null);
  /** Skip one message-cache write right after chatId changes (messages may not match yet). */
  const skipLayoutCacheRef = useRef(false);
  const appliedHistoryVersionRef = useRef<Map<string, number>>(new Map());
  const pendingCanonicalHydrateRef = useRef<Set<string>>(new Set());
  const sessionKeyByChatIdRef = useRef<Map<string, string>>(new Map());
  const webuiDiskHydratedKeyRef = useRef<string | null>(null);
  const webuiSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const initial = useMemo(() => {
    if (!chatId) return historical;
    return messageCacheRef.current.get(chatId) ?? historical;
  }, [chatId, historical]);
  const handleTurnEnd = useCallback(() => {
    if (chatId) pendingCanonicalHydrateRef.current.add(chatId);
    refreshHistory();
    onTurnEnd?.();
  }, [chatId, onTurnEnd, refreshHistory]);
  const {
    messages,
    isStreaming,
    runStartedAt,
    send,
    stop,
    setMessages,
    streamError,
    dismissStreamError,
  } = useNanobotStream(chatId, initial, hasPendingToolCalls, handleTurnEnd);

  useEffect(() => {
    if (chatId && historyKey) sessionKeyByChatIdRef.current.set(chatId, historyKey);
  }, [chatId, historyKey]);

  useEffect(() => {
    webuiDiskHydratedKeyRef.current = null;
  }, [historyKey]);

  useEffect(() => {
    if (!historyKey || !chatId || loading) return;
    if (webuiDiskHydratedKeyRef.current === historyKey) return;
    let cancelled = false;
    void (async () => {
      const disk = await fetchWebuiThreadWithRetry(token, historyKey);
      if (cancelled) return;
      webuiDiskHydratedKeyRef.current = historyKey;
      const dm = disk?.messages;
      if (!dm?.length) return;
      setMessages((prev) =>
        normalizeLegacyLongTaskMessages(
          mergeWebuiDiskSnapshotWithHistorical(dm, prev.length ? prev : historical),
        ),
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [historyKey, chatId, loading, historical, setMessages, token]);

  useEffect(() => {
    if (!historyKey || !chatId) return;
    if (webuiSaveTimerRef.current !== null) clearTimeout(webuiSaveTimerRef.current);
    webuiSaveTimerRef.current = setTimeout(() => {
      webuiSaveTimerRef.current = null;
      client.saveWebuiThreadSnapshot(historyKey, {
        schemaVersion: WEBUI_THREAD_SCHEMA_VERSION,
        savedAt: new Date().toISOString(),
        sessionKey: historyKey,
        messages: normalizeLegacyLongTaskMessages(messages),
      });
    }, 450);
    return () => {
      if (webuiSaveTimerRef.current !== null) {
        clearTimeout(webuiSaveTimerRef.current);
        webuiSaveTimerRef.current = null;
      }
    };
  }, [messages, historyKey, chatId, client]);

  const displayMessages = useMemo(
    () => normalizeLegacyLongTaskMessages(messages),
    [messages],
  );

  const showHeroComposer = messages.length === 0 && !loading;

  useEffect(() => {
    if (!chatId || loading) return;
    const cached = messageCacheRef.current.get(chatId);
    const appliedVersion = appliedHistoryVersionRef.current.get(chatId) ?? 0;
    const hasPendingCanonicalHydrate = pendingCanonicalHydrateRef.current.has(chatId);
    const hasNewCanonicalHistory = hasPendingCanonicalHydrate && historyVersion > appliedVersion;
    // When the user switches away and back, keep the local in-memory thread
    // state (including not-yet-persisted messages) instead of replacing it with
    // whatever the history endpoint currently knows about. Once a fresh
    // canonical replay arrives after turn_end, prefer it so live Markdown/tool
    // rendering converges to the same shape as a manual refresh.
    setMessages((prev) => {
      if (hasNewCanonicalHistory && historical.length > 0) {
        pendingCanonicalHydrateRef.current.delete(chatId);
        appliedHistoryVersionRef.current.set(chatId, historyVersion);
        const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
        const normalized = normalizeLegacyLongTaskMessages(merged);
        messageCacheRef.current.set(chatId, normalized);
        return normalized;
      }
      if (cached && cached.length > 0) return normalizeLegacyLongTaskMessages(cached);
      if (historical.length === 0 && prev.length > 0) return normalizeLegacyLongTaskMessages(prev);
      appliedHistoryVersionRef.current.set(chatId, historyVersion);
      const merged = mergeCanonicalHistoryPreservingLongTasks(prev, historical);
      return normalizeLegacyLongTaskMessages(merged);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, chatId, historical, historyVersion]);

  useEffect(() => {
    if (!chatId) return;
    return client.onSessionUpdate((updatedChatId) => {
      if (updatedChatId !== chatId) return;
      pendingCanonicalHydrateRef.current.add(chatId);
      refreshHistory();
    });
  }, [chatId, client, refreshHistory]);

  useEffect(() => {
    if (!chatId || loading) return;
    setScrollToBottomSignal((value) => value + 1);
  }, [chatId, loading, historical]);

  useEffect(() => {
    if (chatId) return;
    setMessages(historical);
  }, [chatId, historical, setMessages]);

  useLayoutEffect(() => {
    if (chatId) {
      const prev = prevChatIdForCacheRef.current;
      if (prev && prev !== chatId) {
        const oldKey = sessionKeyByChatIdRef.current.get(prev);
        const cached = messageCacheRef.current.get(prev);
        if (oldKey && cached && cached.length > 0) {
          client.saveWebuiThreadSnapshot(oldKey, {
            schemaVersion: WEBUI_THREAD_SCHEMA_VERSION,
            savedAt: new Date().toISOString(),
            sessionKey: oldKey,
            messages: normalizeLegacyLongTaskMessages(cached),
          });
        }
        messageCacheRef.current.set(prev, normalizeLegacyLongTaskMessages(messages));
        skipLayoutCacheRef.current = true;
      }
      prevChatIdForCacheRef.current = chatId;
    } else {
      if (prevChatIdForCacheRef.current) {
        messageCacheRef.current.set(
          prevChatIdForCacheRef.current,
          normalizeLegacyLongTaskMessages(messages),
        );
        skipLayoutCacheRef.current = true;
      }
      prevChatIdForCacheRef.current = null;
    }
  }, [chatId, messages, client]);

  // Persist thread to in-memory cache after paint so ``useNanobotStream``'s chat switch
  // ``useEffect`` reset has flushed; ``skipLayoutCacheRef`` drops the first run that still
  // sees the *previous* chat's ``messages`` (avoids stale rows leaking across sessions).
  useEffect(() => {
    if (!chatId) {
      return;
    }
    if (skipLayoutCacheRef.current) {
      skipLayoutCacheRef.current = false;
      return;
    }
    if (loading) {
      return;
    }
    messageCacheRef.current.set(chatId, normalizeLegacyLongTaskMessages(messages));
  }, [chatId, loading, messages]);

  useEffect(() => {
    if (!chatId) return;
    const pending = pendingFirstRef.current;
    if (!pending) return;
    pendingFirstRef.current = null;
    setScrollToBottomSignal((value) => value + 1);
    send(pending.content, pending.images, pending.options);
    setBooting(false);
  }, [chatId, send]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const commands = await listSlashCommands(token);
        if (!cancelled) setSlashCommands(commands);
      } catch {
        if (!cancelled) setSlashCommands([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const handleWelcomeSend = useCallback(
    async (content: string, images?: SendImage[], options?: SendOptions) => {
      if (booting) return;
      setBooting(true);
      pendingFirstRef.current = { content, images, options };
      const newId = await onCreateChat?.();
      if (!newId) {
        pendingFirstRef.current = null;
        setBooting(false);
      }
    },
    [booting, onCreateChat],
  );

  const handleThreadSend = useCallback(
    (content: string, images?: SendImage[], options?: SendOptions) => {
      setScrollToBottomSignal((value) => value + 1);
      send(content, images, options);
    },
    [send],
  );

  const handleQuickAction = useCallback(
    (prompt: string) => {
      const options: SendOptions | undefined = heroImageMode
        ? { imageGeneration: { enabled: true, aspect_ratio: null } }
        : undefined;
      if (session) {
        handleThreadSend(prompt, undefined, options);
        return;
      }
      void handleWelcomeSend(prompt, undefined, options);
    },
    [handleThreadSend, handleWelcomeSend, heroImageMode, session],
  );

  const quickActionItems = heroImageMode ? IMAGE_QUICK_ACTION_KEYS : QUICK_ACTION_KEYS;
  const quickActionPrefix = heroImageMode
    ? "thread.empty.imageQuickActions"
    : "thread.empty.quickActions";
  const quickActions = (
    <div className="mx-auto grid w-full max-w-[58rem] grid-cols-2 gap-3 pt-4 sm:grid-cols-3 lg:grid-cols-6 lg:gap-4">
      {quickActionItems.map(({ key, icon: Icon, tone }) => {
        const title = t(`${quickActionPrefix}.${key}.title`);
        const prompt = t(`${quickActionPrefix}.${key}.prompt`);
        return (
          <button
            key={key}
            type="button"
            onClick={() => handleQuickAction(prompt)}
            disabled={booting || isStreaming}
            className="group flex min-h-[136px] flex-col justify-between rounded-[20px] border border-black/[0.035] bg-card px-5 py-5 text-left shadow-[0_14px_34px_rgba(15,23,42,0.07)] transition-all hover:-translate-y-0.5 hover:shadow-[0_18px_42px_rgba(15,23,42,0.10)] disabled:pointer-events-none disabled:opacity-60 dark:border-white/[0.06] dark:shadow-[0_16px_34px_rgba(0,0,0,0.28)]"
          >
            <Icon className={`h-[18px] w-[18px] ${tone}`} strokeWidth={2} />
            <span className="max-w-[7.5rem] text-[15px] font-medium leading-[1.28] tracking-[-0.01em] text-foreground/82">
              {title}
            </span>
            <ChevronRight className="h-4 w-4 self-end text-muted-foreground/45 transition-colors group-hover:text-muted-foreground" />
          </button>
        );
      })}
    </div>
  );

  const composer = (
    <>
      {streamError ? (
        <StreamErrorNotice
          error={streamError}
          onDismiss={dismissStreamError}
        />
      ) : null}
      {session ? (
        <ThreadComposer
          onSend={handleThreadSend}
          disabled={!chatId}
          isStreaming={isStreaming}
          placeholder={
            showHeroComposer
              ? t("thread.composer.placeholderHero")
              : t("thread.composer.placeholderThread")
          }
          modelLabel={toModelBadgeLabel(modelName)}
          variant={showHeroComposer ? "hero" : "thread"}
          slashCommands={slashCommands}
          imageMode={showHeroComposer ? heroImageMode : undefined}
          onImageModeChange={showHeroComposer ? setHeroImageMode : undefined}
          onStop={stop}
          runStartedAt={runStartedAt}
        />
      ) : (
        <ThreadComposer
          onSend={handleWelcomeSend}
          disabled={booting}
          isStreaming={isStreaming}
          placeholder={
            booting
              ? t("thread.composer.placeholderOpening")
              : t("thread.composer.placeholderHero")
          }
          modelLabel={toModelBadgeLabel(modelName)}
          variant="hero"
          slashCommands={slashCommands}
          imageMode={heroImageMode}
          onImageModeChange={setHeroImageMode}
          runStartedAt={runStartedAt}
        />
      )}
      {showHeroComposer ? quickActions : null}
    </>
  );

  const emptyState = loading ? (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      {t("thread.loadingConversation")}
    </div>
  ) : (
    <div className="flex w-full flex-col items-center text-center animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
      <h1 className="text-balance text-[40px] font-normal leading-tight tracking-[-0.045em] text-foreground sm:text-[48px]">
        {t("thread.empty.greeting")}
      </h1>
    </div>
  );

  return (
    <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <ThreadHeader
        title={title}
        onToggleSidebar={onToggleSidebar}
        theme={theme}
        onToggleTheme={onToggleTheme}
        hideSidebarToggleOnDesktop={hideSidebarToggleOnDesktop}
        minimal={!session && !loading}
      />
      <ThreadViewport
        messages={displayMessages}
        isStreaming={isStreaming}
        emptyState={emptyState}
        composer={composer}
        scrollToBottomSignal={scrollToBottomSignal}
        conversationKey={historyKey}
      />
    </section>
  );
}
