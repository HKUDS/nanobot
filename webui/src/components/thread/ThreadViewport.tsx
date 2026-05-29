import {
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { isAgentActivityMember } from "@/components/thread/AgentActivityCluster";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CliAppInfo, McpPresetInfo, UIMessage } from "@/lib/types";

interface ThreadViewportProps {
  messages: UIMessage[];
  isStreaming: boolean;
  composer: ReactNode;
  emptyState?: ReactNode;
  scrollToBottomSignal?: number;
  conversationKey?: string | null;
  showScrollToBottomButton?: boolean;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
}

const NEAR_BOTTOM_PX = 48;
const DEFAULT_SCROLL_BUTTON_BOTTOM_PX = 192;
const SCROLL_BUTTON_COMPOSER_GAP_PX = 16;
export const INITIAL_HISTORY_WINDOW = 160;
export const HISTORY_WINDOW_INCREMENT = 120;

export function windowMessages(messages: UIMessage[], visibleCount: number): UIMessage[] {
  if (messages.length <= visibleCount) return messages;
  let start = Math.max(0, messages.length - visibleCount);
  while (
    start > 0
    && isAgentActivityMember(messages[start])
    && isAgentActivityMember(messages[start - 1])
  ) {
    start -= 1;
  }
  return messages.slice(start);
}

