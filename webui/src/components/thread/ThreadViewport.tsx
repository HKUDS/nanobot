import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PromptRail } from "@/components/thread/PromptRail";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { isAgentActivityMember } from "@/components/thread/AgentActivityCluster";
import { Button } from "@/components/ui/button";
import {
  findPromptElement,
  jumpToPrompt,
  promptTop,
} from "@/components/thread/promptNavigation";
import { cn } from "@/lib/utils";
import type { CliAppInfo, McpPresetInfo, SlashCommand, UIMessage } from "@/lib/types";

export interface ThreadViewportHandle {
  jumpToUserPrompt: (promptId: string) => void;
  cancelAutoScroll: () => void;
}

interface ThreadViewportProps {
  messages: UIMessage[];
  isStreaming: boolean;
  composer: ReactNode;
  emptyState?: ReactNode;
  scrollToBottomSignal?: number;
  scrollToLatestUserPromptSignal?: number;
  conversationKey?: string | null;
  showScrollToBottomButton?: boolean;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  slashCommands?: SlashCommand[];
  forkBoundaryMessageCount?: number | null;
  hasMoreBefore?: boolean;
  loadingOlder?: boolean;
  userMessageOffset?: number;
  onLoadOlder?: () => Promise<void> | void;
  onOpenFilePreview?: (path: string) => void;
  onForkFromMessage?: (beforeUserIndex: number) => void;
  onQuoteSelection?: (text: string) => void;
}

const NEAR_BOTTOM_PX = 48;
const NEAR_TOP_PX = 96;
const DEFAULT_SCROLL_BUTTON_BOTTOM_PX = 192;
const SCROLL_BUTTON_COMPOSER_GAP_PX = 16;
const SOFT_KEYBOARD_MIN_INSET_PX = 80;
const KEYBOARD_SCROLL_FRAMES = 18;
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

function isKeyboardEditableElement(element: Element | null): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable) return true;
  if (element instanceof HTMLTextAreaElement) return true;
  if (!(element instanceof HTMLInputElement)) return false;
  return ![
    "button",
    "checkbox",
    "color",
    "file",
    "hidden",
    "image",
    "radio",
    "range",
    "reset",
    "submit",
  ].includes(element.type);
}

function readSoftKeyboardInsetBottom(container: HTMLElement | null): number {
  const viewport = window.visualViewport;
  if (!viewport) return 0;
  const active = document.activeElement;
  if (!isKeyboardEditableElement(active) || !container?.contains(active)) return 0;
  const layoutHeight = window.innerHeight || document.documentElement.clientHeight;
  const inset = layoutHeight - viewport.height - viewport.offsetTop;
  return inset >= SOFT_KEYBOARD_MIN_INSET_PX ? Math.ceil(inset) : 0;
}

