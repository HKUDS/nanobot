import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { FilePreviewAvailabilityProvider } from "@/components/FilePreviewAvailabilityContext";
import { FilePreviewPanel } from "@/components/FilePreviewPanel";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import { PromptNavigator } from "@/components/thread/PromptNavigator";
import { RecoveryNotice } from "@/components/thread/RecoveryNotice";
import { SessionInfoPopover } from "@/components/thread/SessionInfoPopover";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import type {
  ComposerContextUsage,
  ComposerRoundUsage,
} from "@/components/thread/ComposerUsagePopover";
import type { ModelPresetOption } from "@/components/thread/ModelPresetBadge";
import { ThreadHeader } from "@/components/thread/ThreadHeader";
import { StreamErrorNotice } from "@/components/thread/StreamErrorNotice";
import { ThreadViewport, type ThreadViewportHandle } from "@/components/thread/ThreadViewport";
import { useNanobotStream, type SendAttachment, type SendOptions } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import {
  ApiError,
  fetchFilePreviewAvailability,
  fetchInstalledCliApps,
  fetchMcpPresets,
  fetchSettings,
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
import type { CanonicalRunSnapshot, StreamError } from "@/lib/nanobot-client";
import { inferProviderFromModelName, providerDisplayLabel } from "@/lib/provider-brand";
import type {
  ChatSummary,
  RoundUsage,
  SettingsPayload,
  SlashCommand,
  SkillSummary,
  UIMessage,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { projectWebuiThreadMessages } from "@/lib/thread-display-compat";
import { useClient } from "@/providers/ClientProvider";

type MessageShape = Pick<UIMessage, "role" | "kind" | "content" | "isStreaming" | "turnId">;

interface PendingCanonicalHydrate {
  historyLineage: number;
  historyVersion: number;
  runGeneration: number;
  uiBaseline: MessageShape[];
  uiLineage: number | null;
  uiRevision: number;
}

interface PendingHistoryLineageCommit {
  lineage: number;
  messages: UIMessage[];
}

interface PendingCanonicalCommit {
  canonicalSnapshot: CanonicalRunSnapshot;
  completedTurnIds: string[];
  expectedUiRevision: number;
  historyLineage: number;
  historyVersion: number;
  hydrate: PendingCanonicalHydrate;
  messages: UIMessage[];
  previousMessages: UIMessage[];
}

function sameMessageShape(a: MessageShape, b: MessageShape): boolean {
  return (
    a.role === b.role
    && (a.kind ?? "") === (b.kind ?? "")
    && a.content === b.content
    && (!a.turnId || !b.turnId || a.turnId === b.turnId)
  );
}

function latestComposerContextUsage(messages: UIMessage[]): ComposerContextUsage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
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

function snapshotPreservesMessage(
  current: MessageShape,
  candidate: MessageShape,
  allowCompletedTurnReplacement: boolean,
): boolean {
  if (sameMessageShape(current, candidate)) return true;
  if (
    allowCompletedTurnReplacement
    && current.role === "assistant"
    && candidate.role === current.role
    && (candidate.kind ?? "") === (current.kind ?? "")
    && !!current.turnId
    && candidate.turnId === current.turnId
  ) {
    return true;
  }
  return (
    current.role === "assistant"
    && current.isStreaming === true
    && candidate.role === current.role
    && (candidate.kind ?? "") === (current.kind ?? "")
    && (!current.turnId || !candidate.turnId || candidate.turnId === current.turnId)
    && candidate.content.startsWith(current.content)
  );
}

function durableMessageShape(message: UIMessage): MessageShape | null {
  if (message.kind === "trace") return null;
  if (message.role !== "user" && message.role !== "assistant") return null;
  if (message.role === "assistant" && !message.content.trim() && !message.media?.length) {
    return null;
  }
  return {
    role: message.role,
    kind: message.kind,
    content: message.content,
    isStreaming: message.isStreaming,
    turnId: message.turnId,
  };
}

function durableMessageShapes(messages: UIMessage[]): MessageShape[] {
  return messages
    .map(durableMessageShape)
    .filter((message): message is MessageShape => message !== null);
}

function preservesMessageShapes(
  expected: MessageShape[],
  candidates: MessageShape[],
  allowCompletedTurnReplacement: boolean,
): boolean {
  let cursor = 0;
  let previousCandidate: MessageShape | null = null;
  for (const message of expected) {
    if (
      allowCompletedTurnReplacement
      && previousCandidate?.role === "assistant"
      && message.role === "assistant"
      && !!message.turnId
      && message.turnId === previousCandidate.turnId
    ) {
      // A delayed websocket delta can briefly create a second bubble after an
      // HTTP completion snapshot. The completed replay is authoritative for
      // that turn, so both local fragments may map to its single assistant row.
      continue;
    }
    let found = false;
    while (cursor < candidates.length) {
      const candidate = candidates[cursor];
      cursor += 1;
      if (snapshotPreservesMessage(message, candidate, allowCompletedTurnReplacement)) {
        found = true;
        previousCandidate = candidate;
        break;
      }
    }
    if (!found) return false;
  }
  return true;
}

function preservesDurableMessages(
  current: UIMessage[],
  snapshot: UIMessage[],
  allowCompletedTurnReplacement = false,
): boolean {
  // Canonical history refreshes can race with live websocket messages after fork/send.
  // Never accept a refreshed snapshot that drops a user/assistant message already shown.
  const expected = durableMessageShapes(current);
  if (expected.length === 0) return true;
  return preservesMessageShapes(
    expected,
    durableMessageShapes(snapshot),
    allowCompletedTurnReplacement,
  );
}

function resetDropsPostRequestDurableTail(
  baseline: MessageShape[],
  current: UIMessage[],
  snapshot: UIMessage[],
): boolean {
  const currentDurable = durableMessageShapes(current);
  let stablePrefixLength = 0;
  while (
    stablePrefixLength < baseline.length
    && stablePrefixLength < currentDurable.length
    && sameMessageShape(baseline[stablePrefixLength], currentDurable[stablePrefixLength])
  ) {
    stablePrefixLength += 1;
  }
  const postRequestTail = currentDurable.slice(stablePrefixLength);
  if (postRequestTail.length === 0) return false;
  return !preservesMessageShapes(
    postRequestTail,
    durableMessageShapes(snapshot),
    true,
  );
}

function isStaleThreadSnapshot(
  current: UIMessage[],
  snapshot: UIMessage[],
  allowCompletedTurnReplacement = false,
): boolean {
  if (current.length === 0) return false;
  if (snapshot.length === 0) return true;
  if (!preservesDurableMessages(current, snapshot, allowCompletedTurnReplacement)) return true;
  if (snapshot.length >= current.length) return false;
  if (allowCompletedTurnReplacement) return false;
  return snapshot.every((message, index) => sameMessageShape(current[index], message));
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

function completedAssistantTurnIds(messages: UIMessage[]): string[] {
  return Array.from(new Set(
    messages
      .filter((message) => message.role === "assistant" && !!message.turnId)
      .map((message) => message.turnId as string),
  ));
}

function canonicalRunSnapshot(
  messages: UIMessage[],
  hasPendingToolCalls: boolean,
  activeTurnId: string | null,
): CanonicalRunSnapshot {
  return {
    observedTurnIds: Array.from(new Set(
      messages
        .filter((message) => message.role === "user" && !!message.turnId)
        .map((message) => message.turnId as string),
    )),
    hasPendingToolCalls,
    activeTurnId,
  };
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
  return Math.max(
    FILE_PREVIEW_MIN_WIDTH,
    Math.min(FILE_PREVIEW_MAX_WIDTH, containerWidth - FILE_PREVIEW_MIN_MAIN_WIDTH),
  );
}

interface ThreadShellProps {
  session: ChatSummary | null;
  sessions?: ChatSummary[];
  title: string;
  temporary?: boolean;
  temporaryChatIds?: readonly string[];
  temporaryChatEnabled?: boolean;
  onTemporaryChatEnabledChange?: (enabled: boolean) => void;
  onToggleSidebar: () => void;
  onGoHome?: () => void;
  onNewChat?: () => void;
  onCreateChat?: (
    workspaceScope?: WorkspaceScopePayload | null,
    initialMessage?: string,
    modelPreset?: string | null,
  ) => Promise<string | null>;
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
  onOpenModelSettings?: () => void;
  skills?: SkillSummary[];
}

function toModelBadgeLabel(modelName: string | null): string | null {
  if (!modelName) return null;
  const trimmed = modelName.trim();
  if (!trimmed) return null;
  const leaf = trimmed.split("/").pop() ?? trimmed;
  return leaf || trimmed;
}

interface ModelBadgeInfo {
  label: string | null;
  model: string | null;
  provider: string | null;
  providerLabel: string | null;
  needsSetup: boolean;
}

function modelPresetForBadge(
  settings: SettingsPayload | null,
  scopedPreset: string | null,
): SettingsPayload["model_presets"][number] | null {
  if (!settings) return null;
  if (scopedPreset) {
    return settings.model_presets.find((preset) => preset.name === scopedPreset) ?? null;
  }
  const configured = settings.agent.model_preset || "default";
  return (
    settings.model_presets.find((preset) => preset.name === configured)
    ?? settings.model_presets.find((preset) => preset.active)
    ?? null
  );
}

function toModelBadgeInfo(
  modelName: string | null,
  settings: SettingsPayload | null,
  modelPreset: string | null = null,
): ModelBadgeInfo {
  const scopedPreset = modelPreset?.trim() || null;
  const preset = modelPresetForBadge(settings, scopedPreset);
  const model = scopedPreset
    ? preset?.model || null
    : settings?.agent.model || modelName || null;
  const label = preset
    ? preset.is_default
      ? preset.label?.trim() || "Default"
      : preset.name.trim()
    : scopedPreset || toModelBadgeLabel(model);
  const rawProvider = preset?.provider
    || (!scopedPreset ? settings?.agent.provider : null)
    || null;
  const provider = rawProvider === "auto"
    ? preset?.resolved_provider
      || (!scopedPreset ? settings?.agent.resolved_provider : null)
      || null
    : rawProvider || inferProviderFromModelName(model);
  const providerRow = provider
    ? settings?.providers.find((item) => item.name === provider)
    : null;
  const needsSetup = Boolean(
    settings && (!model || !provider || !providerRow || !providerRow.configured),
  );
  return {
    label,
    model: toModelBadgeLabel(model),
    provider,
    providerLabel: provider ? providerDisplayLabel(settings?.providers ?? [], provider) : null,
    needsSetup,
  };
}

function modelPresetOptionsFromSettings(
  settings: SettingsPayload | null,
): ModelPresetOption[] {
  if (!settings) return [];
  const order = new Map(
    (settings.model_call_order ?? []).map((name, index) => [name.trim(), index]),
  );
  return settings.model_presets
    .filter((preset) => !preset.is_default && preset.name.trim())
    .sort((a, b) => (
      (order.get(a.name.trim()) ?? Number.POSITIVE_INFINITY)
      - (order.get(b.name.trim()) ?? Number.POSITIVE_INFINITY)
    ))
    .map((preset) => {
      const name = preset.name.trim();
      return {
        name,
        model: preset.model,
        provider: preset.resolved_provider || preset.provider,
      };
    });
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
  content: string;
  images?: SendAttachment[];
  options?: SendOptions;
}

interface InstalledSettingItemsOptions<Payload, Item> {
  getToken: () => string;
  eventName: string;
  fetchPayload: (token: string) => Promise<Payload>;
  isPayload: (value: unknown) => value is Payload;
  selectItems: (payload: Payload) => Item[];
}

function useInstalledSettingItems<Payload, Item>({
  getToken,
  eventName,
  fetchPayload,
  isPayload,
  selectItems,
}: InstalledSettingItemsOptions<Payload, Item>): Item[] {
  const [items, setItems] = useState<Item[]>([]);

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
      try {
        const payload = await fetchPayload(getToken());
        if (!cancelled && version === payloadVersion) {
          setItems(selectItems(payload));
        }
      } catch {
        // Keep the last successful catalog during transient refresh failures.
      } finally {
        refreshing = false;
        if (refreshAfterFlight && !cancelled) {
          refreshAfterFlight = false;
          void refresh();
        }
      }
    };
    const queueRefresh = () => {
      if (document.visibilityState === "hidden" || refreshQueued) return;
      refreshQueued = true;
      queueMicrotask(() => {
        refreshQueued = false;
        if (!cancelled) void refresh();
      });
    };
    void refresh();

    const refreshOnChanged = (event: Event) => {
      const payload = (event as CustomEvent<unknown>).detail;
      if (isPayload(payload)) {
        payloadVersion += 1;
        setItems(selectItems(payload));
        return;
      }
      if (refreshing) {
        refreshAfterFlight = true;
        return;
      }
      queueRefresh();
    };

    window.addEventListener("focus", queueRefresh);
    document.addEventListener("visibilitychange", queueRefresh);
    window.addEventListener(eventName, refreshOnChanged);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", queueRefresh);
      document.removeEventListener("visibilitychange", queueRefresh);
      window.removeEventListener(eventName, refreshOnChanged);
    };
  }, [eventName, fetchPayload, getToken, isPayload, selectItems]);

  return items;
}

