import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { FilePreviewAvailabilityProvider } from "@/components/FilePreviewAvailabilityContext";
import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import { PreviewPane } from "@/components/PreviewPane";
import { FileActionsProvider } from "@/components/FileActions";
import { createFilePreviewResource } from "@/lib/file-preview-resource";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { usePromptHistory } from "@/hooks/usePromptHistory";
import { ModelFallbackNotice } from "@/components/thread/ModelFallbackNotice";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";
import { SubagentTasksProvider } from "@/components/thread/SubagentTasks";
import { SubagentTaskDock } from "@/components/thread/SubagentTaskDock";
import { latestSubagentInputKey } from "@/lib/subagent-tasks";
import { SessionInfoPopover } from "@/components/thread/SessionInfoPopover";
import type { ComposerDraft, ComposerDraftStore } from "@/lib/composer-draft";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type {
  ComposerContextUsage,
  ComposerRoundUsage,
} from "@/components/thread/ComposerUsagePopover";
import {
  modelPresetOptionsFromSettings,
  toModelBadgeInfo,
} from "@/components/thread/model-preset";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { ThreadLoadingSkeleton } from "@/components/thread/ThreadLoadingSkeleton";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadViewport, type ThreadViewportHandle } from "@/components/thread/ThreadViewport";
import { useNanobotStream, type SendAttachment, type SendOptions } from "@/hooks/useNanobotStream";
import { useFilePreviewState, type FilePreviewState, type FilePreviewStore } from "@/hooks/useFilePreviewState";
import {
  ApiError,
  fetchFilePreviewAvailability,
  fetchFilePreview,
  fetchFileReferenceMetadata,
  fetchInstalledCliApps,
  fetchMcpPresets,
  fetchSettings,
  fetchWorkspaces,
  fetchWorkspaceDirectories,
  listSlashCommands,
} from "@/lib/api";
import {
  CLI_APPS_CHANGED_EVENT,
  installedCliAppsFromPayload,
  isCliAppsPayload,
} from "@/lib/cli-app-events";
import {
  MCP_PRESETS_CHANGED_EVENT,
  installedMcpPresetsFromPayload,
  isMcpPresetsPayload,
} from "@/lib/mcp-preset-events";
import type { StreamError } from "@/lib/nanobot-client";
import { isLocalAttachment } from "../../../../packages/client-events/attachments";
import type {
  ChatSummary,
  FilePreviewPayload,
  FileReferenceMetadata,
  RoundUsage,
  SettingsPayload,
  SlashCommand,
  SkillSummary,
  UIMessage,
  WorkspaceScopePayload,
  WorkspacesPayload,
  ProjectDirectory,
} from "@/lib/types";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { providerDisplayLabel } from "@/lib/provider-brand";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

function latestComposerContextUsage(messages: UIMessage[]): ComposerContextUsage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.kind === "compaction" && message.compaction?.phase === "succeeded") {
      return null;
    }
    const contextTokens = message.usage?.context_tokens;
    if (
      message.role !== "assistant"
      || message.kind === "trace"
      || message.isStreaming
      || typeof contextTokens !== "number"
      || !Number.isFinite(contextTokens)
      || contextTokens < 0
    ) {
      continue;
    }
    return {
      contextTokens,
      ...(typeof message.contextWindowTokens === "number"
        ? { contextWindowTokens: message.contextWindowTokens }
        : {}),
    };
  }
  return null;
}

function recentComposerRoundUsage(messages: UIMessage[]): ComposerRoundUsage[] {
  const recent: ComposerRoundUsage[] = [];
  const seenTurns = new Set<string>();
  for (let index = messages.length - 1; index >= 0 && recent.length < 8; index -= 1) {
    const message = messages[index];
    const turnKey = message.turnId || message.id;
    if (
      message.role !== "assistant"
      || message.kind === "trace"
      || message.isStreaming
      || seenTurns.has(turnKey)
    ) {
      continue;
    }

    seenTurns.add(turnKey);
    const rounds: RoundUsage[] = message.roundUsages ?? [];
    for (let roundIndex = rounds.length - 1; roundIndex >= 0; roundIndex -= 1) {
      const round = rounds[roundIndex];
      const inputTokens = round.prompt_tokens;
      if (
        recent.length >= 8
        || typeof inputTokens !== "number"
        || !Number.isFinite(inputTokens)
        || inputTokens <= 0
      ) {
        continue;
      }
      const outputTokens = round.completion_tokens;
      const cachedTokens = round.cached_tokens;
      const estimatedTokens = round.estimated_tokens;
      const generationMs = round.generation_ms;
      recent.push({
        id: `${turnKey}:${roundIndex}`,
        timestamp: message.completedAt ?? message.createdAt,
        inputTokens,
        ...(typeof outputTokens === "number" && Number.isFinite(outputTokens)
          ? { outputTokens }
          : {}),
        ...(typeof cachedTokens === "number" && Number.isFinite(cachedTokens)
          ? { cachedTokens }
          : {}),
        ...(typeof estimatedTokens === "number" && Number.isFinite(estimatedTokens)
          ? { estimatedTokens }
          : {}),
        ...(typeof generationMs === "number" && Number.isFinite(generationMs)
          ? { generationMs }
          : {}),
      });
    }
  }
  return recent.reverse();
}

function latestActiveTurnId(messages: UIMessage[], runStartedAt: number | null): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.isStreaming && message.turnId) return message.turnId;
  }
  if (runStartedAt === null) return null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role !== "user"
      && message.turnId
      && message.createdAt >= runStartedAt * 1000
    ) return message.turnId;
  }
  return null;
}

function hasInlineDeliveryError(
  messages: UIMessage[],
  error: StreamError | null,
): boolean {
  if (!error?.turnId) return false;
  return messages.some((message) => (
    message.role === "user"
    && message.turnId === error.turnId
    && message.deliveryStatus === "failed"
    && message.deliveryErrorKind === error.kind
  ));
}

const FILE_PREVIEW_DEFAULT_WIDTH = 544;
const FILE_PREVIEW_MIN_WIDTH = 360;
const FILE_PREVIEW_MAX_WIDTH = 860;
const FILE_PREVIEW_MIN_MAIN_WIDTH = 420;
const FILE_PREVIEW_CLOSE_ANIMATION_MS = 320;

type FilePreviewAvailabilityCacheEntry = {
  available?: boolean;
  promise: Promise<boolean>;
  revision: number;
};

function clampFilePreviewWidth(width: number, maxWidth: number): number {
  return Math.min(Math.max(width, FILE_PREVIEW_MIN_WIDTH), maxWidth);
}

function maxFilePreviewWidth(containerWidth: number): number {
  return Math.min(
    containerWidth > 0 ? containerWidth : FILE_PREVIEW_MIN_WIDTH,
    Math.max(
      FILE_PREVIEW_MIN_WIDTH,
      Math.min(FILE_PREVIEW_MAX_WIDTH, containerWidth - FILE_PREVIEW_MIN_MAIN_WIDTH),
    ),
  );
}

const EMPTY_TITLE_OVERRIDES: Record<string, string> = {};

