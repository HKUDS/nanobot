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
import { ThreadCameraController } from "@/components/thread/thread-camera";
import {
  ThreadMotionCoordinator,
  type ThreadMotionGeometry,
} from "@/components/thread/thread-motion";
import { Button } from "@/components/ui/button";
import {
  findPromptElement,
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
  activeTurnId?: string | null;
  activeTurnStartedHere?: boolean;
  conversationKey?: string | null;
  conversationReady?: boolean;
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

type ThreadScrollDirection = "backward" | "forward";

const KEYBOARD_SCROLL_DIRECTIONS: Readonly<
  Partial<Record<string, ThreadScrollDirection>>
> = {
  ArrowUp: "backward",
  PageUp: "backward",
  Home: "backward",
  ArrowDown: "forward",
  PageDown: "forward",
  End: "forward",
};

function directionFromDelta(deltaY: number): ThreadScrollDirection | null {
  return deltaY < 0 ? "backward" : deltaY > 0 ? "forward" : null;
}

function keyboardScrollDirection(
  event: KeyboardEvent,
): ThreadScrollDirection | null {
  if (event.key === " ") {
    return event.shiftKey ? "backward" : "forward";
  }
  return KEYBOARD_SCROLL_DIRECTIONS[event.key] ?? null;
}

function canScrollInDirection(
  element: HTMLElement,
  direction: ThreadScrollDirection | null,
): boolean {
  switch (direction) {
    case "backward":
      return element.scrollTop > 0;
    case "forward":
      return (
        element.scrollTop
        < Math.max(0, element.scrollHeight - element.clientHeight)
      );
    default:
      return false;
  }
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
  activeTurnId = null,
  activeTurnStartedHere = false,
  conversationKey = null,
  conversationReady = true,
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
  const messageRegionRef = useRef<HTMLDivElement>(null);
  const messageContentRef = useRef<HTMLDivElement>(null);
  const composerDockRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastConversationKeyRef = useRef<string | null>(conversationKey);
  const pendingConversationScrollRef = useRef(true);
  const pendingPromptJumpRef = useRef<string | null>(null);
  const restoreScrollAfterPrependRef =
    useRef<{ height: number; top: number } | null>(null);
  const composerDockHeightRef = useRef(0);
  const [atBottom, setAtBottom] = useState(true);
  const [composerDockHeight, setComposerDockHeight] = useState(0);
  const [keyboardInsetBottom, setKeyboardInsetBottom] = useState(0);
  const [hasVerticalOverflow, setHasVerticalOverflow] = useState(false);
  const [visibleMessageCount, setVisibleMessageCount] =
    useState(INITIAL_HISTORY_WINDOW);
  const threadMotionRef = useRef<ThreadMotionCoordinator | null>(null);
  if (threadMotionRef.current === null) {
    const camera = new ThreadCameraController(() => scrollRef.current);
    threadMotionRef.current = new ThreadMotionCoordinator({
      camera,
      measure: (promptId) => {
        const scrollEl = scrollRef.current;
        const composerDock = composerDockRef.current;
        if (!scrollEl) return null;
        const composerHeight = composerDock
          ? composerDock.getBoundingClientRect().height || composerDock.offsetHeight
          : 0;
        const prompt = promptId ? findPromptElement(scrollEl, promptId) : null;
        const scrollHeight = scrollEl.scrollHeight;
        const clientHeight = scrollEl.clientHeight;
        const maxScrollTop = Math.max(0, scrollHeight - clientHeight);
        return {
          scrollTop: scrollEl.scrollTop,
          scrollHeight,
          clientHeight,
          maxScrollTop,
          composerHeight,
          promptTop: prompt
            ? Math.min(
                maxScrollTop,
                Math.max(0, promptTop(scrollEl, prompt) - 16),
              )
            : null,
        };
      },
      onGeometry: (geometry: ThreadMotionGeometry) => {
        if (Math.abs(composerDockHeightRef.current - geometry.composerHeight) >= 1) {
          composerDockHeightRef.current = geometry.composerHeight;
          setComposerDockHeight(geometry.composerHeight);
        }
        const nextOverflow = geometry.scrollHeight > geometry.clientHeight + 1;
        setHasVerticalOverflow((current) =>
          current === nextOverflow ? current : nextOverflow,
        );
      },
      onAutoFollow: () => setAtBottom(true),
    });
  }
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

  const yieldCameraToUser = useCallback(() => {
    threadMotionRef.current?.takeUserControl();
  }, []);

  const scrollToBottomNow = useCallback((smooth = false) => {
    const el = scrollRef.current;
    const marker = bottomRef.current;
    const behavior: ScrollBehavior = smooth ? "smooth" : "auto";
    if (el) {
      const top = Math.max(0, el.scrollHeight - el.clientHeight);
      if (smooth) {
        threadMotionRef.current?.animateTo(top);
      } else {
        threadMotionRef.current?.jumpTo(top);
      }
    } else if (marker) {
      marker.scrollIntoView({ block: "end", behavior });
    }
    setAtBottom(true);
  }, []);

  const scrollToBottom = useCallback(
    (smooth = false, options?: { force?: boolean }) => {
      const force = options?.force ?? false;
      if (!force && threadMotionRef.current?.isAutoFollowPaused()) return;
      threadMotionRef.current?.resumeAutoFollow();
      scrollToBottomNow(smooth);
    },
    [scrollToBottomNow],
  );

  const loadEarlierMessages = useCallback(() => {
    const el = scrollRef.current;
    if (el) {
      restoreScrollAfterPrependRef.current = {
        height: el.scrollHeight,
        top: el.scrollTop,
      };
    }
    threadMotionRef.current?.takeUserControl();
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
    if (!threadMotionRef.current?.isBrowsingHistory()) return;
    if (el.scrollTop > NEAR_TOP_PX) return;
    if (hiddenMessageCount <= 0 && !hasMoreBefore) return;
    loadEarlierMessages();
  }, [hasMessages, hasMoreBefore, hiddenMessageCount, loadEarlierMessages]);

  const navigateToVisiblePrompt = useCallback((promptId: string) => {
    const scrollEl = scrollRef.current;
    const prompt = scrollEl ? findPromptElement(scrollEl, promptId) : null;
    if (!scrollEl || !prompt) return false;
    setAtBottom(false);
    const maxScrollTop = Math.max(0, scrollEl.scrollHeight - scrollEl.clientHeight);
    threadMotionRef.current?.navigateHistoryTo(
      Math.min(
        maxScrollTop,
        Math.max(0, promptTop(scrollEl, prompt) - 16),
      ),
    );
    return true;
  }, []);

  const jumpToUserPrompt = useCallback((promptId: string) => {
    if (navigateToVisiblePrompt(promptId)) return;
    const index = messages.findIndex((message) => message.id === promptId);
    if (index < 0) return;
    threadMotionRef.current?.takeUserControl();
    pendingPromptJumpRef.current = promptId;
    setAtBottom(false);
    setVisibleMessageCount((count) => Math.max(count, messages.length - index));
  }, [messages, navigateToVisiblePrompt]);

  const cancelAutoScroll = useCallback(() => {
    threadMotionRef.current?.takeUserControl();
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      jumpToUserPrompt,
      cancelAutoScroll,
    }),
    [cancelAutoScroll, jumpToUserPrompt],
  );

  useLayoutEffect(() => {
    const updateKeyboardInset = () => {
      const scrollEl = scrollRef.current;
      const next = readSoftKeyboardInsetBottom(scrollEl);
      const active = document.activeElement;
      const composerFocused =
        hasMessages
        && isKeyboardEditableElement(active)
        && Boolean(scrollEl?.contains(active));
      setKeyboardInsetBottom((current) =>
        Math.abs(current - next) < 1 ? current : next,
      );
      if (composerFocused) {
        // Focusing the composer establishes a new reference frame at the
        // latest message. This is one immediate positioning command; viewport
        // events may issue a fresh command, but no command survives into a
        // later render as a train of retry frames.
        scrollToBottom(false, { force: true });
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

  useEffect(() => {
    if (scrollToBottomSignal <= 0) return;
    scrollToBottom(false, { force: true });
  }, [scrollToBottomSignal, scrollToBottom]);

  useLayoutEffect(() => {
    if (lastConversationKeyRef.current === conversationKey) return;
    lastConversationKeyRef.current = conversationKey;
    pendingConversationScrollRef.current = true;
    threadMotionRef.current?.reset();
    setAtBottom(true);
    setVisibleMessageCount(INITIAL_HISTORY_WINDOW);
  }, [conversationKey]);

  useLayoutEffect(() => {
    if (!conversationReady) {
      threadMotionRef.current?.reset();
      return;
    }
    if (!activeTurnId) {
      threadMotionRef.current?.completeTurn();
      return;
    }

    const promptIndex = messages.findIndex(
      (message) => message.role === "user" && message.turnId === activeTurnId,
    );
    if (
      activeTurnStartedHere
      && promptIndex >= 0
      && threadMotionRef.current?.snapshot().turnId !== activeTurnId
    ) {
      // A turn submitted in this mounted viewport establishes a new prompt
      // origin. A restored turn must first complete open-at-bottom instead.
      pendingConversationScrollRef.current = false;
    }
    const prompt = promptIndex >= 0 ? messages[promptIndex] : null;
    const hasOutput = promptIndex >= 0
      ? messages
          .slice(promptIndex + 1)
          .some(
            (message) =>
              message.role !== "user"
              && (!message.turnId || message.turnId === activeTurnId),
          )
      : !activeTurnStartedHere && messages.some(
          (message) =>
            message.role !== "user" && message.turnId === activeTurnId,
        );
    threadMotionRef.current?.updateTurn({
      id: activeTurnId,
      promptId: prompt?.id ?? null,
      hasOutput,
      entry: activeTurnStartedHere ? "submitted" : "restored",
    });
  }, [activeTurnId, activeTurnStartedHere, conversationReady, messages]);

  useLayoutEffect(() => {
    const pending = restoreScrollAfterPrependRef.current;
    if (!pending) return;
    const el = scrollRef.current;
    restoreScrollAfterPrependRef.current = null;
    if (!el) return;
    const delta = el.scrollHeight - pending.height;
    const nextTop = Math.min(
      Math.max(0, el.scrollHeight - el.clientHeight),
      Math.max(0, pending.top + delta),
    );
    threadMotionRef.current?.jumpTo(nextTop);
  }, [visibleMessages.length, messages.length]);

  useLayoutEffect(() => {
    const promptId = pendingPromptJumpRef.current;
    const scrollEl = scrollRef.current;
    if (!promptId || !scrollEl || !findPromptElement(scrollEl, promptId)) return;
    pendingPromptJumpRef.current = null;
    const frame = window.requestAnimationFrame(() => navigateToVisiblePrompt(promptId));
    return () => window.cancelAnimationFrame(frame);
  }, [navigateToVisiblePrompt, visibleMessages.length]);

  useLayoutEffect(() => {
    if (!pendingConversationScrollRef.current) return;
    if (!conversationReady) return;
    if (!conversationKey) {
      pendingConversationScrollRef.current = false;
      scrollToBottom(false, { force: true });
      return;
    }
    scrollToBottom(false, { force: true });
    if (!hasMessages) return;
    pendingConversationScrollRef.current = false;
  }, [
    conversationKey,
    conversationReady,
    hasMessages,
    messages,
    scrollToBottom,
  ]);

  useLayoutEffect(() => {
    threadMotionRef.current?.invalidateGeometry();
  }, [composer, hasMessages, visibleMessages.length]);

  useEffect(() => () => threadMotionRef.current?.dispose(), []);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    const messageRegion = messageRegionRef.current;
    const messageContent = messageContentRef.current;
    const composerDock = composerDockRef.current;
    if (!el) return;

    const invalidateGeometry = () => {
      threadMotionRef.current?.invalidateGeometry();
    };
    invalidateGeometry();
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(invalidateGeometry);
    observer?.observe(el);
    if (content) observer?.observe(content);
    if (messageRegion) observer?.observe(messageRegion);
    if (messageContent) observer?.observe(messageContent);
    if (composerDock) observer?.observe(composerDock);
    window.addEventListener("resize", invalidateGeometry);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", invalidateGeometry);
    };
  }, [hasMessages]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = (allowHistoryLoad = true) => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distance < NEAR_BOTTOM_PX;
      const owner = threadMotionRef.current?.observeScroll(near) ?? "automatic";
      const logicallyAtBottom = owner === "automatic" || near;
      setAtBottom((current) =>
        current === logicallyAtBottom ? current : logicallyAtBottom,
      );
      if (allowHistoryLoad && owner === "user") maybeLoadEarlierFromScroll();
    };

    onScroll(false);
    const handleScroll = () => onScroll(true);
    const handleDirectionalInput = (
      direction: ThreadScrollDirection | null,
    ) => {
      if (!direction) return;
      threadMotionRef.current?.handleUserScrollIntent(
        canScrollInDirection(el, direction),
      );
    };
    const handleWheel = (event: WheelEvent) => {
      if (
        event.defaultPrevented
        || event.ctrlKey
        || Math.abs(event.deltaY) <= Math.abs(event.deltaX)
      ) {
        return;
      }
      handleDirectionalInput(directionFromDelta(event.deltaY));
    };
    const handlePointerDown = (event: PointerEvent) => {
      if (event.button === 0 && event.target === el) yieldCameraToUser();
    };
    let touchStartY: number | null = null;
    const handleTouchStart = (event: TouchEvent) => {
      touchStartY = event.touches[0]?.clientY ?? null;
    };
    const handleTouchMove = (event: TouchEvent) => {
      const currentY = event.touches[0]?.clientY;
      const scrollDeltaY =
        touchStartY !== null && currentY !== undefined
          ? touchStartY - currentY
          : 0;
      handleDirectionalInput(directionFromDelta(scrollDeltaY));
    };
    const handleTouchEnd = () => {
      touchStartY = null;
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented
        || event.altKey
        || event.ctrlKey
        || event.metaKey
        || isKeyboardEditableElement(event.target as Element | null)
      ) {
        return;
      }
      handleDirectionalInput(keyboardScrollDirection(event));
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    el.addEventListener("wheel", handleWheel, { passive: true });
    el.addEventListener("touchstart", handleTouchStart, { passive: true });
    el.addEventListener("touchmove", handleTouchMove, { passive: true });
    el.addEventListener("touchend", handleTouchEnd, { passive: true });
    el.addEventListener("touchcancel", handleTouchEnd, { passive: true });
    el.addEventListener("pointerdown", handlePointerDown);
    el.addEventListener("keydown", handleKeyDown);
    return () => {
      el.removeEventListener("scroll", handleScroll);
      el.removeEventListener("wheel", handleWheel);
      el.removeEventListener("touchstart", handleTouchStart);
      el.removeEventListener("touchmove", handleTouchMove);
      el.removeEventListener("touchend", handleTouchEnd);
      el.removeEventListener("touchcancel", handleTouchEnd);
      el.removeEventListener("pointerdown", handlePointerDown);
      el.removeEventListener("keydown", handleKeyDown);
    };
  }, [maybeLoadEarlierFromScroll, yieldCameraToUser]);

  return (
    <div className="thread-viewport relative flex min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          "thread-viewport-scrollbar absolute inset-0 scroll-auto",
          "[overflow-anchor:none] [scrollbar-width:none]",
          "[&::-webkit-scrollbar]:hidden",
          hasVerticalOverflow ? "overflow-y-auto" : "overflow-hidden",
        )}
        style={scrollViewportStyle}
      >
        <div
          ref={contentRef}
          data-testid={!hasMessages ? "thread-welcome-layout" : undefined}
          data-layout={hasMessages ? "thread" : "hero"}
          className={cn(
            "thread-layout mx-auto grid min-h-full w-full",
            hasMessages
              ? "max-w-[64rem]"
              : "max-w-[72rem] px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-6 sm:px-4 sm:py-12",
          )}
        >
          {hasMessages ? (
            <div
              ref={messageRegionRef}
              data-testid="thread-message-region"
              className="row-start-1 flex min-h-0 flex-col justify-start px-3 pb-4 pt-4 sm:px-4"
            >
              <div ref={messageContentRef} className="mx-auto w-full max-w-[49.5rem]">
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
          ) : (
            <div className="row-start-1 flex min-h-0 min-w-0 w-full items-center justify-center sm:items-end sm:pb-8">
              {emptyState}
            </div>
          )}

          <div
            ref={composerDockRef}
            data-testid="thread-composer-dock"
            className={cn(
              "row-start-2 z-10 w-full",
              hasMessages ? "sticky bottom-0 bg-background" : "relative self-center",
            )}
          >
            <div
              className={cn(
                hasMessages
                  ? "px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:px-4"
                  : "",
              )}
            >
              <div
                data-testid="thread-composer-motion"
                className="mx-auto w-full max-w-[58rem]"
              >
                {composer}
              </div>
            </div>
          </div>

          <div
            aria-hidden
            className="thread-layout-spacer row-start-3 min-h-0 overflow-hidden"
          />
        </div>
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
          onJumpToPrompt={navigateToVisiblePrompt}
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
            onClick={() => scrollToBottom(true, { force: true })}
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