export const ThreadViewport = forwardRef<ThreadViewportHandle, ThreadViewportProps>(function ThreadViewport({
  messages,
  isStreaming,
  composer,
  emptyState,
  scrollToBottomSignal = 0,
  scrollToLatestUserPromptSignal = 0,
  conversationKey = null,
  showScrollToBottomButton = true,
  cliApps = [],
  mcpPresets = [],
  slashCommands = [],
  forkBoundaryMessageCount = null,
  hasMoreBefore = false,
  loadingOlder = false,
  userMessageOffset = 0,
  onLoadOlder,
  onOpenFilePreview,
  onForkFromMessage,
  onQuoteSelection,
}, ref) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const composerDockRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastConversationKeyRef = useRef<string | null>(conversationKey);
  const pendingConversationScrollRef = useRef(true);
  const pendingPromptJumpRef = useRef<string | null>(null);
  const scrollFrameIdsRef = useRef<number[]>([]);
  const programmaticPromptScrollTopRef = useRef<number | null>(null);
  const handledLatestPromptSignalRef = useRef(0);
  const activeTurnPromptRef = useRef<string | null>(null);
  const restoreScrollAfterPrependRef =
    useRef<{ height: number; top: number } | null>(null);
  /** User scrolled away from the bottom; do not auto-yank until they return or we reset (new chat / send). */
  const userReadingHistoryRef = useRef(false);
  const [atBottom, setAtBottom] = useState(true);
  const [composerDockHeight, setComposerDockHeight] = useState(0);
  const [keyboardInsetBottom, setKeyboardInsetBottom] = useState(0);
  const [hasVerticalOverflow, setHasVerticalOverflow] = useState(false);
  const [visibleMessageCount, setVisibleMessageCount] =
    useState(INITIAL_HISTORY_WINDOW);
  const hasMessages = messages.length > 0;
  const visibleMessages = useMemo(
    () => windowMessages(messages, visibleMessageCount),
    [messages, visibleMessageCount],
  );
  const hiddenMessageCount = messages.length - visibleMessages.length;
  const hiddenUserMessageCount =
    userMessageOffset
    + (hiddenMessageCount > 0
      ? messages.slice(0, hiddenMessageCount).filter((message) => message.role === "user").length
      : 0);
  const visibleForkBoundaryMessageCount =
    forkBoundaryMessageCount !== null && forkBoundaryMessageCount > hiddenMessageCount
      ? forkBoundaryMessageCount - hiddenMessageCount
      : null;
  const scrollButtonBottom =
    keyboardInsetBottom
    + (composerDockHeight > 0
      ? composerDockHeight + SCROLL_BUTTON_COMPOSER_GAP_PX
      : DEFAULT_SCROLL_BUTTON_BOTTOM_PX);
  const scrollViewportStyle =
    keyboardInsetBottom > 0 ? { bottom: keyboardInsetBottom } : undefined;

  const cancelScheduledBottomScroll = useCallback(() => {
    for (const id of scrollFrameIdsRef.current) {
      window.cancelAnimationFrame(id);
    }
    scrollFrameIdsRef.current = [];
  }, []);

  const markProgrammaticPromptScroll = useCallback((top: number) => {
    programmaticPromptScrollTopRef.current = top;
  }, []);

  const scrollToBottomNow = useCallback((smooth = false) => {
    const el = scrollRef.current;
    const marker = bottomRef.current;
    const behavior: ScrollBehavior = smooth ? "smooth" : "auto";
    if (el) {
      const top = Math.max(0, el.scrollHeight - el.clientHeight);
      try {
        el.scrollTo?.({ top, behavior });
        if (!smooth) el.scrollTop = top;
      } catch {
        try {
          el.scrollTop = top;
        } catch {
          // Test DOMs can expose read-only scrollTop; browsers keep this writable.
        }
      }
    } else if (marker) {
      marker.scrollIntoView({ block: "end", behavior });
    }
    userReadingHistoryRef.current = false;
    setAtBottom(true);
  }, []);

  const scrollToPromptTopNow = useCallback((promptId: string) => {
    const el = scrollRef.current;
    if (!el) return false;
    const target = findPromptElement(el, promptId);
    if (!target) return false;
    const top = Math.max(0, promptTop(el, target) - 16);
    markProgrammaticPromptScroll(top);
    try {
      el.scrollTo?.({ top, behavior: "auto" });
      el.scrollTop = top;
    } catch {
      try {
        el.scrollTop = top;
      } catch {
        // Test DOMs can expose read-only scrollTop; browsers keep this writable.
      }
    }
    const near = el.scrollHeight - top - el.clientHeight < NEAR_BOTTOM_PX;
    userReadingHistoryRef.current = false;
    setAtBottom(near);
    return true;
  }, [markProgrammaticPromptScroll]);

  const scrollToBottom = useCallback(
    (smooth = false, frames = 1, options?: { force?: boolean }) => {
      const force = options?.force ?? false;
      cancelScheduledBottomScroll();
      const run = () => {
        if (!force && userReadingHistoryRef.current) return;
        scrollToBottomNow(smooth);
      };
      const scheduleNext = (remainingFrames: number) => {
        if (remainingFrames <= 0) return;
        const id = window.requestAnimationFrame(() => {
          scrollFrameIdsRef.current = scrollFrameIdsRef.current.filter((frameId) => frameId !== id);
          if (!force && userReadingHistoryRef.current) return;
          scrollToBottomNow(smooth);
          scheduleNext(remainingFrames - 1);
        });
        scrollFrameIdsRef.current.push(id);
      };
      run();
      scheduleNext(frames - 1);
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
    activeTurnPromptRef.current = null;
    setAtBottom(false);
    if (hiddenMessageCount > 0) {
      setVisibleMessageCount((count) =>
        Math.min(messages.length, count + HISTORY_WINDOW_INCREMENT),
      );
      return;
    }
    if (hasMoreBefore && onLoadOlder && !loadingOlder) {
      setVisibleMessageCount((count) => count + HISTORY_WINDOW_INCREMENT);
      void onLoadOlder();
    }
  }, [hasMoreBefore, hiddenMessageCount, loadingOlder, messages.length, onLoadOlder]);

  const maybeLoadEarlierFromScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el || !hasMessages || pendingConversationScrollRef.current) return;
    if (!userReadingHistoryRef.current) return;
    if (el.scrollTop > NEAR_TOP_PX) return;
    if (hiddenMessageCount <= 0 && !hasMoreBefore) return;
    loadEarlierMessages();
  }, [hasMessages, hasMoreBefore, hiddenMessageCount, loadEarlierMessages]);

  const jumpToUserPrompt = useCallback((promptId: string) => {
    const scrollEl = scrollRef.current;
    if (scrollEl && findPromptElement(scrollEl, promptId)) {
      jumpToPrompt(scrollEl, promptId);
      return;
    }
    const index = messages.findIndex((message) => message.id === promptId);
    if (index < 0) return;
    pendingPromptJumpRef.current = promptId;
    userReadingHistoryRef.current = true;
    activeTurnPromptRef.current = null;
    setAtBottom(false);
    setVisibleMessageCount((count) => Math.max(count, messages.length - index));
  }, [messages]);

  useImperativeHandle(
    ref,
    () => ({
      jumpToUserPrompt,
      cancelAutoScroll: cancelScheduledBottomScroll,
    }),
    [cancelScheduledBottomScroll, jumpToUserPrompt],
  );

  const measureComposerDock = useCallback(() => {
    const el = composerDockRef.current;
    if (!el) return;
    const height = el.getBoundingClientRect().height || el.offsetHeight;
    setComposerDockHeight((current) =>
      Math.abs(current - height) < 1 ? current : height,
    );
  }, []);

  useLayoutEffect(() => {
    const updateKeyboardInset = () => {
      const scrollEl = scrollRef.current;
      const next = readSoftKeyboardInsetBottom(scrollEl);
      const active = document.activeElement;
      const composerFocused =
        hasMessages && isKeyboardEditableElement(active) && Boolean(scrollEl?.contains(active));
      setKeyboardInsetBottom((current) =>
        Math.abs(current - next) < 1 ? current : next,
      );
      if (composerFocused) {
        userReadingHistoryRef.current = false;
        scrollToBottom(false, KEYBOARD_SCROLL_FRAMES, { force: true });
      }
    };
    updateKeyboardInset();
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", updateKeyboardInset);
    viewport?.addEventListener("scroll", updateKeyboardInset);
    window.addEventListener("resize", updateKeyboardInset);
    document.addEventListener("focusin", updateKeyboardInset);
    document.addEventListener("focusout", updateKeyboardInset);
    return () => {
      viewport?.removeEventListener("resize", updateKeyboardInset);
      viewport?.removeEventListener("scroll", updateKeyboardInset);
      window.removeEventListener("resize", updateKeyboardInset);
      document.removeEventListener("focusin", updateKeyboardInset);
      document.removeEventListener("focusout", updateKeyboardInset);
    };
  }, [hasMessages, scrollToBottom]);

  useLayoutEffect(() => {
    if (keyboardInsetBottom > 0) {
      userReadingHistoryRef.current = false;
      scrollToBottom(false, KEYBOARD_SCROLL_FRAMES, { force: true });
      return;
    }
    if (userReadingHistoryRef.current) return;
    scrollToBottom(false, 4);
  }, [keyboardInsetBottom, scrollToBottom]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    const onComposerFocus = () => {
      const active = document.activeElement;
      if (!hasMessages || !isKeyboardEditableElement(active) || !scrollEl.contains(active)) return;
      userReadingHistoryRef.current = false;
      scrollToBottom(false, KEYBOARD_SCROLL_FRAMES, { force: true });
    };

    document.addEventListener("focusin", onComposerFocus);
    return () => document.removeEventListener("focusin", onComposerFocus);
  }, [hasMessages, scrollToBottom]);

  useEffect(() => {
    if (scrollToBottomSignal <= 0) return;
    userReadingHistoryRef.current = false;
    scrollToBottom(false, 8);
  }, [scrollToBottomSignal, scrollToBottom]);

  useLayoutEffect(() => {
    if (scrollToLatestUserPromptSignal <= handledLatestPromptSignalRef.current) return;
    const latest = messages[messages.length - 1];
    if (!latest || latest.role !== "user") return;
    handledLatestPromptSignalRef.current = scrollToLatestUserPromptSignal;
    cancelScheduledBottomScroll();
    activeTurnPromptRef.current = latest.id;
    if (!scrollToPromptTopNow(latest.id)) activeTurnPromptRef.current = null;
  }, [
    cancelScheduledBottomScroll,
    messages,
    scrollToLatestUserPromptSignal,
    scrollToPromptTopNow,
  ]);

  useLayoutEffect(() => {
    if (lastConversationKeyRef.current === conversationKey) return;
    lastConversationKeyRef.current = conversationKey;
    pendingConversationScrollRef.current = true;
    userReadingHistoryRef.current = false;
    activeTurnPromptRef.current = null;
    setAtBottom(true);
    setVisibleMessageCount(INITIAL_HISTORY_WINDOW);
  }, [conversationKey]);

  useLayoutEffect(() => {
    const promptId = activeTurnPromptRef.current;
    if (!promptId || userReadingHistoryRef.current) return;
    const promptIndex = messages.findIndex((message) => message.id === promptId);
    if (promptIndex < 0) {
      activeTurnPromptRef.current = null;
      return;
    }
    const hasAgentOutput = messages
      .slice(promptIndex + 1)
      .some((message) => message.role !== "user");
    if (!hasAgentOutput) return;
    scrollToBottom(false, isStreaming ? 3 : 1);
  }, [isStreaming, messages, scrollToBottom]);

  useLayoutEffect(() => {
    const pending = restoreScrollAfterPrependRef.current;
    if (!pending) return;
    const el = scrollRef.current;
    restoreScrollAfterPrependRef.current = null;
    if (!el) return;
    const delta = el.scrollHeight - pending.height;
    const nextTop = pending.top + delta;
    try {
      el.scrollTop = nextTop;
    } catch {
      try {
        el.scrollTo?.({ top: nextTop, behavior: "auto" });
      } catch {
        // Test DOMs can expose read-only scrollTop; browsers keep this writable.
      }
    }
  }, [visibleMessages.length, messages.length]);

  useLayoutEffect(() => {
    const promptId = pendingPromptJumpRef.current;
    const scrollEl = scrollRef.current;
    if (!promptId || !scrollEl || !findPromptElement(scrollEl, promptId)) return;
    pendingPromptJumpRef.current = null;
    const frame = window.requestAnimationFrame(() => jumpToPrompt(scrollEl, promptId));
    return () => window.cancelAnimationFrame(frame);
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

  useLayoutEffect(() => {
    if (!hasMessages || userReadingHistoryRef.current) return;
    const promptId = activeTurnPromptRef.current;
    if (promptId && scrollToPromptTopNow(promptId)) return;
    scrollToBottom(false, 2);
  }, [composerDockHeight, hasMessages, scrollToBottom, scrollToPromptTopNow]);

  useEffect(() => cancelScheduledBottomScroll, [cancelScheduledBottomScroll]);

  useEffect(() => {
    const target = composerDockRef.current;
    if (!target || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measureComposerDock());
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMessages, measureComposerDock]);

  const measureVerticalOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const next = el.scrollHeight > el.clientHeight + 1;
    setHasVerticalOverflow((current) => (current === next ? current : next));
  }, []);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el) return;

    measureVerticalOverflow();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measureVerticalOverflow);
    observer?.observe(el);
    if (content) observer?.observe(content);
    window.addEventListener("resize", measureVerticalOverflow);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measureVerticalOverflow);
    };
  }, [composerDockHeight, hasMessages, measureVerticalOverflow, visibleMessages.length]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = (allowHistoryLoad = true) => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distance < NEAR_BOTTOM_PX;
      const programmaticPromptTop = programmaticPromptScrollTopRef.current;
      const programmatic =
        programmaticPromptTop !== null && Math.abs(el.scrollTop - programmaticPromptTop) < 2;
      setAtBottom((current) => current === near ? current : near);
      if (programmatic) {
        programmaticPromptScrollTopRef.current = null;
        if (near) userReadingHistoryRef.current = false;
        return;
      }
      programmaticPromptScrollTopRef.current = null;
      userReadingHistoryRef.current = !near;
      if (!near) activeTurnPromptRef.current = null;
      if (allowHistoryLoad && !near) maybeLoadEarlierFromScroll();
    };

    onScroll(false);
    const handleScroll = () => onScroll(true);
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [maybeLoadEarlierFromScroll]);

  return (
    <div className="thread-viewport relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          "thread-viewport-scrollbar absolute inset-0 scroll-auto scrollbar-thin",
          hasVerticalOverflow ? "overflow-y-auto" : "overflow-hidden",
          "[&::-webkit-scrollbar]:w-1.5",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:bg-muted-foreground/30",
          "[&::-webkit-scrollbar-track]:bg-transparent",
        )}
        style={scrollViewportStyle}
      >
        {hasMessages ? (
          <div ref={contentRef} className="mx-auto flex min-h-full w-full max-w-[64rem] flex-col">
            <div
              data-testid="thread-message-region"
              className="flex min-h-0 flex-1 flex-col justify-start px-3 pb-4 pt-4 sm:px-4"
            >
              <div className="mx-auto w-full max-w-[49.5rem]">
                <ThreadMessages
                  messages={visibleMessages}
                  isStreaming={isStreaming}
                  hiddenUserMessageCount={hiddenUserMessageCount}
                  cliApps={cliApps}
                  mcpPresets={mcpPresets}
                  slashCommands={slashCommands}
                  forkBoundaryMessageCount={visibleForkBoundaryMessageCount}
                  onOpenFilePreview={onOpenFilePreview}
                  onForkFromMessage={onForkFromMessage}
                  onQuoteSelection={onQuoteSelection}
                />
              </div>
            </div>

            <div
              ref={composerDockRef}
              data-testid="thread-composer-dock"
              className="sticky bottom-0 z-10 bg-background"
            >
              <div className="px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:px-4">
                {composer}
              </div>
            </div>
          </div>
        ) : (
          <div ref={contentRef} className="mx-auto flex min-h-full w-full max-w-[72rem] flex-col px-3 sm:px-4">
            <div className="flex w-full flex-1 flex-col items-center pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-6 sm:justify-center sm:py-12">
              <div
                data-testid="thread-welcome-layout"
                className="relative grid w-full max-w-[58rem] flex-1 grid-rows-[minmax(min-content,1fr)_auto] gap-8 sm:block sm:flex-none"
              >
                <div className="flex min-h-0 min-w-0 w-full items-center justify-center sm:absolute sm:inset-x-0 sm:bottom-[calc(100%+2rem)]">
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

      {hasMessages ? (
        <PromptRail
          messages={visibleMessages}
          scrollRef={scrollRef}
          bottomOffset={scrollButtonBottom}
        />
      ) : null}

      {showScrollToBottomButton && !atBottom && (
        <div
          className="absolute left-1/2 z-20 -translate-x-1/2"
          style={{ bottom: scrollButtonBottom }}
        >
          <Button
            variant="outline"
            size="icon"
            onClick={() => scrollToBottom(true, 1, { force: true })}
            className={cn(
              "h-8 w-8 rounded-full shadow-md",
              "bg-background/90 backdrop-blur",
              "animate-in fade-in-0 zoom-in-95",
            )}
            aria-label={t("thread.scrollToBottom")}
          >
            <ArrowDown className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
});
