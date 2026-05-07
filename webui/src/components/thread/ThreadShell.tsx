import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  BookOpen,
  ChevronRight,
  Code2,
  LayoutGrid,
  Lightbulb,
  MoreHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { AskUserPrompt } from "@/components/thread/AskUserPrompt";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadViewport } from "@/components/thread/ThreadViewport";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import { listSlashCommands } from "@/lib/api";
import type { ChatSummary, SlashCommand, UIMessage } from "@/lib/types";
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
  onOpenSettings?: () => void;
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

export function ThreadShell({
  session,
  title,
  onToggleSidebar,
  onCreateChat,
  onTurnEnd,
  theme = "light",
  onToggleTheme = () => {},
  onOpenSettings = () => {},
  hideSidebarToggleOnDesktop = false,
}: ThreadShellProps) {
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
  const historyKey = session?.key ?? null;
  const { messages: historical, loading, hasPendingToolCalls } = useSessionHistory(historyKey);
  const { client, modelName, token } = useClient();
  const [booting, setBooting] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const pendingFirstRef = useRef<string | null>(null);
  const messageCacheRef = useRef<Map<string, UIMessage[]>>(new Map());
  const lastCachedChatIdRef = useRef<string | null>(null);

  const initial = useMemo(() => {
    if (!chatId) return historical;
    return messageCacheRef.current.get(chatId) ?? historical;
  }, [chatId, historical]);
  const {
    messages,
    isStreaming,
    send,
    setMessages,
    streamError,
    dismissStreamError,
  } = useNanobotStream(chatId, initial, hasPendingToolCalls, onTurnEnd);
  const showHeroComposer = messages.length === 0 && !loading;
  const pendingAsk = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.kind === "trace") continue;
      if (message.role === "user") return null;
      if (message.role === "assistant" && message.buttons?.some((row) => row.length > 0)) {
        return {
          question: message.content,
          buttons: message.buttons,
        };
      }
      if (message.role === "assistant") return null;
    }
    return null;
  }, [messages]);

  useEffect(() => {
    if (!chatId || loading) return;
    const cached = messageCacheRef.current.get(chatId);
    // When the user switches away and back, keep the local in-memory thread
    // state (including not-yet-persisted messages) instead of replacing it with
    // whatever the history endpoint currently knows about.
    setMessages(cached && cached.length > 0 ? cached : historical);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, chatId, historical]);

  useEffect(() => {
    if (chatId) return;
    setMessages(historical);
  }, [chatId, historical, setMessages]);

  useLayoutEffect(() => {
    if (!chatId) {
      lastCachedChatIdRef.current = null;
      return;
    }
    if (loading) return;
    // Skip the first cache write after a chat switch. During that render,
    // `messages` can still belong to the previous chat until the stream hook
    // resets its local state for the new session.
    if (lastCachedChatIdRef.current !== chatId) {
      lastCachedChatIdRef.current = chatId;
      if (messages.length > 0) {
        messageCacheRef.current.set(chatId, messages);
      }
      return;
    }
    messageCacheRef.current.set(chatId, messages);
  }, [chatId, loading, messages]);

  useEffect(() => {
    if (!chatId) return;
    const pending = pendingFirstRef.current;
    if (!pending) return;
    pendingFirstRef.current = null;
    client.sendMessage(chatId, pending);
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: pending,
        createdAt: Date.now(),
      },
    ]);
    setBooting(false);
  }, [chatId, client, setMessages]);

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
    async (content: string) => {
      if (booting) return;
      setBooting(true);
      pendingFirstRef.current = content;
      const newId = await onCreateChat?.();
      if (!newId) {
        pendingFirstRef.current = null;
        setBooting(false);
      }
    },
    [booting, onCreateChat],
  );

  const handleQuickAction = useCallback(
    (prompt: string) => {
      if (session) {
        send(prompt);
        return;
      }
      void handleWelcomeSend(prompt);
    },
    [handleWelcomeSend, send, session],
  );

  const quickActions = (
    <div className="mx-auto grid w-full max-w-[58rem] grid-cols-2 gap-3 pt-4 sm:grid-cols-3 lg:grid-cols-6 lg:gap-4">
      {QUICK_ACTION_KEYS.map(({ key, icon: Icon, tone }) => {
        const title = t(`thread.empty.quickActions.${key}.title`);
        const prompt = t(`thread.empty.quickActions.${key}.prompt`);
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
      {pendingAsk ? (
        <AskUserPrompt
          question={pendingAsk.question}
          buttons={pendingAsk.buttons}
          onAnswer={send}
        />
      ) : null}
      {session ? (
        <ThreadComposer
          onSend={send}
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
        onOpenSettings={onOpenSettings}
        hideSidebarToggleOnDesktop={hideSidebarToggleOnDesktop}
        minimal={!session && !loading}
      />
      <ThreadViewport
        messages={messages}
        isStreaming={isStreaming}
        emptyState={emptyState}
        composer={composer}
      />
    </section>
  );
}