interface ThreadShellProps {
  session: ChatSummary | null;
  sessions?: ChatSummary[];
  titleOverrides?: Record<string, string>;
  title: string;
  temporary?: boolean;
  temporaryChatIds?: readonly string[];
  messageCache?: ThreadMessageCache;
  filePreviewStore?: FilePreviewStore;
  draftStore?: ComposerDraftStore;
  temporaryChatEnabled?: boolean;
  onTemporaryChatEnabledChange?: (enabled: boolean) => void;
  onToggleSidebar: () => void;
  onCreateChat?: (
    workspaceScope?: WorkspaceScopePayload | null,
    initialMessage?: string,
    modelPreset?: string | null,
  ) => Promise<string | null>;
  pendingFirstMessage?: PendingFirstMessage & { id: string; chatId: string } | null;
  onPendingFirstMessageConsumed?: (id: string) => void;
  onForkChat?: (sourceChatId: string, beforeUserIndex: number) => Promise<string | null>;
  onTurnEnd?: () => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
  hideSidebarToggleForHostChrome?: boolean;
  hideSidebarToggle?: boolean;
  hideThemeButton?: boolean;
  hideHeaderTitle?: boolean;
  inlineHandle?: boolean;
  hideHeader?: boolean;
  headerActions?: ReactNode;
  headerPortalTarget?: HTMLElement | null;
  headerActive?: boolean;
  composerPortalTarget?: HTMLElement | null;
  navigationFrame?: HTMLElement | null;
  composerActive?: boolean;
  composerInputAriaLabel?: string;
  emptyComposerVariant?: "hero" | "thread";
  workspaceScope?: WorkspaceScopePayload | null;
  workspaceDefaultScope?: WorkspaceScopePayload | null;
  workspaceControls?: WorkspacesPayload["controls"] | null;
  workspaceScopeDisabled?: boolean;
  workspaceError?: string | null;
  onWorkspaceScopeChange?: (scope: WorkspaceScopePayload) => void;
  settingsSnapshot?: SettingsPayload | null;
  settingsLoading?: boolean;
  onOpenModelSettings?: () => void;
  skills?: SkillSummary[];
}

const HERO_GREETING_KEYS = [
  "thread.empty.greetings.workOn",
  "thread.empty.greetings.start",
  "thread.empty.greetings.build",
  "thread.empty.greetings.tackle",
] as const;

function HeroGreeting({ text }: { text: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const heading = headingRef.current;
    if (!container || !heading) return;

    const fitToWidth = () => {
      heading.style.removeProperty("font-size");
      const availableWidth = container.clientWidth;
      if (availableWidth <= 0) return;

      const naturalWidth = heading.scrollWidth;
      const maximumFontSize = Number.parseFloat(window.getComputedStyle(heading).fontSize);
      if (
        naturalWidth <= availableWidth
        || !Number.isFinite(maximumFontSize)
        || maximumFontSize <= 0
      ) {
        return;
      }

      const fittedFontSize = Math.max(
        12,
        Math.floor(maximumFontSize * ((availableWidth - 2) / naturalWidth) * 100) / 100,
      );
      heading.style.fontSize = `${fittedFontSize}px`;
    };

    fitToWidth();

    let lastObservedWidth = container.clientWidth;
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(([entry]) => {
          const nextWidth = entry?.contentRect.width ?? container.clientWidth;
          if (nextWidth === lastObservedWidth) return;
          lastObservedWidth = nextWidth;
          fitToWidth();
        });
    resizeObserver?.observe(container);
    window.addEventListener("resize", fitToWidth);

    let cancelled = false;
    void document.fonts?.ready.then(() => {
      if (!cancelled) fitToWidth();
    });

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      window.removeEventListener("resize", fitToWidth);
    };
  }, [text]);

  return (
    <div ref={containerRef} className="min-w-0 w-full max-w-[44rem]">
      <h1
        ref={headingRef}
        data-testid="hero-greeting"
        data-theme-ink
        className="select-none whitespace-nowrap text-[34px] font-normal leading-[1.08] tracking-normal text-foreground sm:text-[48px] sm:leading-tight"
      >
        {text}
      </h1>
    </div>
  );
}

function randomHeroGreetingKey(): (typeof HERO_GREETING_KEYS)[number] {
  const index = Math.floor(Math.random() * HERO_GREETING_KEYS.length);
  return HERO_GREETING_KEYS[index] ?? HERO_GREETING_KEYS[0];
}

interface PendingFirstMessage {
  finish?: (accepted: boolean) => void;
  content: string;
  images?: SendAttachment[];
  options?: SendOptions;
}

interface InstalledSettingItemsOptions<Payload, Item> {
  requestCount: number;
  getToken: () => string;
  eventName: string;
  fetchPayload: (token: string) => Promise<Payload>;
  isPayload: (value: unknown) => value is Payload;
  selectItems: (payload: Payload) => Item[];
}

function useInstalledSettingItems<Payload, Item>({
  requestCount,
  getToken,
  eventName,
  fetchPayload,
  isPayload,
  selectItems,
}: InstalledSettingItemsOptions<Payload, Item>): Item[] {
  const [items, setItems] = useState<Item[]>([]);
  const loadedRef = useRef(false);
  const pendingRef = useRef<Promise<Payload> | null>(null);

  useEffect(() => {
    let cancelled = false;
    let refreshQueued = false;
    let refreshAfterFlight = false;
    let refreshing = false;
    let payloadVersion = 0;
    const refresh = async (): Promise<void> => {
      if (refreshing) return;
      refreshing = true;
      const version = payloadVersion;
      const pending = pendingRef.current ?? fetchPayload(getToken());
      pendingRef.current = pending;
      try {
        const payload = await pending;
        if (!cancelled && version === payloadVersion) {
          loadedRef.current = true;
          setItems(selectItems(payload));
        }
      } catch {
        // Keep the last successful catalog during transient refresh failures.
      } finally {
        if (pendingRef.current === pending) pendingRef.current = null;
        refreshing = false;
        if (refreshAfterFlight && !cancelled) {
          refreshAfterFlight = false;
          void refresh();
        }
      }
    };
    const queueRefresh = () => {
      if (!requestCount || document.visibilityState === "hidden" || refreshQueued) return;
      refreshQueued = true;
      queueMicrotask(() => {
        refreshQueued = false;
        if (!cancelled) void refresh();
      });
    };
    if (requestCount && !loadedRef.current) void refresh();

    const refreshOnChanged = (event: Event) => {
      const payload = (event as CustomEvent<unknown>).detail;
      if (isPayload(payload)) {
        payloadVersion += 1;
        loadedRef.current = true;
        setItems(selectItems(payload));
        return;
      }
      if (refreshing) {
        refreshAfterFlight = true;
        return;
      }
      queueRefresh();
    };

    window.addEventListener(eventName, refreshOnChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(eventName, refreshOnChanged);
    };
  }, [requestCount, eventName, fetchPayload, getToken, isPayload, selectItems]);

  return items;
}