export function ThreadViewport({
  messages,
  isStreaming,
  composer,
  emptyState,
  scrollToBottomSignal = 0,
  conversationKey = null,
  showScrollToBottomButton = true,
  cliApps = [],
  mcpPresets = [],
}: ThreadViewportProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const composerDockRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastConversationKeyRef = useRef<string | null>(conversationKey);
  const pendingConversationScrollRef = useRef(true);
  const scrollFrameIdsRef = useRef<number[]>([]);
  const restoreScrollAfterPrependRef =
    useRef<{ height: number; top: number } | null>(null);
  /** User scrolled away from the bottom; do not auto-yank until they return or we reset (new chat / send). */
  const userReadingHistoryRef = useRef(false);
  const [atBottom, setAtBottom] = useState(true);
  const [composerDockHeight, setComposerDockHeight] = useState(0);
  const [visibleMessageCount, setVisibleMessageCount] =
    useState(INITIAL_HISTORY_WINDOW);
  const hasMessages = messages.length > 0;
  const visibleMessages = useMemo(
    () => windowMessages(messages, visibleMessageCount),
    [messages, visibleMessageCount],
  );
  const hiddenMessageCount = messages.length - visibleMessages.length;
  const scrollButtonBottom = composerDockHeight > 0
    ? composerDockHeight + SCROLL_BUTTON_COMPOSER_GAP_PX
    : DEFAULT_SCROLL_BUTTON_BOTTOM_PX;

  const cancelScheduledBottomScroll = useCallback(() => {
    for (const id of scrollFrameIdsRef.current) {
      window.cancelAnimationFrame(id);
    }
    scrollFrameIdsRef.current = [];
  }, []);

  const scrollToBottomNow = useCallback((smooth = false) => {
    const el = scrollRef.current;
    const marker = bottomRef.current;
    const behavior: ScrollBehavior = smooth ? "smooth" : "auto";
    if (marker) {
      marker.scrollIntoView({ block: "end", behavior });
    } else if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior });
    }
    setAtBottom(true);
  }, []);

  const scrollToBottom = useCallback(
    (smooth = false, frames = 1, options?: { force?: boolean }) => {
      const force = options?.force ?? false;
      cancelScheduledBottomScroll();
      const run = () => {
        if (!force && userReadingHistoryRef.current) return;
        scrollToBottomNow(smooth);
      };
      run();
      for (let i = 1; i < frames; i += 1) {
        const id = window.requestAnimationFrame(() => {
          if (!force && userReadingHistoryRef.current) return;
          scrollToBottomNow(smooth);
        });
        scrollFrameIdsRef.current.push(id);
      }
    },
    [cancelScheduledBottomScroll, scrollToBottomNow],
  );

  const loadEarlierMessages = useCallback(() => {
    const el = scrollRef.current;
    if (el) {
      restoreScrollAfterPrependRef.current = {
        height: el.scrollHeight,
        top: el.scrollTop,
      };
    }
    userReadingHistoryRef.current = true;
    setAtBottom(false);
    setVisibleMessageCount((count) =>
      Math.min(messages.length, count + HISTORY_WINDOW_INCREMENT),
    );
  }, [messages.length]);

  const measureComposerDock = useCallback(() => {
    const el = composerDockRef.current;
    if (!el) return;
    const height = el.getBoundingClientRect().height || el.offsetHeight;
    setComposerDockHeight((current) =>
      Math.abs(current - height) < 1 ? current : height,
    );
  }, []);

  useEffect(() => {
    if (!atBottom) return;
    // Instant jump: CSS scroll-smooth + behavior "auto" still animates in some
    // browsers; session switches and history hydration should never slide from top.
    scrollToBottom(false);
  }, [messages, atBottom, scrollToBottom]);

  useEffect(() => {
    if (scrollToBottomSignal <= 0) return;
    userReadingHistoryRef.current = false;
    scrollToBottom(false, 8);
  }, [scrollToBottomSignal, scrollToBottom]);

  useLayoutEffect(() => {
    if (lastConversationKeyRef.current === conversationKey) return;
    lastConversationKeyRef.current = conversationKey;
    pendingConversationScrollRef.current = true;
    userReadingHistoryRef.current = false;
    setAtBottom(true);
    setVisibleMessageCount(INITIAL_HISTORY_WINDOW);
  }, [conversationKey]);

  useLayoutEffect(() => {
    const pending = restoreScrollAfterPrependRef.current;
    if (!pending) return;
    const el = scrollRef.current;
    restoreScrollAfterPrependRef.current = null;
    if (!el) return;
    const delta = el.scrollHeight - pending.height;
    el.scrollTop = pending.top + delta;
  }, [visibleMessages.length]);

  useLayoutEffect(() => {
    if (!pendingConversationScrollRef.current) return;
    if (!conversationKey) {
      pendingConversationScrollRef.current = false;
      scrollToBottom(false, 4);
      return;
    }
    scrollToBottom(false, 8);
    if (!hasMessages) return;
    pendingConversationScrollRef.current = false;
  }, [conversationKey, hasMessages, messages, scrollToBottom]);

  useLayoutEffect(() => {
    measureComposerDock();
  }, [composer, hasMessages, measureComposerDock]);

  useEffect(() => cancelScheduledBottomScroll, [cancelScheduledBottomScroll]);

  useEffect(() => {
    const target = contentRef.current;
    if (!target || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (userReadingHistoryRef.current) return;
      scrollToBottom(false, 4);
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMessages, scrollToBottom]);

  useEffect(() => {
    const target = composerDockRef.current;
    if (!target || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measureComposerDock());
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMessages, measureComposerDock]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distance < NEAR_BOTTOM_PX;
      setAtBottom(near);
      userReadingHistoryRef.current = !near;
    };

    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          "absolute inset-0 overflow-y-auto scroll-auto scrollbar-thin",
          "[&::-webkit-scrollbar]:w-1.5",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/30",
          "[&::-webkit-scrollbar-track]:bg-transparent",
        )}
      >
        {hasMessages ? (
          <div ref={contentRef} className="mx-auto flex min-h-full w-full max-w-[64rem] flex-col">
            <div className="flex-1 px-4 pb-20 pt-4">
              <div className="mx-auto w-full max-w-[49.5rem]">
                <ThreadMessages
                  messages={visibleMessages}
                  isStreaming={isStreaming}
                  hiddenMessageCount={hiddenMessageCount}
                  onLoadEarlier={loadEarlierMessages}
                  cliApps={cliApps}
                  mcpPresets={mcpPresets}
                />
              </div>
            </div>

            <div
              ref={composerDockRef}
              data-testid="thread-composer-dock"
              className="sticky bottom-0 z-10 mt-auto bg-background"
            >
              <div className="px-4 pb-3">
                {composer}
              </div>
            </div>
          </div>
        ) : (
          <div ref={contentRef} className="mx-auto flex min-h-full w-full max-w-[72rem] flex-col px-4">
            <div className="flex w-full flex-1 items-center justify-center py-10 sm:py-12">
              <div className="relative w-full max-w-[58rem]">
                <div className="absolute inset-x-0 bottom-[calc(100%+1.5rem)] flex justify-center">
                  {emptyState}
                </div>
                <div className="w-full">{composer}</div>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} aria-hidden className="h-px" />
      </div>

      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-background to-transparent"
      />

      {showScrollToBottomButton && !atBottom && (
        <Button
          variant="outline"
          size="icon"
          onClick={() => scrollToBottom(true, 1, { force: true })}
          className={cn(
            /* Keep clear of sticky composer (textarea + toolbar + optional goal strip). */
            "absolute left-1/2 z-20 h-8 w-8 -translate-x-1/2 rounded-full shadow-md",
            "bg-background/90 backdrop-blur",
            "animate-in fade-in-0 zoom-in-95",
          )}
          style={{ bottom: scrollButtonBottom }}
          aria-label={t("thread.scrollToBottom")}
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