export function ThreadShell({
  session,
  sessions = [],
  title,
  temporary = false,
  temporaryChatIds = [],
  temporaryChatEnabled = false,
  onTemporaryChatEnabledChange,
  onToggleSidebar,
  onCreateChat,
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
  onOpenModelSettings,
  skills = [],
}: ThreadShellProps) {
  const { t } = useTranslation();
  const chatId = session?.chatId ?? null;
  const historyKey = temporary ? null : session?.key ?? null;
  const mentionSessions = useMemo(
    () => sessions.filter((candidate) => candidate.key !== historyKey),
    [historyKey, sessions],
  );
  const {
    messages: historical,
    loading,
    error: historyError,
    loadingOlder,
    loadOlder,
    hasMoreBefore,
    userMessageOffset,
    hasPendingToolCalls,
    completedTurnIds,
    continuity: historyContinuity,
    lineage: historyLineage,
    activeTurnId: historyActiveTurnId,
    refresh: refreshHistory,
    version: historyVersion,
    forkBoundaryMessageCount,
  } = useSessionHistory(historyKey);
  const { client, getToken, ingressLimits, modelName, token } = useClient();
  const pickWorkspaceFolder = useCallback(async (): Promise<string | null> => {
    const response = await client.requestMutation<{ path: unknown }>(
      "workspace.pick_folder",
      {},
      300_000,
    );
    return typeof response.path === "string" ? response.path : null;
  }, [client]);
  const [fallbackModelName, setFallbackModelName] = useState<string | null>(null);
  const [booting, setBooting] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const cliApps = useInstalledSettingItems({
    getToken,
    eventName: CLI_APPS_CHANGED_EVENT,
    fetchPayload: fetchInstalledCliApps,
    isPayload: isCliAppsPayload,
    selectItems: installedCliAppsFromPayload,
  });
  const mcpPresets = useInstalledSettingItems({
    getToken,
    eventName: MCP_PRESETS_CHANGED_EVENT,
    fetchPayload: fetchMcpPresets,
    isPayload: isMcpPresetsPayload,
    selectItems: installedMcpPresetsFromPayload,
  });
  const [settings, setSettings] = useState<SettingsPayload | null>(settingsSnapshot);
  const [heroGreetingKey, setHeroGreetingKey] = useState(randomHeroGreetingKey);
  const [submittedViewportTurnId, setSubmittedViewportTurnId] = useState<string | null>(null);
  const [filePreviewPath, setFilePreviewPath] = useState<string | null>(null);
  const [filePreviewClosing, setFilePreviewClosing] = useState(false);
  const [filePreviewWidth, setFilePreviewWidth] = useState(FILE_PREVIEW_DEFAULT_WIDTH);
  const [quotedContext, setQuotedContext] = useState<string | null>(null);
  const [composerFocusSignal, setComposerFocusSignal] = useState(0);
  const shellRef = useRef<HTMLElement | null>(null);
  const composerSurfaceRef = useRef<HTMLDivElement | null>(null);
  const filePreviewWidthRef = useRef(FILE_PREVIEW_DEFAULT_WIDTH);
  const filePreviewCloseTimerRef = useRef<number | null>(null);
  const pendingFirstRef = useRef<PendingFirstMessage | null>(null);
  const [pendingFirstTargetChatId, setPendingFirstTargetChatId] = useState<string | null>(null);
  const viewportRef = useRef<ThreadViewportHandle | null>(null);
  const activeViewportTurnByChatIdRef = useRef<Map<string, string>>(new Map());
  const messageCacheRef = useRef<Map<string, UIMessage[]>>(new Map());
  const knownTemporaryChatIdsRef = useRef(new Set<string>());
  /** Last chatId we associated with the in-memory thread (for cache-on-switch). */
  const prevChatIdForCacheRef = useRef<string | null>(null);
  /** Skip one message-cache write right after chatId changes (messages may not match yet). */
  const skipLayoutCacheRef = useRef(false);
  const pendingCanonicalHydrateRef = useRef<Map<string, PendingCanonicalHydrate>>(new Map());
  const pendingCanonicalCommitRef = useRef<Map<string, PendingCanonicalCommit>>(new Map());
  const pendingHistoryLineageCommitRef = useRef<Map<string, PendingHistoryLineageCommit>>(
    new Map(),
  );
  const completedCanonicalHydrateVersionRef = useRef<Map<string, number>>(new Map());
  const committedHistoryLineageRef = useRef<Map<string, number>>(new Map());
  const sessionKeyByChatIdRef = useRef<Map<string, string>>(new Map());
  const currentUiMessagesRef = useRef<UIMessage[] | null>(null);
  const uiRevisionRef = useRef(0);
  const showTemporaryChatControl =
    !hideHeader && !session && !loading && !!onTemporaryChatEnabledChange;

  const initial = useMemo(() => {
    if (!chatId) return historical;
    return messageCacheRef.current.get(chatId) ?? historical;
  }, [chatId, historical]);
  const handleTurnEnd = useCallback(() => {
    if (chatId) activeViewportTurnByChatIdRef.current.delete(chatId);
    setSubmittedViewportTurnId(null);
    setFallbackModelName(null);
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
    reconcileTurnComplete,
    setMessages,
    streamError,
    dismissStreamError,
  } = useNanobotStream(chatId, initial, hasPendingToolCalls, handleTurnEnd);

  useLayoutEffect(() => {
    if (currentUiMessagesRef.current === messages) return;
    currentUiMessagesRef.current = messages;
    uiRevisionRef.current += 1;
    if (!chatId) return;
    const lineageCommit = pendingHistoryLineageCommitRef.current.get(chatId);
    if (!lineageCommit) return;
    pendingHistoryLineageCommitRef.current.delete(chatId);
    if (lineageCommit.messages === messages) {
      committedHistoryLineageRef.current.set(chatId, lineageCommit.lineage);
    }
  }, [chatId, messages]);

  useEffect(() => {
    if (chatId && historyKey) sessionKeyByChatIdRef.current.set(chatId, historyKey);
  }, [chatId, historyKey]);

  useEffect(() => {
    filePreviewWidthRef.current = filePreviewWidth;
  }, [filePreviewWidth]);

  useEffect(() => {
    if (filePreviewCloseTimerRef.current !== null) {
      window.clearTimeout(filePreviewCloseTimerRef.current);
      filePreviewCloseTimerRef.current = null;
    }
    setFilePreviewClosing(false);
    setFilePreviewPath(null);
    setQuotedContext(null);
    setSubmittedViewportTurnId(null);
  }, [historyKey]);

  useEffect(() => {
    const retained = new Set(temporaryChatIds);
    for (const chatId of retained) knownTemporaryChatIdsRef.current.add(chatId);
    for (const cachedChatId of knownTemporaryChatIdsRef.current) {
      if (!retained.has(cachedChatId)) {
        messageCacheRef.current.delete(cachedChatId);
        activeViewportTurnByChatIdRef.current.delete(cachedChatId);
        knownTemporaryChatIdsRef.current.delete(cachedChatId);
      }
    }
  }, [temporaryChatIds]);

  const handleQuoteSelection = useCallback((text: string) => {
    setQuotedContext(text);
    setComposerFocusSignal((value) => value + 1);
  }, []);

  useEffect(() => {
    return () => {
      if (filePreviewCloseTimerRef.current !== null) {
        window.clearTimeout(filePreviewCloseTimerRef.current);
      }
    };
  }, []);

  const displayMessages = useMemo(() => projectWebuiThreadMessages(messages), [messages]);
  const composerContextUsage = useMemo(
    () => latestComposerContextUsage(displayMessages),
    [displayMessages],
  );
  const composerRoundUsage = useMemo(
    () => recentComposerRoundUsage(displayMessages),
    [displayMessages],
  );
  const currentGoalState = messagesReady ? goalState : undefined;
  // Decision states freeze the interrupted turn and hand the next action to
  // the recovery notice. ``resuming`` remains active; ``recovered`` is only
  // historical metadata and must not suppress a later normal turn.
  const recoveryNeedsDecision = recoveryState?.status === "awaiting_user"
    || recoveryState?.status === "failed";
  const currentRunStartedAt = messagesReady && !recoveryNeedsDecision ? runStartedAt : null;
  const turnActive = messagesReady
    && !recoveryNeedsDecision
    && (isStreaming || currentRunStartedAt !== null);
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
    [historyKey],
  );
  const filePreviewAvailabilityRevision = displayMessages.length;
  const resolveFilePreviewAvailability = useCallback((path: string) => {
    if (!historyKey) return Promise.resolve(false);
    const cached = filePreviewAvailabilityCache.get(path);
    if (
      cached
      && (cached.available !== false || cached.revision === filePreviewAvailabilityRevision)
    ) {
      return cached.promise;
    }
    const pending = fetchFilePreviewAvailability(getToken(), historyKey, path).catch(
      (error: unknown) => {
        if (error instanceof ApiError) {
          if (error.status === 404 && /API route not found/i.test(error.message)) {
            return true;
          }
          if ([400, 403, 404, 415].includes(error.status)) return false;
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
    historyKey,
  ]);

  const showHeroComposer = displayMessages.length === 0 && !loading;
  const composerVariant = showHeroComposer ? emptyComposerVariant : "thread";
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
    void refreshModelSettings();
  }, [refreshModelSettings, settingsSnapshot]);

  useEffect(() => {
    return client.onRuntimeModelUpdate(() => {
      void refreshModelSettings();
    });
  }, [client, refreshModelSettings]);

  useEffect(() => {
    if (!chatId) {
      setFallbackModelName(null);
      return;
    }
    setFallbackModelName(null);
    return client.onChat(chatId, (event) => {
      if (event.event !== "turn_model_updated" || event.fallback !== true) return;
      setFallbackModelName(event.model_name);
    });
  }, [chatId, client]);

  useEffect(() => {
    if (!historyKey || !chatId || loading) return;
    const cached = messageCacheRef.current.get(chatId);
    const pendingCanonicalHydrate = pendingCanonicalHydrateRef.current.get(chatId);
    const hasNewCanonicalHistory = (
      pendingCanonicalHydrate !== undefined
      && historyVersion > pendingCanonicalHydrate.historyVersion
    );
    // When the user switches away and back, keep the local in-memory thread
    // state (including not-yet-persisted messages) instead of replacing it with
    // whatever the history endpoint currently knows about. Once a fresh
    // canonical replay arrives (e.g. after ``session_updated`` refresh), prefer it
    // so rendering converges to the same shape as a manual refresh.
    const normalizedHistory = projectWebuiThreadMessages(historical);
    const keepLiveMessages = (current: UIMessage[]) => projectWebuiThreadMessages(current);
    if (hasNewCanonicalHistory && pendingCanonicalHydrate) {
      // Transcript replay strips streaming metadata and uses persisted ids.
      // Never adopt it while the turn is active: even if no assistant delta
      // arrived locally yet, the next resumed delta must create/continue the
      // live cursor rather than append to an immutable replay row.
      if (hasPendingToolCalls) {
        setMessages((current) => keepLiveMessages(current));
        return;
      }
      const authoritativeReset = (
        pendingCanonicalHydrate.uiLineage !== null
        && historyLineage !== pendingCanonicalHydrate.uiLineage
        && (
          historyContinuity === "reset"
          || (
            historyContinuity === "overlap"
            && historyLineage === pendingCanonicalHydrate.historyLineage
          )
        )
      );
      const responseUiRevision = uiRevisionRef.current;
      const resetDropsRenderedTail = (
        authoritativeReset
        && responseUiRevision !== pendingCanonicalHydrate.uiRevision
        && resetDropsPostRequestDurableTail(
          pendingCanonicalHydrate.uiBaseline,
          messages,
          normalizedHistory,
        )
      );
      if (
        authoritativeReset
          ? resetDropsRenderedTail
          : isStaleThreadSnapshot(messages, normalizedHistory, true)
      ) {
        setMessages((current) => keepLiveMessages(current));
        return;
      }
      const canonicalCompletedTurnIds = Array.from(new Set([
        ...completedTurnIds,
        ...completedAssistantTurnIds(normalizedHistory),
      ]));
      const canonicalSnapshot = canonicalRunSnapshot(
        normalizedHistory,
        hasPendingToolCalls,
        historyActiveTurnId,
      );
      if (!client.canReconcileCanonicalCompletion(
        chatId,
        pendingCanonicalHydrate.runGeneration,
        canonicalCompletedTurnIds,
        canonicalSnapshot,
      )) {
        setMessages((current) => keepLiveMessages(current));
        return;
      }
      pendingCanonicalCommitRef.current.set(chatId, {
        canonicalSnapshot,
        completedTurnIds: canonicalCompletedTurnIds,
        expectedUiRevision: responseUiRevision + 1,
        historyLineage,
        historyVersion,
        hydrate: pendingCanonicalHydrate,
        messages: normalizedHistory,
        previousMessages: messages,
      });
      setMessages((current) => {
        if (current !== messages) return current;
        if (
          authoritativeReset
            ? resetDropsRenderedTail
            : isStaleThreadSnapshot(current, normalizedHistory, true)
        ) {
          return keepLiveMessages(current);
        }
        return normalizedHistory;
      });
      return;
    }
    const adoptsNormalizedHistory = cached && cached.length > 0
      ? (
          normalizedHistory.length > cached.length
          && !isStaleThreadSnapshot(messages, normalizedHistory)
        )
      : !isStaleThreadSnapshot(messages, normalizedHistory);
    if (adoptsNormalizedHistory) {
      pendingHistoryLineageCommitRef.current.set(chatId, {
        lineage: historyLineage,
        messages: normalizedHistory,
      });
    }
    setMessages((current) => {
      if (cached && cached.length > 0) {
        if (
          normalizedHistory.length > cached.length
          && !isStaleThreadSnapshot(current, normalizedHistory)
        ) {
          return normalizedHistory;
        }
        return isStaleThreadSnapshot(current, cached) ? keepLiveMessages(current) : cached;
      }
      return isStaleThreadSnapshot(current, normalizedHistory)
        ? keepLiveMessages(current)
        : normalizedHistory;
    });
  }, [
    loading,
    chatId,
    client,
    completedTurnIds,
    historical,
    historyVersion,
    historyContinuity,
    historyLineage,
    historyActiveTurnId,
    hasPendingToolCalls,
    historyKey,
  ]);

  useLayoutEffect(() => {
    if (!historyKey || !chatId) return;
    const commit = pendingCanonicalCommitRef.current.get(chatId);
    if (!commit) return;
    if (
      commit.historyVersion !== historyVersion
      || commit.historyLineage !== historyLineage
      || commit.messages !== messages
    ) {
      pendingCanonicalCommitRef.current.delete(chatId);
      return;
    }
    if (pendingCanonicalHydrateRef.current.get(chatId) !== commit.hydrate) {
      pendingCanonicalCommitRef.current.delete(chatId);
      return;
    }
    if (uiRevisionRef.current !== commit.expectedUiRevision) {
      pendingCanonicalCommitRef.current.delete(chatId);
      const fallback = messageCacheRef.current.get(chatId) ?? commit.previousMessages;
      messageCacheRef.current.set(chatId, fallback);
      setMessages((current) => current === commit.messages ? fallback : current);
      return;
    }
    if (!client.reconcileCanonicalCompletion(
      chatId,
      commit.hydrate.runGeneration,
      commit.completedTurnIds,
      commit.canonicalSnapshot,
    )) {
      pendingCanonicalCommitRef.current.delete(chatId);
      const fallback = messageCacheRef.current.get(chatId) ?? commit.previousMessages;
      messageCacheRef.current.set(chatId, fallback);
      setMessages((current) => current === commit.messages ? fallback : current);
      return;
    }
    pendingCanonicalHydrateRef.current.delete(chatId);
    pendingCanonicalCommitRef.current.delete(chatId);
    committedHistoryLineageRef.current.set(chatId, historyLineage);
    completedCanonicalHydrateVersionRef.current.set(chatId, historyVersion);
  }, [chatId, client, historyKey, historyLineage, historyVersion, messages, setMessages]);

  useEffect(() => {
    if (!historyKey || !chatId || hasPendingToolCalls) return;
    if (completedCanonicalHydrateVersionRef.current.get(chatId) !== historyVersion) return;
    completedCanonicalHydrateVersionRef.current.delete(chatId);
    reconcileTurnComplete();
  }, [chatId, hasPendingToolCalls, historyKey, historyVersion, messages, reconcileTurnComplete]);

  const refreshCanonicalHistory = useCallback(() => {
    if (!historyKey || !chatId) return;
    pendingCanonicalHydrateRef.current.set(chatId, {
      historyLineage,
      historyVersion,
      runGeneration: client.getRunGeneration(chatId),
      uiBaseline: durableMessageShapes(currentUiMessagesRef.current ?? []),
      uiLineage: committedHistoryLineageRef.current.get(chatId) ?? null,
      uiRevision: uiRevisionRef.current,
    });
    refreshHistory();
  }, [chatId, client, historyKey, historyLineage, historyVersion, refreshHistory]);

  useEffect(() => {
    if (!historyKey || !chatId) return;
    return client.onSessionUpdate((updatedChatId, scope) => {
      if (updatedChatId !== chatId) return;
      if (scope === "metadata") return;
      // A turn-end thread refresh can arrive while the viewport is easing the
      // final layout change. User-driven scrolling already disables following,
      // so keep an active programmatic follow alive across canonical hydration.
      refreshCanonicalHistory();
    });
  }, [chatId, client, historyKey, refreshCanonicalHistory]);

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
      refreshCanonicalHistory();
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
    refreshCanonicalHistory,
    turnActive,
  ]);

  useEffect(() => {
    let refreshOnNextOpen = client.status !== "open";
    return client.onStatus((status) => {
      if (status !== "open") {
        refreshOnNextOpen = true;
        return;
      }
      if (refreshOnNextOpen) refreshCanonicalHistory();
      refreshOnNextOpen = false;
    });
  }, [client, refreshCanonicalHistory]);

  useEffect(() => {
    if (chatId) return;
    setMessages(projectWebuiThreadMessages(historical));
  }, [chatId, historical, setMessages]);

  useLayoutEffect(() => {
    if (chatId) {
      const prev = prevChatIdForCacheRef.current;
      if (prev && prev !== chatId) {
        messageCacheRef.current.set(prev, displayMessages);
        skipLayoutCacheRef.current = true;
      }
      prevChatIdForCacheRef.current = chatId;
    } else {
      if (prevChatIdForCacheRef.current) {
        messageCacheRef.current.set(
          prevChatIdForCacheRef.current,
          displayMessages,
        );
        skipLayoutCacheRef.current = true;
      }
      prevChatIdForCacheRef.current = null;
    }
  }, [chatId, displayMessages]);

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
    messageCacheRef.current.set(chatId, displayMessages);
  }, [chatId, displayMessages, loading]);

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
    setBooting(false);
  }, [chatId, pendingFirstTargetChatId, send]);

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
      pendingFirstRef.current = { content, images, options: withWorkspaceScope(options) };
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
      return true;
    },
    [booting, client, localModelPreset, onCreateChat, withWorkspaceScope, workspaceScope],
  );

  const handleThreadSend = useCallback(
    (content: string, images?: SendAttachment[], options?: SendOptions) => {
      setFallbackModelName(null);
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
    },
    [chatId, send, withWorkspaceScope],
  );

  const handleOpenFilePreview = useCallback((path: string) => {
    if (filePreviewCloseTimerRef.current !== null) {
      window.clearTimeout(filePreviewCloseTimerRef.current);
      filePreviewCloseTimerRef.current = null;
    }
    setFilePreviewClosing(false);
    setFilePreviewPath(path);
  }, []);

  const handleCloseFilePreview = useCallback(() => {
    if (!filePreviewPath || filePreviewClosing) return;
    setFilePreviewClosing(true);
    filePreviewCloseTimerRef.current = window.setTimeout(() => {
      filePreviewCloseTimerRef.current = null;
      setFilePreviewPath(null);
      setFilePreviewClosing(false);
    }, FILE_PREVIEW_CLOSE_ANIMATION_MS);
  }, [filePreviewClosing, filePreviewPath]);

  const handleFilePreviewResizeStart = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const panel = event.currentTarget.closest<HTMLElement>("[data-file-preview-panel]");
    const shellRect = shellRef.current?.getBoundingClientRect();
    const rightEdge = shellRect?.right ?? window.innerWidth;
    const maxWidth = maxFilePreviewWidth(shellRect?.width ?? window.innerWidth);
    const originalBodyCursor = document.body.style.cursor;
    const originalBodyUserSelect = document.body.style.userSelect;
    const originalPanelTransition = panel?.style.transition ?? "";
    let nextWidth = filePreviewWidthRef.current;
    let frame: number | null = null;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    if (panel) panel.style.transition = "none";

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
    const handlePointerUp = () => {
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
        frame = null;
      }
      panel?.style.setProperty("--file-preview-width", `${nextWidth}px`);
      panel?.style.setProperty("--file-preview-slot-width", `${nextWidth}px`);
      if (panel) panel.style.transition = originalPanelTransition;
      setFilePreviewWidth(nextWidth);
      document.body.style.cursor = originalBodyCursor;
      document.body.style.userSelect = originalBodyUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };

    applyWidth(event.clientX);
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  }, []);

  useEffect(() => {
    if (!filePreviewPath) return;
    const clampToShell = () => {
      const shellWidth = shellRef.current?.getBoundingClientRect().width ?? window.innerWidth;
      const maxWidth = maxFilePreviewWidth(shellWidth);
      const nextWidth = clampFilePreviewWidth(filePreviewWidthRef.current, maxWidth);
      filePreviewWidthRef.current = nextWidth;
      setFilePreviewWidth(nextWidth);
    };
    clampToShell();
    window.addEventListener("resize", clampToShell);
    return () => {
      window.removeEventListener("resize", clampToShell);
    };
  }, [filePreviewPath]);

  const handleForkFromMessage = useCallback(
    async (beforeUserIndex: number) => {
      if (!chatId || !onForkChat) return;
      const forkedChatId = await onForkChat(chatId, beforeUserIndex);
      if (!forkedChatId) return;
      messageCacheRef.current.delete(forkedChatId);
      pendingCanonicalHydrateRef.current.delete(forkedChatId);
      completedCanonicalHydrateVersionRef.current.delete(forkedChatId);
    },
    [chatId, onForkChat],
  );

  const composer = (
    <>
      {recoveryState ? (
        <RecoveryNotice
          state={recoveryState}
          onContinue={continueRecovery}
          onDismiss={dismissRecovery}
        />
      ) : null}
      {streamError && !hasInlineDeliveryError(messages, streamError) ? (
        <StreamErrorNotice
          error={streamError}
          onDismiss={dismissStreamError}
        />
      ) : null}
      {session ? (
        <ThreadComposer
          onSend={handleThreadSend}
          disabled={!chatId}
          inputAriaLabel={composerInputAriaLabel}
          isStreaming={turnActive}
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
          fallbackModelName={fallbackModelName}
          onModelBadgeClick={modelBadge.needsSetup ? onOpenModelSettings : undefined}
          onManageModels={onOpenModelSettings}
          contextUsage={composerContextUsage}
          recentRoundUsage={composerRoundUsage}
          variant={composerVariant}
          slashCommands={availableSlashCommands}
          cliApps={cliApps}
          mcpPresets={mcpPresets}
          sessions={mentionSessions}
          skills={skills}
          onStop={stop}
          onTranscribeAudio={transcribeAudio}
          goalState={currentGoalState}
          workspaceScope={workspaceScope}
          workspaceControlsHidden={temporary}
          workspaceDefaultScope={workspaceDefaultScope}
          workspaceControls={workspaceControls}
          workspaceScopeDisabled={workspaceScopeDisabled}
          workspaceError={workspaceError}
          onPickWorkspaceFolder={
            workspaceControls?.can_pick_folder ? pickWorkspaceFolder : undefined
          }
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
          fallbackModelName={fallbackModelName}
          onModelBadgeClick={modelBadge.needsSetup ? onOpenModelSettings : undefined}
          onManageModels={onOpenModelSettings}
          contextUsage={composerContextUsage}
          recentRoundUsage={composerRoundUsage}
          variant="hero"
          slashCommands={availableSlashCommands}
          cliApps={cliApps}
          mcpPresets={mcpPresets}
          sessions={mentionSessions}
          skills={skills}
          surfaceRef={composerSurfaceRef}
          onTranscribeAudio={transcribeAudio}
          goalState={currentGoalState}
          workspaceScope={workspaceScope}
          workspaceControlsHidden={temporary}
          workspaceDefaultScope={workspaceDefaultScope}
          workspaceControls={workspaceControls}
          workspaceScopeDisabled={workspaceScopeDisabled}
          workspaceError={workspaceError}
          onPickWorkspaceFolder={
            workspaceControls?.can_pick_folder ? pickWorkspaceFolder : undefined
          }
          onWorkspaceScopeChange={onWorkspaceScopeChange}
          transcriptionProvider={settingsSnapshot?.transcription?.provider}
          ingressLimits={ingressLimits}
        />
      )}
    </>
  );

  const emptyState = loading ? (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      {t("thread.loadingConversation")}
    </div>
  ) : (
    <div className="flex w-full flex-col items-center text-center animate-in fade-in-0 slide-in-from-bottom-2 [animation-duration:220ms] motion-reduce:animate-none">
      <HeroGreeting text={t(heroGreetingKey)} />
    </div>
  );
  const sessionInfoAction = historyKey ? (
    <SessionInfoPopover sessionKey={historyKey} token={token} title={title} />
  ) : undefined;
  const promptNavigatorAction = historyKey ? (
    <PromptNavigator
      messages={displayMessages}
      onJumpToPrompt={(promptId) => viewportRef.current?.jumpToUserPrompt(promptId)}
    />
  ) : undefined;

  const threadHeader = !hideHeader ? (
    <ThreadHeader
      title={title}
      handle={temporary || (hideHeaderTitle && inlineHandle) ? null : session?.handle}
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
    <section ref={shellRef} className="relative flex min-h-0 flex-1 overflow-hidden">
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
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
          resolve={historyKey ? resolveFilePreviewAvailability : undefined}
        >
          <ThreadViewport
            ref={viewportRef}
            messages={displayMessages}
            temporary={temporary}
            isStreaming={turnActive}
            runStartedAt={currentRunStartedAt}
            retryStatus={retryStatus}
            emptyState={emptyState}
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
            userMessageOffset={userMessageOffset}
            onLoadOlder={loadOlder}
            onOpenFilePreview={historyKey ? handleOpenFilePreview : undefined}
            onForkFromMessage={onForkChat ? handleForkFromMessage : undefined}
            onQuoteSelection={session ? handleQuoteSelection : undefined}
          />
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
      {filePreviewPath && historyKey ? (
        <FilePreviewPanel
          sessionKey={historyKey}
          path={filePreviewPath}
          token={token}
          desktopWidth={filePreviewWidth}
          isClosing={filePreviewClosing}
          onResizeStart={handleFilePreviewResizeStart}
          onClose={handleCloseFilePreview}
        />
      ) : null}
    </section>
  );
}