export function ThreadShell({
  session,
  sessions = [],
  titleOverrides = EMPTY_TITLE_OVERRIDES,
  title,
  temporary = false,
  temporaryChatIds = [],
  messageCache,
  filePreviewStore,
  draftStore,
  temporaryChatEnabled = false,
  onTemporaryChatEnabledChange,
  onToggleSidebar,
  onCreateChat,
  pendingFirstMessage = null,
  onPendingFirstMessageConsumed,
  onForkChat,
  onTurnEnd,
  theme = "light",
  onToggleTheme = () => {},
  hideSidebarToggleForHostChrome = false,
  hideSidebarToggle = false,
  hideThemeButton = false,
  hideHeaderTitle = false,
  inlineHandle = false,
  hideHeader = false,
  headerActions,
  headerPortalTarget,
  headerActive = true,
  composerPortalTarget,
  navigationFrame,
  composerActive = true,
  composerInputAriaLabel,
  emptyComposerVariant = "hero",
  workspaceScope = null,
  workspaceDefaultScope = null,
  workspaceControls = null,
  workspaceScopeDisabled = false,
  workspaceError = null,
  onWorkspaceScopeChange,
  settingsSnapshot = null,
  settingsLoading = false,
  onOpenModelSettings,
  skills = [],
}: ThreadShellProps) {
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
  const historyKey = temporary ? null : session?.key ?? null;
  const previewSessionKey = session?.key ?? null;
  const mentionSessions = useMemo(
    () => sessions.filter((candidate) => candidate.key !== historyKey).map((candidate) => {
      const renamedTitle = titleOverrides[candidate.key]?.trim();
      return renamedTitle ? { ...candidate, title: renamedTitle } : candidate;
    }),
    [historyKey, sessions, titleOverrides],
  );
  const { client, getToken, ingressLimits, modelName, token, webuiCapabilities } = useClient();
  const favoriteWorkspaceProject = useCallback(
    async (path: string, pinned: boolean) => {
      const response = await client.requestMutation<{ favorite_projects: ProjectDirectory[] }>("workspace.favorite", { path, pinned });
      return response.favorite_projects;
    },
    [client],
  );
  const resolveWorkspaceProject = useCallback(
    (path: string) => client.requestMutation<ProjectDirectory>("workspace.resolve_project", { path }),
    [client],
  );
  const loadWorkspaceProjects = useCallback(() => fetchWorkspaces(getToken()), [getToken]);
  const browseWorkspaceDirectories = useCallback(
    (path: string, query: string, showHidden: boolean, allowPartial = false) =>
      fetchWorkspaceDirectories(getToken(), path, query, showHidden, allowPartial),
    [getToken],
  );
  const [booting, setBooting] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const [mentionCatalogRequestCount, setMentionCatalogRequestCount] = useState(0);
  const requestMentionCatalogs = useCallback(() => setMentionCatalogRequestCount((count) => count + 1), []);
  const cliApps = useInstalledSettingItems({
    requestCount: mentionCatalogRequestCount,
    getToken,
    eventName: CLI_APPS_CHANGED_EVENT,
    fetchPayload: fetchInstalledCliApps,
    isPayload: isCliAppsPayload,
    selectItems: installedCliAppsFromPayload,
  });
  const mcpPresets = useInstalledSettingItems({
    requestCount: mentionCatalogRequestCount,
    getToken,
    eventName: MCP_PRESETS_CHANGED_EVENT,
    fetchPayload: fetchMcpPresets,
    isPayload: isMcpPresetsPayload,
    selectItems: installedMcpPresetsFromPayload,
  });
  const [settings, setSettings] = useState<SettingsPayload | null>(settingsSnapshot);
  const [modelFallback, setModelFallback] = useState<{
    chatId: string;
    model: string;
    reauthProvider?: string;
    dismissed: boolean;
  } | null>(null);
  const [heroGreetingKey, setHeroGreetingKey] = useState(randomHeroGreetingKey);
  const [submittedViewportTurnId, setSubmittedViewportTurnId] = useState<string | null>(null);
  const { state: previewState, openFile, resolveFile, selectTab, closeTab, close: closePreview, setWidth: setFilePreviewWidth } =
    useFilePreviewState(previewSessionKey, filePreviewStore);
  const [closingPreview, setClosingPreview] = useState<{ key: string; state: FilePreviewState } | null>(null);
  const filePreviewClosing = closingPreview?.key === previewSessionKey;
  const visiblePreview = filePreviewClosing ? closingPreview.state : previewState;
  const activePreview = visiblePreview.tabs.find((tab) => tab.id === visiblePreview.activeId);
  const previewOpen = Boolean(activePreview);
  const [filePreviewMaxWidth, setFilePreviewMaxWidth] = useState(FILE_PREVIEW_MAX_WIDTH);
  const filePreviewWidth = clampFilePreviewWidth(previewState.width, filePreviewMaxWidth);
  const draftKey = session?.key ?? (temporaryChatEnabled ? "new:temporary" : "new:chat");
  const persistDraft = session ? !temporary : !temporaryChatEnabled;
  const [quote, setQuote] = useState<{ key: string; text: string | null } | null>(null);
  const quotedContext = quote?.key === draftKey
    ? quote.text
    : draftStore?.get(draftKey, persistDraft)?.quotedContext ?? null;
  const setQuotedContext = useCallback((text: string | null) => {
    setQuote({ key: draftKey, text });
  }, [draftKey]);
  const [composerFocusSignal, setComposerFocusSignal] = useState(0);
  const shellRef = useRef<HTMLElement | null>(null);
  const [conversationElement, setConversationElement] = useState<HTMLDivElement | null>(null);
  const composerSurfaceRef = useRef<HTMLDivElement | null>(null);
  const filePreviewWidthRef = useRef(FILE_PREVIEW_DEFAULT_WIDTH);
  const filePreviewCloseTimerRef = useRef<number | null>(null);
  const filePreviewResizeCleanupRef = useRef<(() => void) | null>(null);
  const pendingFirstRef = useRef<(PendingFirstMessage & { draft?: ComposerDraft; draftKey: string }) | null>(null);
  const [restoredFirstDraft, setRestoredFirstDraft] = useState<{ chatId: string; revision: number; error: string } | null>(null);
  const [pendingFirstTargetChatId, setPendingFirstTargetChatId] = useState<string | null>(null);
  const consumedPendingFirstMessageIdRef = useRef<string | null>(null);
  const viewportRef = useRef<ThreadViewportHandle | null>(null);
  const activeViewportTurnByChatIdRef = useRef<Map<string, string>>(new Map());
  const knownTemporaryChatIdsRef = useRef(new Set<string>());
  const localMessageCacheRef = useRef(new ThreadMessageCache(
    (key) => knownTemporaryChatIdsRef.current.has(key),
  ));
  const messageCacheRef = useRef(messageCache ?? localMessageCacheRef.current);
  messageCacheRef.current = messageCache ?? localMessageCacheRef.current;
  const sessionKeyByChatIdRef = useRef<Map<string, string>>(new Map());
  const handleTurnEnd = useCallback(() => {
    if (chatId) activeViewportTurnByChatIdRef.current.delete(chatId);
    setSubmittedViewportTurnId(null);
    onTurnEnd?.();
  }, [chatId, onTurnEnd]);
  const {
    messages,
    messagesReady,
    isStreaming,
    runStartedAt,
    retryStatus,
    goalState,
    recoveryState,
    continueRecovery,
    dismissRecovery,
    send,
    transcribeAudio,
    stop,
    history: {
      loading,
      error: historyError,
      loadingOlder,
      olderError,
      hasMoreBefore,
      userMessageOffset,
      hasPendingToolCalls,
      completedTurnIds,
      activeTurnId: historyActiveTurnId,
      version: historyVersion,
      forkBoundaryMessageCount,
    },
    refreshHistory,
    loadOlder,
    loadTraceDetails: loadBodyTraceDetails,
    streamError,
    dismissStreamError,
  } = useNanobotStream(
    chatId, undefined, false, handleTurnEnd, undefined, undefined,
    { key: historyKey, cache: messageCacheRef.current },
  );
  const displayMessages = useMemo(() => projectWebuiThreadMessages(messages), [messages]);
  const initialHistoryLoading = loading;
  const showTemporaryChatControl =
    !hideHeader && !session && !loading && !!onTemporaryChatEnabledChange;
  const promptNavigation = usePromptHistory(historyKey, historyVersion, displayMessages);
  const updateNavigationMessages = promptNavigation.updateMessages;
  useEffect(() => {
    if (!chatId || !messagesReady) return;
    messageCacheRef.current.setLoadedMessages(chatId, promptNavigation.window
      ? [displayMessages, promptNavigation.window.messages] : [displayMessages]);
  }, [chatId, messagesReady, displayMessages, promptNavigation.window]);
  useEffect(() => {
    const cache = messageCacheRef.current;
    return () => { if (chatId) cache.deleteLoadedMessages(chatId); };
  }, [chatId]);

  const loadTraceDetails = useCallback(async (refs: string[]) => {
    const details = await loadBodyTraceDetails(refs);
    for (const detail of details) {
      const projected = projectThreadEvents(detail.events);
      updateNavigationMessages((current) => current.flatMap((message) => (
        message.traceDetail?.ref === detail.ref
          ? projected.map((row) => ({ ...row, activitySegmentId: message.activitySegmentId }))
          : [message]
      )));
    }
  }, [loadBodyTraceDetails, updateNavigationMessages]);

  useEffect(() => {
    if (chatId && historyKey) sessionKeyByChatIdRef.current.set(chatId, historyKey);
  }, [chatId, historyKey]);

  useEffect(() => {
    filePreviewWidthRef.current = filePreviewWidth;
  }, [filePreviewWidth]);

  useEffect(() => {
    filePreviewResizeCleanupRef.current?.();
    if (filePreviewCloseTimerRef.current !== null) {
      window.clearTimeout(filePreviewCloseTimerRef.current);
      filePreviewCloseTimerRef.current = null;
    }
    setClosingPreview(null);
    setSubmittedViewportTurnId(null);
  }, [previewSessionKey]);

  useEffect(() => {
    const retained = new Set(temporaryChatIds);
    for (const chatId of retained) knownTemporaryChatIdsRef.current.add(chatId);
    for (const cachedChatId of knownTemporaryChatIdsRef.current) {
      if (!retained.has(cachedChatId)) {
        // Shared caches are retained/pruned by the app, not by individual panes.
        if (!messageCache) messageCacheRef.current.delete(cachedChatId);
        activeViewportTurnByChatIdRef.current.delete(cachedChatId);
        knownTemporaryChatIdsRef.current.delete(cachedChatId);
      }
    }
  }, [messageCache, temporaryChatIds]);

  const handleQuoteSelection = useCallback((text: string) => {
    setQuotedContext(text);
    setComposerFocusSignal((value) => value + 1);
  }, [setQuotedContext]);

  useEffect(() => {
    return () => {
      filePreviewResizeCleanupRef.current?.();
      if (filePreviewCloseTimerRef.current !== null) {
        window.clearTimeout(filePreviewCloseTimerRef.current);
      }
    };
  }, []);

  const hasAppMentions = displayMessages.some((message) => message.cliApps?.length || message.mcpPresets?.length);
  useEffect(() => {
    if (hasAppMentions) requestMentionCatalogs();
  }, [hasAppMentions, requestMentionCatalogs]);
  const composerContextUsage = useMemo(
    () => latestComposerContextUsage(displayMessages),
    [displayMessages],
  );
  const composerRoundUsage = useMemo(
    () => recentComposerRoundUsage(displayMessages),
    [displayMessages],
  );
  const currentGoalState = messagesReady ? goalState : undefined;
  // Recovery decisions gate queued input, not the ledger-owned run state.
  const recoveryNeedsDecision = recoveryState?.status === "awaiting_user"
    || recoveryState?.status === "failed";
  const currentRunStartedAt = messagesReady ? runStartedAt : null;
  const turnActive = messagesReady && isStreaming;
  const restoredViewportTurnId = useMemo(
    () => turnActive ? latestActiveTurnId(displayMessages, currentRunStartedAt) : null,
    [currentRunStartedAt, displayMessages, turnActive],
  );
  const rememberedViewportTurnId = chatId
    ? activeViewportTurnByChatIdRef.current.get(chatId) ?? null
    : null;
  const canonicalRunTurnId = chatId && messagesReady && turnActive
    ? client.getRunTurnId(chatId)
    : null;
  const viewportTurnId = messagesReady && turnActive
    ? canonicalRunTurnId
      ?? rememberedViewportTurnId
      ?? historyActiveTurnId
      ?? restoredViewportTurnId
    : null;
  const activeTurnStartedHere =
    viewportTurnId !== null && viewportTurnId === submittedViewportTurnId;
  useEffect(() => {
    if (!chatId || !messagesReady || turnActive) return;
    activeViewportTurnByChatIdRef.current.delete(chatId);
    setSubmittedViewportTurnId((current) =>
      current === rememberedViewportTurnId ? null : current,
    );
  }, [chatId, messagesReady, rememberedViewportTurnId, turnActive]);
  const filePreviewAvailabilityCache = useMemo(
    () => new Map<string, FilePreviewAvailabilityCacheEntry>(),
    [previewSessionKey],
  );
  const filePreviewAvailabilityRevision = displayMessages.length;
  const resolveFilePreviewAvailability = useCallback((path: string) => {
    if (!previewSessionKey) return Promise.resolve(false);
    const cached = filePreviewAvailabilityCache.get(path);
    if (
      cached
      && (cached.available !== false || cached.revision === filePreviewAvailabilityRevision)
    ) {
      return cached.promise;
    }
    const request = temporary
      ? client.requestMutation<{ available: boolean }>("temporary_chat.file_preview", {
          chat_id: chatId, path, probe: true,
        }).then((result) => result.available)
      : fetchFilePreviewAvailability(getToken(), previewSessionKey, path);
    const pending = request.catch(
      (error: unknown) => {
        if (error instanceof ApiError) {
          if (error.status === 404 && /API route not found/i.test(error.message)) {
            return true;
          }
          if ([400, 403, 404, 413, 415].includes(error.status)) return false;
        }
        return false;
      },
    );
    const entry: FilePreviewAvailabilityCacheEntry = {
      promise: pending,
      revision: filePreviewAvailabilityRevision,
    };
    filePreviewAvailabilityCache.set(path, entry);
    void pending.then((available) => {
      if (filePreviewAvailabilityCache.get(path) === entry) {
        entry.available = available;
      }
    });
    return pending;
  }, [
    filePreviewAvailabilityCache,
    filePreviewAvailabilityRevision,
    getToken,
    previewSessionKey,
    temporary,
    client,
    chatId,
  ]);

  const showHeroComposer = displayMessages.length === 0 && !initialHistoryLoading;
  const composerVariant = showHeroComposer ? emptyComposerVariant : "thread";
  // The server owns the project lock. Old servers have no marker, so an existing
  // user turn is read-only here too; the gateway remains the editing authority.
  const projectLocked = session?.projectLocked === true
    || (session?.projectLocked === undefined && displayMessages.some((message) => message.role === "user" && message.deliveryStatus !== "failed"));
  const wasShowingHeroComposerRef = useRef(showHeroComposer);
  const sessionModelPreset = session?.modelPreset?.trim() || null;
  const [localModelPreset, setLocalModelPreset] = useState<string | null>(null);
  useEffect(() => {
    setLocalModelPreset(null);
  }, [session?.key, sessionModelPreset]);
  const configuredPresetNames = useMemo(
    () => new Set(settings?.model_presets.map((preset) => preset.name) ?? []),
    [settings],
  );
  const activeModelPreset = (
    (localModelPreset && (!settings || configuredPresetNames.has(localModelPreset))
      ? localModelPreset
      : null)
    || (sessionModelPreset && (!settings || configuredPresetNames.has(sessionModelPreset))
      ? sessionModelPreset
      : null)
    || settings?.agent.model_preset
    || "default"
  );
  useEffect(() => {
    setModelFallback(null);
    if (!chatId) return;
    return client.onChat(chatId, (event) => {
      if (event.event !== "turn_model_updated") return;
      if (event.fallback !== true) {
        // The next turn starts with its configured model, not the previous fallback.
        setModelFallback(null);
        return;
      }
      const model = event.model_name.trim();
      if (!model) return;
      const reauthProvider = typeof event.reauth_provider === "string"
        ? event.reauth_provider.trim() || undefined : undefined;
      // A tool loop may report the same fallback repeatedly. Closing the notice
      // lasts until the next turn/model change, without changing the actual preset.
      setModelFallback((current) => {
        if (current?.chatId === chatId && current.model === model) {
          // An explicit auth rejection is actionable even after dismissing a
          // generic fallback. A circuit-skipped call must not erase that reason.
          return reauthProvider && reauthProvider !== current.reauthProvider
            ? { ...current, reauthProvider, dismissed: false } : current;
        }
        return { chatId, model, reauthProvider, dismissed: false };
      });
    });
  }, [activeModelPreset, chatId, client]);
  const handleModelPresetChange = useCallback((name: string) => {
    setLocalModelPreset(name);
    if (chatId) {
      void client.sendSystemCommand(chatId, `/model ${name}`).catch(() => {});
    }
  }, [chatId, client]);
  const modelPresetOptions = useMemo(
    () => modelPresetOptionsFromSettings(settings),
    [settings],
  );
  const availableSlashCommands = useMemo(
    () => temporary
      ? slashCommands.filter(({ command }) => command === "/model" || command === "/stop")
      : slashCommands,
    [slashCommands, temporary],
  );
  const modelBadge = useMemo(
    () => toModelBadgeInfo(modelName, settings, activeModelPreset),
    [activeModelPreset, modelName, settings],
  );
  const modelBadgeLabel = modelBadge.needsSetup
    ? t("thread.composer.chooseAI", { defaultValue: "Choose your AI" })
    : modelBadge.label;
  useEffect(() => {
    if (showHeroComposer && !wasShowingHeroComposerRef.current) {
      setHeroGreetingKey(randomHeroGreetingKey());
    }
    wasShowingHeroComposerRef.current = showHeroComposer;
  }, [showHeroComposer]);

  const withWorkspaceScope = useCallback(
    (options?: SendOptions): SendOptions | undefined => {
      if (!workspaceScope) return options;
      return {
        ...(options ?? {}),
        workspaceScope,
      };
    },
    [workspaceScope],
  );

  const refreshModelSettings = useCallback(async () => {
    try {
      setSettings(await fetchSettings(getToken()));
    } catch {
      if (!settingsSnapshot) setSettings(null);
    }
  }, [getToken, settingsSnapshot]);

  useEffect(() => {
    if (settingsSnapshot) {
      setSettings(settingsSnapshot);
      return;
    }
    if (!settingsLoading) void refreshModelSettings();
  }, [refreshModelSettings, settingsLoading, settingsSnapshot]);

  useEffect(() => {
    return client.onRuntimeModelUpdate(() => {
      void refreshModelSettings();
    });
  }, [client, refreshModelSettings]);

  const lastRunTurnId = chatId ? client.getRunTurnId(chatId) : null;
  const completedRunTurnId = chatId && lastRunTurnId && client.isRunCompleted(chatId, lastRunTurnId)
    ? lastRunTurnId : null;
  const queueCompletedTurnIds = useMemo(() => {
    const canonical = hasPendingToolCalls ? [] : completedTurnIds;
    // Live terminal facts can release the queue before the history refresh finishes.
    return completedRunTurnId && !canonical.includes(completedRunTurnId)
      ? [...canonical, completedRunTurnId] : canonical;
  }, [completedTurnIds, completedRunTurnId, hasPendingToolCalls]);

  useEffect(() => {
    if (!historyKey || !chatId) return;
    return client.onSessionUpdate((updatedChatId, scope) => {
      if (updatedChatId !== chatId) return;
      if (scope === "metadata") return;
      // A turn-end thread refresh can arrive while the viewport is easing the
      // final layout change. User-driven scrolling already disables following,
      // so keep an active programmatic follow alive across canonical hydration.
      refreshHistory();
    });
  }, [chatId, client, historyKey, refreshHistory]);

  const wasPageHiddenRef = useRef(document.visibilityState === "hidden");
  useEffect(() => {
    const refreshOnReturn = () => {
      if (document.visibilityState === "hidden") {
        wasPageHiddenRef.current = true;
        return;
      }
      if (!wasPageHiddenRef.current) return;
      wasPageHiddenRef.current = false;
      if (!historyKey || !chatId || client.status !== "open" || loading) return;
      if (
        !turnActive
        && !hasPendingToolCalls
        && !client.hasUnsettledRun(chatId)
        && !historyError
      ) {
        return;
      }
      refreshHistory();
    };
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => document.removeEventListener("visibilitychange", refreshOnReturn);
  }, [
    chatId,
    client,
    hasPendingToolCalls,
    historyKey,
    historyError,
    loading,
    refreshHistory,
    turnActive,
  ]);

  useEffect(() => {
    let refreshOnNextOpen = client.status !== "open";
    return client.onStatus((status) => {
      if (status !== "open") {
        refreshOnNextOpen = true;
        return;
      }
      if (refreshOnNextOpen) refreshHistory();
      refreshOnNextOpen = false;
    });
  }, [client, refreshHistory]);

  // The landing composer queues the first message while `new_chat` is in flight.
  // Only the chat created for that send may consume it; selecting another chat
  // while creation is pending must not leak the message there.
  useEffect(() => {
    if (!chatId || pendingFirstTargetChatId !== chatId) return;
    const pending = pendingFirstRef.current;
    if (!pending) {
      setPendingFirstTargetChatId(null);
      return;
    }
    pendingFirstRef.current = null;
    setPendingFirstTargetChatId(null);
    const submitted = send(pending.content, pending.images, pending.options);
    if (submitted && !submitted.sideChannel) {
      activeViewportTurnByChatIdRef.current.set(chatId, submitted.turnId);
      setSubmittedViewportTurnId(submitted.turnId);
    }
    if (submitted?.delivery) {
      void submitted.delivery.then(() => pending.finish?.(true), (error: unknown) => {
        // Topic creation already unmounted the landing composer. A rejected
        // local reference must hand its draft to that topic, not strand it on /new.
        if (pending.draft && pending.images?.some((image) => image.media.path !== undefined)) {
          const targetKey = `websocket:${chatId}`;
          const current = draftStore?.get(targetKey, !temporary);
          if (!current?.text && !current?.attachments.length
            && !current?.sessionMentions.length && !current?.quotedContext) {
            draftStore?.set(targetKey, pending.draft, !temporary);
            if (draftStore?.get(pending.draftKey) === pending.draft) draftStore.delete(pending.draftKey);
            setRestoredFirstDraft((previous) => ({
              chatId, revision: (previous?.revision ?? 0) + 1,
              error: error instanceof Error ? error.message : String(error),
            }));
          }
        }
        pending.finish?.(false);
      });
    } else pending.finish?.(submitted !== null);
    setBooting(false);
  }, [chatId, draftStore, pendingFirstTargetChatId, send, temporary]);

  useEffect(() => {
    if (
      !chatId
      || pendingFirstMessage?.chatId !== chatId
      || consumedPendingFirstMessageIdRef.current === pendingFirstMessage.id
    ) return;
    consumedPendingFirstMessageIdRef.current = pendingFirstMessage.id;
    const submitted = send(
      pendingFirstMessage.content,
      pendingFirstMessage.images,
      withWorkspaceScope(pendingFirstMessage.options),
    );
    if (submitted && !submitted.sideChannel) {
      activeViewportTurnByChatIdRef.current.set(chatId, submitted.turnId);
      setSubmittedViewportTurnId(submitted.turnId);
    }
    onPendingFirstMessageConsumed?.(pendingFirstMessage.id);
  }, [
    chatId,
    onPendingFirstMessageConsumed,
    pendingFirstMessage,
    send,
    withWorkspaceScope,
  ]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const commands = await listSlashCommands(getToken());
        if (!cancelled) setSlashCommands(commands);
      } catch {
        if (!cancelled) setSlashCommands([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  const handleWelcomeSend = useCallback(
    async (content: string, images?: SendAttachment[], options?: SendOptions) => {
      if (booting) return false;
      setBooting(true);
      let finish!: (accepted: boolean) => void;
      const delivery = new Promise<boolean>((resolve) => { finish = resolve; });
      pendingFirstRef.current = {
        content, images, options: withWorkspaceScope(options), finish,
        draftKey, draft: draftStore?.get(draftKey, persistDraft),
      };
      setPendingFirstTargetChatId(null);
      const newId = await onCreateChat?.(workspaceScope, content, localModelPreset);
      if (!newId) {
        pendingFirstRef.current = null;
        setPendingFirstTargetChatId(null);
        setBooting(false);
        return false;
      }
      if (localModelPreset) {
        await client.sendSystemCommand(newId, `/model ${localModelPreset}`).catch(() => {});
      }
      setPendingFirstTargetChatId(newId);
      return delivery;
    },
    [booting, client, draftKey, draftStore, localModelPreset, onCreateChat, persistDraft, withWorkspaceScope, workspaceScope],
  );

  const inspectAttachment = useCallback(async (path: string) => {
    const result = await client.requestMutation("attachment.inspect", {
      chat_id: chatId, path, ...(workspaceScope ? { workspace_scope: workspaceScope } : {}),
    });
    if (!isLocalAttachment(result)) throw new Error("Invalid attachment metadata");
    return result;
  }, [chatId, client, workspaceScope]);

  const handleThreadSend = useCallback(
    (content: string, images?: SendAttachment[], options?: SendOptions) => {
      setRestoredFirstDraft((current) => current?.chatId === chatId ? { ...current, error: "" } : current);
      const submitted = send(content, images, withWorkspaceScope(options));
      if (
        chatId
        && submitted
        && !submitted.sideChannel
        && options?.continueActiveTurn !== true
      ) {
        activeViewportTurnByChatIdRef.current.set(chatId, submitted.turnId);
        setSubmittedViewportTurnId(submitted.turnId);
      }
      return submitted?.delivery ? submitted.delivery.then(() => true) : submitted !== null;
    },
    [chatId, send, withWorkspaceScope],
  );

  const loadTemporaryFilePreview = useCallback((path: string) =>
    client.requestMutation<FilePreviewPayload>("temporary_chat.file_preview", {
      chat_id: chatId, path,
    }).catch((error: unknown) => {
      if (error instanceof Error && "status" in error && typeof error.status === "number") {
        throw new ApiError(error.status, error.message);
      }
      throw error;
    }), [client, chatId]);

  const handleCloseFilePreview = useCallback(() => {
    if (!previewSessionKey || !previewState.activeId || filePreviewClosing) return;
    filePreviewResizeCleanupRef.current?.();
    setClosingPreview({ key: previewSessionKey, state: previewState });
    // Record the closed state immediately, even if navigation interrupts the animation.
    closePreview();
    filePreviewCloseTimerRef.current = window.setTimeout(() => {
      filePreviewCloseTimerRef.current = null;
      setClosingPreview(null);
    }, FILE_PREVIEW_CLOSE_ANIMATION_MS);
  }, [previewSessionKey, filePreviewClosing, previewState, closePreview]);

  const cancelPreviewClose = useCallback(() => {
    filePreviewResizeCleanupRef.current?.();
    if (filePreviewCloseTimerRef.current !== null) {
      window.clearTimeout(filePreviewCloseTimerRef.current);
      filePreviewCloseTimerRef.current = null;
    }
    setClosingPreview(null);
  }, []);

  const handleOpenFilePreview = useCallback((path: string) => {
    cancelPreviewClose();
    openFile(path);
  }, [cancelPreviewClose, openFile]);

  const handleClosePreviewTab = useCallback((id: string) => {
    if (previewState.tabs.length === 1) handleCloseFilePreview();
    else {
      filePreviewResizeCleanupRef.current?.();
      closeTab(id);
    }
  }, [previewState.tabs.length, handleCloseFilePreview, closeTab]);

  // Markdown blocks can retain rendered links while their text is unchanged.
  // Keep their callback stable, but always act on the current pane/session state.
  const openFilePreviewRef = useRef(handleOpenFilePreview);
  openFilePreviewRef.current = handleOpenFilePreview;
  const openFilePreview = useCallback((path: string) => openFilePreviewRef.current(path), []);
  const resolveFileMetadata = useCallback((path: string) => {
    if (!previewSessionKey) return Promise.reject(new Error("No active session"));
    return temporary
      ? client.requestMutation<FileReferenceMetadata>("temporary_chat.file_preview", {
        chat_id: chatId, path, metadata: true,
      })
      : fetchFileReferenceMetadata(getToken(), previewSessionKey, path);
  }, [chatId, client, getToken, previewSessionKey, temporary]);
  const loadFilePreview = useCallback((path: string) => {
    if (!previewSessionKey) return Promise.reject(new Error("No active session"));
    return temporary ? loadTemporaryFilePreview(path) : fetchFilePreview(getToken(), previewSessionKey, path);
  }, [previewSessionKey, temporary, loadTemporaryFilePreview, getToken]);
  const filePreviews = useMemo(() => createFilePreviewResource(loadFilePreview), [loadFilePreview]);
  const fileActions = useMemo(() => ({
    resolveMetadata: resolveFileMetadata,
    loadPreview: filePreviews.load,
  }), [resolveFileMetadata, filePreviews]);

  useEffect(() => {
    if (!previewOpen || !headerActive) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      // Let a dialog/menu above the pane consume Escape without closing this preview.
      if (document.querySelector('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [data-radix-popper-content-wrapper]')) return;
      event.preventDefault();
      handleCloseFilePreview();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewOpen, headerActive, handleCloseFilePreview]);

  const handleFilePreviewResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    filePreviewResizeCleanupRef.current?.();
    event.preventDefault();
    event.stopPropagation();
    const panel = event.currentTarget.closest<HTMLElement>("[data-file-preview-panel]");
    const shellRect = shellRef.current?.getBoundingClientRect();
    const rightEdge = shellRect?.right ?? window.innerWidth;
    const maxWidth = maxFilePreviewWidth(shellRect?.width ?? window.innerWidth);
    const originalBodyCursor = document.body.style.cursor;
    const originalBodyUserSelect = document.body.style.userSelect;
    const originalPanelTransition = panel?.style.transition ?? "";
    const frameElement = panel?.querySelector("iframe");
    const originalFramePointerEvents = frameElement?.style.pointerEvents ?? "";
    let nextWidth = filePreviewWidthRef.current;
    let frame: number | null = null;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    if (panel) panel.style.transition = "none";
    if (frameElement) frameElement.style.pointerEvents = "none";

    const applyWidth = (clientX: number) => {
      nextWidth = clampFilePreviewWidth(rightEdge - clientX, maxWidth);
      filePreviewWidthRef.current = nextWidth;
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        panel?.style.setProperty("--file-preview-width", `${nextWidth}px`);
        panel?.style.setProperty("--file-preview-slot-width", `${nextWidth}px`);
      });
    };
    const handlePointerMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      applyWidth(moveEvent.clientX);
    };
    const stopResize = (commit: boolean) => {
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
        frame = null;
      }
      panel?.style.setProperty("--file-preview-width", `${nextWidth}px`);
      panel?.style.setProperty("--file-preview-slot-width", `${nextWidth}px`);
      if (panel) panel.style.transition = originalPanelTransition;
      if (frameElement) frameElement.style.pointerEvents = originalFramePointerEvents;
      if (commit) setFilePreviewWidth(nextWidth);
      document.body.style.cursor = originalBodyCursor;
      document.body.style.userSelect = originalBodyUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
      filePreviewResizeCleanupRef.current = null;
    };
    const handlePointerUp = () => stopResize(true);
    filePreviewResizeCleanupRef.current = () => stopResize(false);

    applyWidth(event.clientX);
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  }, [setFilePreviewWidth]);

  useEffect(() => {
    if (!previewOpen) return;
    const clampToShell = () => {
      const shellWidth = shellRef.current?.getBoundingClientRect().width ?? window.innerWidth;
      const maxWidth = maxFilePreviewWidth(shellWidth);
      setFilePreviewMaxWidth(maxWidth);
    };
    clampToShell();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(clampToShell);
    if (shellRef.current) observer?.observe(shellRef.current);
    window.addEventListener("resize", clampToShell);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", clampToShell);
    };
  }, [previewOpen]);

  const handleForkFromMessage = useCallback(
    async (beforeUserIndex: number) => {
      if (!chatId || !onForkChat) return;
      const forkedChatId = await onForkChat(chatId, beforeUserIndex);
      if (!forkedChatId) return;
      messageCacheRef.current.delete(forkedChatId);
    },
    [chatId, onForkChat],
  );

  const composer = (
    <div className={composerVariant === "hero" ? "thread-composer-stack is-hero" : "thread-composer-stack"}>
      {modelFallback?.chatId === chatId && !modelFallback.dismissed ? (
        <ModelFallbackNotice
          model={modelFallback.model}
          reauthProvider={modelFallback.reauthProvider}
          reauthProviderLabel={modelFallback.reauthProvider
            ? providerDisplayLabel(settings?.providers ?? [], modelFallback.reauthProvider)
            : undefined}
          onOpenSettings={onOpenModelSettings}
          onDismiss={() => setModelFallback((current) => current && { ...current, dismissed: true })}
        />
      ) : null}
      {recoveryState ? (
        <RecoveryNotice
          state={recoveryState}
          onContinue={continueRecovery}
          onDismiss={dismissRecovery}
          onOpenSettings={onOpenModelSettings}
        />
      ) : null}
      {streamError && !hasInlineDeliveryError(messages, streamError) ? (
        <StreamErrorNotice
          error={streamError}
          onDismiss={dismissStreamError}
          onOpenSettings={onOpenModelSettings}
        />
      ) : null}
      {restoredFirstDraft?.chatId === chatId && restoredFirstDraft.error ? (
        <p role="alert" className="px-3 text-sm text-destructive">{restoredFirstDraft.error}</p>
      ) : null}
      <SubagentTaskDock inputKey={latestSubagentInputKey(displayMessages)} />
      {session ? (
        <ThreadComposer
          key={`${draftKey}:${restoredFirstDraft?.chatId === chatId ? restoredFirstDraft.revision : 0}`}
          draftKey={draftKey}
          draftStore={draftStore}
          persistDraft={persistDraft}
          onSend={handleThreadSend}
          disabled={!chatId}
          inputAriaLabel={composerInputAriaLabel}
          isStreaming={turnActive}
          activeTurnId={turnActive && chatId ? client.getRunTurnId(chatId) ?? historyActiveTurnId : null}
          completedTurnIds={messagesReady && !recoveryNeedsDecision
            && chatId && !client.hasUnsettledRun(chatId) ? queueCompletedTurnIds : undefined}
          placeholder={
            composerVariant === "hero"
              ? t("thread.composer.placeholderHero")
              : t("thread.composer.placeholderThread")
          }
          modelLabel={modelBadgeLabel}
          modelDetail={modelBadge.model}
          modelPreset={activeModelPreset}
          modelPresets={modelPresetOptions}
          onModelPresetChange={handleModelPresetChange}
          modelProvider={modelBadge.provider}
          modelProviderLabel={modelBadge.providerLabel}
          modelNeedsSetup={modelBadge.needsSetup}
          onModelBadgeClick={modelBadge.needsSetup ? onOpenModelSettings : undefined}
          onManageModels={onOpenModelSettings}
          contextUsage={composerContextUsage}
          recentRoundUsage={composerRoundUsage}
          variant={composerVariant}
          slashCommands={availableSlashCommands}
          onMentionSearch={requestMentionCatalogs}
          cliApps={cliApps}
          mcpPresets={mcpPresets}
          sessions={mentionSessions}
          skills={skills}
          onStop={stop}
          onInspectAttachment={inspectAttachment}
          onTranscribeAudio={transcribeAudio}
          goalState={currentGoalState}
          onFavoriteWorkspaceProject={favoriteWorkspaceProject}
          onResolveWorkspaceProject={resolveWorkspaceProject}
          onLoadWorkspaceProjects={loadWorkspaceProjects}
          workspacePickerLayoutAnchor={conversationElement}
          onBrowseWorkspaceDirectories={browseWorkspaceDirectories}
          workspaceScope={workspaceScope}
          workspaceControlsHidden={temporary}
          workspaceDefaultScope={workspaceDefaultScope}
          workspaceControls={workspaceControls}
          workspaceScopeDisabled={workspaceScopeDisabled}
          workspaceProjectLocked={projectLocked}
          workspaceError={workspaceError}
          onWorkspaceScopeChange={onWorkspaceScopeChange}
          pendingQueueKey={temporary ? null : chatId}
          transcriptionProvider={settingsSnapshot?.transcription?.provider}
          ingressLimits={ingressLimits}
          quotedContext={quotedContext}
          focusRequest={composerFocusSignal}
          onQuotedContextChange={setQuotedContext}
        />
      ) : (
        <ThreadComposer
          key={draftKey}
          draftKey={draftKey}
          draftStore={draftStore}
          persistDraft={persistDraft}
          onSend={handleWelcomeSend}
          disabled={booting}
          inputAriaLabel={composerInputAriaLabel}
          isStreaming={turnActive}
          placeholder={
            booting
              ? t("thread.composer.placeholderOpening")
              : t("thread.composer.placeholderHero")
          }
          modelLabel={modelBadgeLabel}
          modelDetail={modelBadge.model}
          modelPreset={activeModelPreset}
          modelPresets={modelPresetOptions}
          onModelPresetChange={handleModelPresetChange}
          modelProvider={modelBadge.provider}
          modelProviderLabel={modelBadge.providerLabel}
          modelNeedsSetup={modelBadge.needsSetup}
          onModelBadgeClick={modelBadge.needsSetup ? onOpenModelSettings : undefined}
          onManageModels={onOpenModelSettings}
          contextUsage={composerContextUsage}
          recentRoundUsage={composerRoundUsage}
          variant="hero"
          slashCommands={availableSlashCommands}
          onMentionSearch={requestMentionCatalogs}
          cliApps={cliApps}
          mcpPresets={mcpPresets}
          sessions={mentionSessions}
          skills={skills}
          surfaceRef={composerSurfaceRef}
          onInspectAttachment={inspectAttachment}
          onTranscribeAudio={transcribeAudio}
          goalState={currentGoalState}
          onFavoriteWorkspaceProject={favoriteWorkspaceProject}
          onResolveWorkspaceProject={resolveWorkspaceProject}
          onLoadWorkspaceProjects={loadWorkspaceProjects}
          workspacePickerLayoutAnchor={conversationElement}
          onBrowseWorkspaceDirectories={browseWorkspaceDirectories}
          workspaceScope={workspaceScope}
          workspaceControlsHidden={temporary}
          workspaceDefaultScope={workspaceDefaultScope}
          workspaceControls={workspaceControls}
          workspaceScopeDisabled={workspaceScopeDisabled}
          workspaceProjectLocked={projectLocked}
          workspaceError={workspaceError}
          onWorkspaceScopeChange={onWorkspaceScopeChange}
          transcriptionProvider={settingsSnapshot?.transcription?.provider}
          ingressLimits={ingressLimits}
          quotedContext={quotedContext}
          onQuotedContextChange={setQuotedContext}
        />
      )}
    </div>
  );

  const emptyState = initialHistoryLoading ? (
    <ThreadLoadingSkeleton />
  ) : (
    <div className="flex w-full flex-col items-center text-center animate-in fade-in-0 slide-in-from-bottom-2 [animation-duration:220ms] motion-reduce:animate-none">
      <HeroGreeting text={t(heroGreetingKey)} />
    </div>
  );
  const sessionInfoAction = historyKey ? (
    <SessionInfoPopover client={client} sessionKey={historyKey} token={token} title={title} />
  ) : undefined;
  const promptNavigatorAction = historyKey ? (
    <PromptNavigator
      messages={displayMessages}
      prompts={promptNavigation.prompts}
      onJumpToPrompt={(promptId) => viewportRef.current?.jumpToUserPrompt(promptId)}
    />
  ) : undefined;

  const threadHeader = !hideHeader ? (
    <ThreadHeader
      className={previewOpen ? "h-10" : undefined}
      title={title}
      onToggleSidebar={onToggleSidebar}
      theme={theme}
      onToggleTheme={onToggleTheme}
      hideSidebarToggleForHostChrome={hideSidebarToggleForHostChrome}
      hideSidebarToggle={hideSidebarToggle}
      hideThemeButton={hideThemeButton}
      hideTitle={hideHeaderTitle}
      actions={headerActions}
      minimal={!session && !loading}
      promptNavigatorAction={promptNavigatorAction}
      sessionInfoAction={sessionInfoAction}
      temporaryChatEnabled={temporaryChatEnabled}
      temporaryChatDisabled={booting || turnActive}
      onTemporaryChatEnabledChange={
        showTemporaryChatControl ? onTemporaryChatEnabledChange : undefined
      }
    />
  ) : null;

  return (
    <SubagentTasksProvider client={client} token={token}
      sessionKey={session?.key ?? null}
      liveEvents={webuiCapabilities.includes("webui.subagents.events.v1")}
      historyEnabled={webuiCapabilities.includes("webui.subagents.history.v1")}
      active={composerActive}
      enabled={!temporary && !!session?.key.startsWith("websocket:") && webuiCapabilities.includes("webui.subagents.v1")}>
    <section ref={shellRef} data-preview-open={previewOpen || undefined} className="thread-preview-layout relative flex min-h-0 flex-1 overflow-hidden">
      <div ref={setConversationElement} className={cn(
        "thread-conversation relative flex min-w-0 flex-1 flex-col overflow-hidden",
        headerPortalTarget === undefined && !hideHeader && "thread-workspace",
      )}>
        {hideHeaderTitle && inlineHandle && !temporary && session?.handle ? (
          <div
            aria-label={`Session @${session.handle.name}`}
            className="flex h-8 shrink-0 items-center px-3 text-[12px]"
          >
            <span
              className="shrink-0"
            >
              <SessionHandleLabel id={session.handle.id}>
                @{session.handle.name}
              </SessionHandleLabel>
            </span>
          </div>
        ) : null}
        {headerPortalTarget === undefined ? threadHeader : null}
        <FilePreviewAvailabilityProvider
          resolve={previewSessionKey ? resolveFilePreviewAvailability : undefined}
        >
          <FileActionsProvider value={previewSessionKey ? fileActions : undefined}>
          <ThreadViewport
            ref={viewportRef}
            messages={displayMessages}
            navigation={promptNavigation}
            navigationFrame={navigationFrame}
            temporary={temporary}
            isStreaming={turnActive}
            runStartedAt={currentRunStartedAt}
            retryStatus={retryStatus}
            emptyState={emptyState}
            initialLoading={initialHistoryLoading}
            composer={composerPortalTarget === undefined ? composer : null}
            activeTurnId={viewportTurnId}
            activeTurnStartedHere={activeTurnStartedHere}
            conversationKey={historyKey}
            conversationReady={messagesReady}
            showScrollToBottomButton={!!session}
            cliApps={cliApps}
            mcpPresets={mcpPresets}
            slashCommands={availableSlashCommands}
            forkBoundaryMessageCount={forkBoundaryMessageCount}
            hasMoreBefore={hasMoreBefore}
            loadingOlder={loadingOlder}
            olderError={olderError}
            userMessageOffset={userMessageOffset}
            onLoadOlder={loadOlder}
            traceDetailScope={historyKey}
            onLoadTraceDetails={messagesReady ? loadTraceDetails : undefined}
            onOpenFilePreview={previewSessionKey ? openFilePreview : undefined}
            onForkFromMessage={onForkChat ? handleForkFromMessage : undefined}
            onQuoteSelection={session ? handleQuoteSelection : undefined}
          />
          </FileActionsProvider>
        </FilePreviewAvailabilityProvider>
      </div>
      {headerPortalTarget && headerActive
        ? createPortal(threadHeader, headerPortalTarget)
        : null}
      {composerPortalTarget ? createPortal(
        <div
          hidden={!composerActive}
          aria-hidden={!composerActive}
          data-testid={composerActive ? "active-pane-composer" : undefined}
        >
          {composer}
        </div>,
        composerPortalTarget,
      ) : null}
      {activePreview && previewSessionKey ? (
        <FileActionsProvider key={previewSessionKey} value={fileActions}>
        <PreviewPane
          key={previewSessionKey}
          tabs={visiblePreview.tabs}
          activeId={activePreview.id}
          width={filePreviewWidth}
          isClosing={filePreviewClosing}
          onSelect={selectTab}
          onCloseTab={handleClosePreviewTab}
          onClose={handleCloseFilePreview}
          onResizeStart={handleFilePreviewResizeStart}
        >
          <FilePreviewPanel
            key={activePreview.id}
            sessionKey={previewSessionKey}
            path={activePreview.value}
            token={token}
            loadPreview={filePreviews.load}
            initialPreview={filePreviews.peek(activePreview.value)}
            onOpenFilePreview={openFilePreview}
            onResolvePath={resolveFile}
          />
        </PreviewPane>
        </FileActionsProvider>
      ) : null}
    </section>
    </SubagentTasksProvider>
  );
}
