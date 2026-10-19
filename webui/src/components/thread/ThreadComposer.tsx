import {
  NewChatIcon,
  CompactIcon,
  StatusIcon,
  ModelsIcon,
  TriggerIcon,
  DreamLogIcon,
  PromptTemplateIcon,
  PairingIcon,
  ToolRunIcon,
  ActivityIcon,
  ArchiveIcon,
  SkillsIcon,
  MemoryIcon,
  HelpIcon,
  HistoryIcon,
  ConversationIcon,
  VoiceIcon,
  AttachIcon,
  RestartIcon,
  RestrictedAccessIcon,
  DreamIcon,
  StopIcon,
  EditIcon,
  GoalIcon,
  RestoreMemoryIcon,
} from "@/components/icons/product-icons";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type Ref,
} from "react";

import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import {
  CapabilityMentionToken,
  cliAppInitials,
  mcpPresetInitials,
  splitCapabilityMentionSegments,
} from "@/components/CliAppMentionText";
import type { CapabilityMentionSegment } from "@/lib/composer-mention-text";
import { INLINE_TOKEN_HIGHLIGHT_COLOR } from "@/components/InlineTokenHighlight";
import {
  ArrowUp,
  ChevronDown,
  ChevronUp,
  CornerDownRight,
  FileText,
  ImageIcon,
  Loader2,
  Quote,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  floatingItemClassName,
  floatingItemFocusClassName,
  floatingSurfaceElevationClassName,
  floatingSurfaceVisualClassName,
} from "@/components/ui/floating-surface";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  WorkspaceAccessToggle,
  WorkspaceProjectPicker,
} from "@/components/thread/WorkspaceControls";
import {
  ModelPresetBadge,
  type ModelPresetOption,
} from "@/components/thread/ModelPresetBadge";
import {
  ComposerUsagePopover,
  type ComposerContextUsage,
  type ComposerRoundUsage,
} from "@/components/thread/ComposerUsagePopover";
import {
  ACCEPT_ATTR,
  MAX_ATTACHMENTS_PER_MESSAGE,
  MAX_ATTACHMENT_BYTES,
  MAX_TOTAL_ATTACHMENT_BYTES,
  useAttachedImages,
  type AttachedImage,
  type AttachmentError,
  type AttachmentKind,
  type RestoredReadyImage,
} from "@/hooks/useAttachedImages";
import { useClipboardAndDrop } from "@/hooks/useClipboardAndDrop";
import { useComposerMentionInput } from "@/hooks/useComposerMentionInput";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import { useVoiceRecorder, type VoiceRecorderErrorKey } from "@/hooks/useVoiceRecorder";
import type {
  CliAppInfo,
  ChatSummary,
  GoalStateWsPayload,
  McpPresetInfo,
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  SessionMention,
  SlashCommand,
  SkillSummary,
  WebUIIngressLimits,
  WorkspaceScopePayload,
  WorkspacesPayload,
  ProjectDirectory,
  WorkspaceDirectoriesPayload,
} from "@/lib/types";
import {
  logoFallbackUrls,
} from "@/lib/provider-brand";
import { sessionHandleColor } from "@/lib/session-handle";
import { requestSkillsRefresh } from "@/lib/skill-events";
import {
  isRegisteredSlashCommand,
  isSideChannelLifecycle,
  slashCommandLifecycle,
} from "@/lib/slash-command";
import {
  clearDraggedSession,
  hasDraggedSession,
  readDraggedSession,
} from "@/lib/session-drag";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";
import { cn } from "@/lib/utils";
import { composerMentionText } from "@/lib/composer-mention-text";
import type { ComposerDraftStore } from "@/lib/composer-draft";

const VOICE_SHORTCUT_CODE = "KeyD";
const VOICE_SHORTCUT_ARIA = "Control+Shift+D";
const VOICE_ERROR_VISIBLE_MS = 3_500;
const VOICE_ERROR_FADE_MS = 500;
type VoiceShortcutPlatform = "apple" | "chromeos" | "linux" | "other" | "windows";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isVoiceShortcutDown(event: KeyboardEvent): boolean {
  return (
    event.code === VOICE_SHORTCUT_CODE
    && event.ctrlKey
    && event.shiftKey
    && !event.altKey
    && !event.metaKey
  );
}

function isVoiceShortcutRelease(event: KeyboardEvent): boolean {
  return (
    event.code === VOICE_SHORTCUT_CODE
    || event.key === "Control"
    || event.key === "Shift"
  );
}

function getVoiceShortcutPlatform(): VoiceShortcutPlatform {
  if (typeof navigator === "undefined") return "other";
  const userAgentData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;
  const platform = [
    userAgentData?.platform,
    navigator.platform,
    navigator.userAgent,
  ].filter(Boolean).join(" ").toLowerCase();
  const isIpadPretendingToBeMac =
    navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  if (isIpadPretendingToBeMac || /mac|iphone|ipad|ipod/.test(platform)) return "apple";
  if (/win/.test(platform)) return "windows";
  if (/cros/.test(platform)) return "chromeos";
  if (/linux|x11|android/.test(platform)) return "linux";
  return "other";
}

function getVoiceShortcutLabel(): string {
  switch (getVoiceShortcutPlatform()) {
    case "apple":
      return "⌃⇧D";
    case "chromeos":
    case "linux":
    case "windows":
    case "other":
      return "Ctrl ⇧ D";
  }
}

interface ThreadComposerProps {
  onSend: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
  ) => boolean | void | Promise<boolean | void>;
  disabled?: boolean;
  placeholder?: string;
  inputAriaLabel?: string;
  compactWhenIdle?: boolean;
  isStreaming?: boolean;
  activeTurnId?: string | null;
  completedTurnIds?: readonly string[];
  modelLabel?: string | null;
  modelDetail?: string | null;
  modelPreset?: string | null;
  modelPresets?: ModelPresetOption[];
  onModelPresetChange?: (name: string) => void;
  modelProvider?: string | null;
  modelProviderLabel?: string | null;
  modelNeedsSetup?: boolean;
  onModelBadgeClick?: () => void;
  onManageModels?: () => void;
  contextUsage?: ComposerContextUsage | null;
  recentRoundUsage?: readonly ComposerRoundUsage[];
  variant?: "thread" | "hero";
  slashCommands?: SlashCommand[];
  onMentionSearch?: () => void;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  sessions?: ChatSummary[];
  skills?: SkillSummary[];
  onStop?: () => void;
  surfaceRef?: Ref<HTMLDivElement>;
  onTranscribeAudio?: (dataUrl: string, options?: { durationMs?: number }) => Promise<string>;
  /** Sustained objective for this chat (WebSocket ``goal_state``). */
  goalState?: GoalStateWsPayload;
  workspaceScope?: WorkspaceScopePayload | null;
  workspaceControlsHidden?: boolean;
  workspacePickerLayoutAnchor?: HTMLElement | null;
  workspaceDefaultScope?: WorkspaceScopePayload | null;
  workspaceControls?: WorkspacesPayload["controls"] | null;
  workspaceScopeDisabled?: boolean;
  workspaceError?: string | null;
  onFavoriteWorkspaceProject?: (path: string, pinned: boolean) => Promise<ProjectDirectory[]>;
  onResolveWorkspaceProject?: (path: string) => Promise<ProjectDirectory>;
  onLoadWorkspaceProjects?: () => Promise<WorkspacesPayload>;
  onBrowseWorkspaceDirectories?: (path: string, query: string, showHidden: boolean) => Promise<WorkspaceDirectoriesPayload>;
  onWorkspaceScopeChange?: (scope: WorkspaceScopePayload) => void;
  pendingQueueKey?: string | null;
  draftKey?: string;
  draftStore?: ComposerDraftStore;
  persistDraft?: boolean;
  transcriptionProvider?: string | null;
  ingressLimits?: WebUIIngressLimits | null;
  quotedContext?: string | null;
  focusRequest?: number;
  onQuotedContextChange?: (text: string | null) => void;
}

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: ActivityIcon,
  archive: ArchiveIcon,
  "book-open": SkillsIcon,
  brain: MemoryIcon,
  "circle-help": HelpIcon,
  history: HistoryIcon,
  "rotate-cw": RestartIcon,
  shield: RestrictedAccessIcon,
  sparkles: DreamIcon,
  square: StopIcon,
  "square-pen": EditIcon,
  "undo-2": RestoreMemoryIcon,
  zap: TriggerIcon,
  "file-text": PromptTemplateIcon,
  wrench: ToolRunIcon,
};

const BUILTIN_COMMAND_ICONS: Record<string, LucideIcon> = {
  "/new": NewChatIcon, "/compact": CompactIcon, "/stop": StopIcon,
  "/restart": RestartIcon, "/status": StatusIcon, "/model": ModelsIcon,
  "/history": HistoryIcon, "/goal": GoalIcon, "/trigger": TriggerIcon,
  "/dream": DreamIcon, "/dream-log": DreamLogIcon, "/dream-restore": RestoreMemoryIcon,
  "/dream-prompt": PromptTemplateIcon, "/evaluator-prompt": PromptTemplateIcon,
  "/skill": SkillsIcon, "/help": HelpIcon, "/pairing": PairingIcon,
};

const SLASH_PALETTE_GAP_PX = 8;
const SLASH_PALETTE_MAX_HEIGHT_PX = 288;
const SLASH_PALETTE_MIN_HEIGHT_PX = 144;
const SLASH_PALETTE_CHROME_PX = 12;
const SLASH_RECENTS_STORAGE_KEY = "nanobot.webui.slashCommandRecents";
const SLASH_RECENTS_LIMIT = 5;
const QUEUED_PROMPTS_STORAGE_PREFIX = "nanobot.webui.composerQueuedGuidance.v1:";
const EMPTY_COMPLETED_TURN_IDS: readonly string[] = [];
const QUEUED_PROMPTS_LIMIT = 20;
const SESSION_MENTIONS_LIMIT = 8;

function VoiceRecordingMeter({
  ariaLabel,
  className,
  elapsedLabel,
  isHero,
  levels,
}: {
  ariaLabel: string;
  className?: string;
  elapsedLabel: string;
  isHero: boolean;
  levels: number[];
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2 text-neutral-700 dark:text-white",
        isHero ? "h-8" : "h-9",
        className,
      )}
      aria-live="polite"
      aria-label={ariaLabel}
    >
      <span className="flex h-5 min-w-0 flex-1 items-center justify-between overflow-hidden" aria-hidden>
        {levels.map((height, index) => (
          <span
            key={index}
            className="w-[2px] rounded-full bg-current opacity-85 transition-[height] duration-75 ease-linear motion-reduce:transition-none"
            style={{ height }}
          />
        ))}
      </span>
      <span className="min-w-[2.1rem] text-right text-[12px] font-medium tabular-nums text-muted-foreground">
        {elapsedLabel}
      </span>
    </div>
  );
}

type SlashPalettePlacement = "above" | "below" | "beside";

interface SlashPaletteLayout {
  placement: SlashPalettePlacement;
  maxHeight: number;
}

interface QueuedPrompt {
  id: string;
  text: string;
  images?: QueuedPromptImage[];
  quotedContext?: string;
  sessionMentions?: SessionMention[];
  autoAfterTurnId?: string;
  autoPaused?: boolean;
}

function pauseQueuedPrompt(prompt: QueuedPrompt): QueuedPrompt {
  return { ...prompt, autoAfterTurnId: undefined, autoPaused: true };
}

function mergeQueuedPrompt(first: QueuedPrompt, next: QueuedPrompt): QueuedPrompt {
  const prompts = [first, next];
  const mentions = new Map<string, SessionMention>();
  for (const prompt of prompts) {
    for (const mention of prompt.sessionMentions ?? []) {
      if (!mentions.has(mention.session_key)) mentions.set(mention.session_key, mention);
    }
  }
  return {
    id: first.id,
    text: prompts.map((prompt) => prompt.text).filter(Boolean).join("\n"),
    images: prompts.flatMap((prompt) => prompt.images ?? []),
    quotedContext: [...new Set(prompts.map((prompt) => prompt.quotedContext).filter(Boolean))].join("\n\n"),
    sessionMentions: [...mentions.values()],
    autoAfterTurnId: first.autoAfterTurnId,
    autoPaused: prompts.some((prompt) => prompt.autoPaused),
  };
}

function queuedAttachmentBytes(image: QueuedPromptImage): number {
  const base64 = image.dataUrl.slice(image.dataUrl.indexOf(",") + 1);
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor(base64.length * 3 / 4) - padding;
}

interface QueuedPromptImage {
  dataUrl: string;
  name?: string;
  kind?: AttachmentKind;
}

interface CliAppMentionQuery {
  query: string;
  start: number;
  end: number;
}

type MentionCandidate = {
  name: string;
  displayName: string;
} & (
  | { kind: "session"; mention: SessionMention }
  | {
      kind: "cli" | "mcp";
      brandColor: string | null;
      logoUrl: string | null;
      initials: string;
    }
);

interface MentionInsertion {
  value: string;
  cursor: number;
  tokenStart: number;
  tokenEnd: number;
}

function mentionInsertion(
  value: string,
  name: string,
  start: number,
  end: number,
): MentionInsertion {
  const from = Math.min(Math.max(start, 0), value.length);
  const to = Math.min(Math.max(end, from), value.length);
  const prefix = value.slice(0, from);
  const suffix = value.slice(to);
  const leadingSpace = prefix && !/\s$/.test(prefix) ? " " : "";
  const trailingSpace = /^\s/.test(suffix) ? "" : " ";
  const tokenStart = prefix.length + leadingSpace.length;
  const tokenEnd = tokenStart + name.length + 1;
  return {
    value: `${prefix}${leadingSpace}@${name}${trailingSpace}${suffix}`,
    cursor: tokenEnd + trailingSpace.length,
    tokenStart,
    tokenEnd,
  };
}

function sessionMentionOptions(sessions: ChatSummary[]): SessionMention[] {
  return sessions.flatMap((session) => {
    if (!session.handle) return [];
    return [{
      id: session.handle.id,
      name: session.handle.name,
      session_key: session.key,
      title: session.title?.trim() || session.preview.trim(),
    }];
  });
}

interface SlashPaletteCommand {
  command: string;
  title: string;
  description: string;
  icon: string;
  kind?: "skill";
  argHint?: string;
  detail: string;
  badge?: string;
  recent: boolean;
}

function skillMatchRank(skill: SkillSummary, query: string): number | null {
  if (!query) return 0;
  const name = skill.name.toLowerCase();
  if (name === query) return 0;
  if (name.startsWith(query)) return 1;
  if (name.includes(query)) return 2;
  if (skill.description.toLowerCase().includes(query)) return 3;
  return null;
}

function slashCommandI18nKey(command: string): string {
  return command.replace(/^\//, "").replace(/-/g, "_");
}

function readSlashRecents(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(SLASH_RECENTS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string").slice(0, SLASH_RECENTS_LIMIT)
      : [];
  } catch {
    return [];
  }
}

function storeSlashRecents(commands: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      SLASH_RECENTS_STORAGE_KEY,
      JSON.stringify(commands.slice(0, SLASH_RECENTS_LIMIT)),
    );
  } catch {
    // localStorage may be unavailable in private contexts; command insertion still works.
  }
}

function queuedPromptsStorageKey(key?: string | null): string | null {
  const clean = key?.trim();
  return clean ? `${QUEUED_PROMPTS_STORAGE_PREFIX}${clean}` : null;
}

function normalizeQueuedSessionMentions(value: unknown): SessionMention[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const candidate = item as Partial<SessionMention>;
    const name = candidate.name?.trim().slice(0, 80);
    const sessionKey = candidate.session_key?.trim().slice(0, 512);
    if (
      !name
      || !sessionKey?.startsWith("websocket:")
      || !/^[\p{L}\p{N}_-]+$/u.test(name)
    ) return [];
    return [{
      ...(typeof candidate.id === "string" && /^handle_[a-f0-9]{32}$/i.test(candidate.id)
        ? { id: candidate.id }
        : {}),
      name,
      session_key: sessionKey,
      title: candidate.title?.trim().slice(0, 160) ?? "",
    }];
  });
}

function normalizeQueuedPrompt(item: unknown, index: number): QueuedPrompt | null {
  if (!item || typeof item !== "object") return null;
  const record = item as Partial<QueuedPrompt>;
  if (typeof record.text !== "string") return null;
  const text = record.text.trim();
  const images = Array.isArray(record.images)
    ? record.images.flatMap((image) => {
        if (!image || typeof image !== "object") return [];
        const candidate = image as Partial<QueuedPromptImage>;
        if (typeof candidate.dataUrl !== "string" || !candidate.dataUrl.startsWith("data:")) {
          return [];
        }
        const kind = candidate.kind === "file" || candidate.kind === "image"
          ? candidate.kind
          : candidate.dataUrl.startsWith("data:image/")
            ? "image"
            : "file";
        return [{
          dataUrl: candidate.dataUrl,
          kind,
          ...(typeof candidate.name === "string" && candidate.name.trim()
            ? { name: candidate.name.trim() }
            : {}),
        }];
      })
    : [];
  const quotedContext = typeof record.quotedContext === "string"
    ? record.quotedContext.trim()
    : "";
  const sessionMentions = normalizeQueuedSessionMentions(record.sessionMentions);
  if (!text && images.length === 0) return null;
  const id = typeof record.id === "string" && record.id.trim()
    ? record.id
    : `queued-prompt-restored-${index}`;
  return {
    id,
    text,
    ...(images.length > 0 ? { images } : {}),
    ...(quotedContext ? { quotedContext } : {}),
    ...(sessionMentions.length > 0 ? { sessionMentions } : {}),
    ...(typeof record.autoAfterTurnId === "string" && record.autoAfterTurnId.trim()
      ? { autoAfterTurnId: record.autoAfterTurnId.trim() }
      : {}),
    ...(record.autoPaused === true ? { autoPaused: true } : {}),
  };
}

function readQueuedPrompt(storageKey: string): QueuedPrompt | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return null;
    return parsed.slice(0, QUEUED_PROMPTS_LIMIT)
      .map((item, index) => normalizeQueuedPrompt(item, index))
      .filter((item): item is QueuedPrompt => item != null)
      .reduce<QueuedPrompt | null>((pending, prompt) => (
        pending ? mergeQueuedPrompt(pending, prompt) : prompt
      ), null);
  } catch {
    return null;
  }
}

function storeQueuedPrompt(storageKey: string, prompt: QueuedPrompt | null): void {
  if (typeof window === "undefined") return;
  try {
    if (!prompt) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    // Retain the v1 array shape so existing queued drafts remain readable.
    window.localStorage.setItem(storageKey, JSON.stringify([prompt]));
  } catch {
    // localStorage persistence is a convenience; the in-memory draft still works.
  }
}

interface QueuedPromptSnapshot {
  prompt: QueuedPrompt | null;
  sending: boolean;
  error: string | null;
}

// Delivery can outlive the composer during attachment upload or topic navigation.
// Keep one owner per mounted/sending topic; idle, unmounted owners are reloaded from storage.
const queuedPromptStores = new Map<string, QueuedPromptStore>();

class QueuedPromptStore {
  private snapshot: QueuedPromptSnapshot;
  private listeners = new Set<() => void>();

  constructor(private storageKey: string | null) {
    this.snapshot = { prompt: storageKey ? readQueuedPrompt(storageKey) : null, sending: false, error: null };
  }

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    if (this.storageKey) queuedPromptStores.set(this.storageKey, this);
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
      this.release();
    };
  };

  private release() {
    if (this.storageKey && !this.snapshot.sending && this.listeners.size === 0
      && queuedPromptStores.get(this.storageKey) === this) queuedPromptStores.delete(this.storageKey);
  }

  private publish(next: QueuedPromptSnapshot) {
    if (this.storageKey && next.prompt !== this.snapshot.prompt) storeQueuedPrompt(this.storageKey, next.prompt);
    this.snapshot = next;
    for (const listener of this.listeners) listener();
    this.release();
  }

  set = (next: QueuedPrompt | null | ((current: QueuedPrompt | null) => QueuedPrompt | null)) => {
    const prompt = typeof next === "function" ? next(this.snapshot.prompt) : next;
    if (prompt !== this.snapshot.prompt) this.publish({ ...this.snapshot, prompt, error: null });
  };

  send(prompt: QueuedPrompt, send: () => void | boolean | Promise<void | boolean>) {
    if (this.snapshot.sending) return;
    const retained = pauseQueuedPrompt(prompt);
    this.publish({ prompt: retained, sending: true, error: null });
    const finish = (accepted: void | boolean, error?: unknown) => {
      const failed = accepted === false || error !== undefined;
      this.publish({
        prompt: failed ? retained : null,
        sending: false,
        error: failed ? error instanceof Error ? error.message : "Message not sent; queued draft retained" : null,
      });
    };
    try {
      const result = send();
      if (result instanceof Promise) void result.then((accepted) => finish(accepted), (error: unknown) => finish(false, error));
      else finish(result);
    } catch (error) {
      finish(false, error);
    }
  }
}

function queuedPromptStoreFor(storageKey: string | null): QueuedPromptStore {
  if (!storageKey) return new QueuedPromptStore(null);
  let store = queuedPromptStores.get(storageKey);
  if (!store) {
    store = new QueuedPromptStore(storageKey);
    queuedPromptStores.set(storageKey, store);
  }
  return store;
}

function readyImagesToQueuedImages(
  images: Array<AttachedImage & { dataUrl: string }>,
): QueuedPromptImage[] {
  return images.map((img) => ({
    dataUrl: img.dataUrl,
    kind: img.kind,
    name: img.file.name,
  }));
}

function queuedImagesToSendImages(images?: QueuedPromptImage[]): SendAttachment[] | undefined {
  if (!images?.length) return undefined;
  return images.map((img) => ({
    media: {
      data_url: img.dataUrl,
      ...(img.name ? { name: img.name } : {}),
    },
    preview: {
      kind: img.kind ?? (img.dataUrl.startsWith("data:image/") ? "image" : "file"),
      url: img.dataUrl,
      ...(img.name ? { name: img.name } : {}),
    },
  }));
}

function queuedPromptLabel(prompt: QueuedPrompt): string {
  const text = prompt.text.trim();
  if (text) return text;
  return prompt.images?.map((img) => img.name).filter(Boolean).join(", ") || "File attachment";
}

function visualViewportBounds(): { top: number; bottom: number; height: number } {
  const viewport = window.visualViewport;
  if (!viewport) {
    return { top: 0, bottom: window.innerHeight, height: window.innerHeight };
  }
  const top = Math.max(0, viewport.offsetTop);
  const height = Math.max(0, viewport.height);
  return { top, bottom: top + height, height };
}

function getVisibleBounds(el: HTMLElement): { top: number; bottom: number } {
  // The app already follows the visual viewport on touch browsers. Measure
  // its frame in the same coordinates as the composer, not WebKit's pan offset.
  // During pinch zoom the app stops fitting, so use the zoomed viewport again.
  const fittedRoot = window.visualViewport?.scale === 1
    ? el.closest("#root.visual-viewport")
    : null;
  const viewport = fittedRoot?.getBoundingClientRect() ?? visualViewportBounds();
  let top = viewport.top;
  let bottom = viewport.bottom;
  let parent = el.parentElement;

  while (parent) {
    const style = window.getComputedStyle(parent);
    if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) {
      const rect = parent.getBoundingClientRect();
      top = Math.max(top, rect.top);
      bottom = Math.min(bottom, rect.bottom);
    }
    parent = parent.parentElement;
  }

  return { top, bottom };
}

function goalStateStripPreview(
  goal: GoalStateWsPayload | undefined,
  t: (key: string) => string,
): string | null {
  if (!goal?.active) return null;
  const summary = goal.ui_summary?.trim();
  if (summary) return summary;
  const obj = goal.objective?.trim();
  if (obj) return obj.length > 72 ? `${obj.slice(0, 72)}…` : obj;
  return t("thread.composer.goalStateFallback");
}

const GOAL_PANEL_VIEWPORT_TOP_PAD = 20;
const GOAL_PANEL_GAP_ABOVE_STRIP_PX = 10;
const GOAL_PANEL_MIN_HEIGHT_PX = 112;
const GOAL_PANEL_MAX_VIEWPORT_RATIO = 0.62;

function measureGoalPanelMaxCssHeight(stripTopY: number): number {
  const viewport = visualViewportBounds();
  const spaceAboveStrip =
    stripTopY - viewport.top - GOAL_PANEL_VIEWPORT_TOP_PAD - GOAL_PANEL_GAP_ABOVE_STRIP_PX;
  return Math.min(
    Math.max(spaceAboveStrip, GOAL_PANEL_MIN_HEIGHT_PX),
    Math.floor(viewport.height * GOAL_PANEL_MAX_VIEWPORT_RATIO),
  );
}

function buildGoalMarkdownBody(summary: string, objective: string): string {
  const s = summary.trim();
  const o = objective.trim();
  if (s && o) return `${s}\n\n---\n\n${o}`;
  return o || s;
}

function cliAppMentionPayload(app: CliAppInfo): OutboundCliAppMention {
  return {
    name: app.name,
    display_name: app.display_name,
    category: app.category,
    entry_point: app.entry_point,
    logo_url: app.logo_url ?? null,
    brand_color: app.brand_color ?? null,
  };
}

function mcpPresetMentionPayload(preset: McpPresetInfo): OutboundMcpPresetMention {
  return {
    name: preset.name,
    display_name: preset.display_name,
    category: preset.category,
    transport: preset.transport,
    status: preset.status,
    configured: preset.configured,
    logo_url: preset.logo_url ?? null,
    brand_color: preset.brand_color ?? null,
  };
}

function GoalStateStrip({
  goalState,
}: {
  goalState?: GoalStateWsPayload;
}) {
  const { t } = useTranslation();
  const [goalPanelOpen, setGoalPanelOpen] = useState(false);
  const stripLabel = goalStateStripPreview(goalState, t);
  const active = !!stripLabel?.trim();
  const [, setTick] = useState(0);
  const stripWrapperRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const expandToggleRef = useRef<HTMLButtonElement>(null);
  const stripSnapshotRef = useRef<{
    goalState?: GoalStateWsPayload;
    stripLabel: string | null;
  } | null>(null);
  const [panelMaxPx, setPanelMaxPx] = useState(280);

  if (active) {
    stripSnapshotRef.current = { goalState, stripLabel };
  }

  useEffect(() => {
    if (!active) setGoalPanelOpen(false);
  }, [active]);

  const display = active
    ? { goalState, stripLabel }
    : stripSnapshotRef.current;
  const displayGoalState = display?.goalState;
  const displayStripLabel = display?.stripLabel ?? null;

  const objectiveFull = displayGoalState?.objective?.trim() ?? "";
  const summaryFull = displayGoalState?.ui_summary?.trim() ?? "";
  const canExpandGoal = !!(active && displayGoalState?.active && (objectiveFull || summaryFull));

  const markdownBody =
    objectiveFull || summaryFull
      ? buildGoalMarkdownBody(summaryFull, objectiveFull)
      : "";

  useLayoutEffect(() => {
    if (!goalPanelOpen) return;

    function relayout(): void {
      const el = stripWrapperRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      setPanelMaxPx(measureGoalPanelMaxCssHeight(top));
    }

    relayout();

    void preloadMarkdownText();
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => relayout())
        : null;
    if (stripWrapperRef.current && ro) {
      ro.observe(stripWrapperRef.current);
    }
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", relayout);
    viewport?.addEventListener("scroll", relayout);
    window.addEventListener("resize", relayout);
    window.addEventListener("scroll", relayout, true);
    return () => {
      ro?.disconnect();
      viewport?.removeEventListener("resize", relayout);
      viewport?.removeEventListener("scroll", relayout);
      window.removeEventListener("resize", relayout);
      window.removeEventListener("scroll", relayout, true);
    };
  }, [goalPanelOpen]);

  useEffect(() => {
    if (!goalPanelOpen) return;

    function onPointerDown(ev: MouseEvent): void {
      const target = ev.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target)) return;
      if (expandToggleRef.current?.contains(target)) return;
      setGoalPanelOpen(false);
    }

    function onKey(ev: KeyboardEvent): void {
      if (ev.key === "Escape") setGoalPanelOpen(false);
    }

    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [goalPanelOpen]);

  if (!display) return null;

  const ariaLabel = displayStripLabel
    ? t("thread.composer.goalStateStrip", { label: displayStripLabel })
    : t("thread.composer.goalStateFallback");

  return (
    <div
      ref={stripWrapperRef}
      className="composer-status-drawer relative z-30"
      data-composer-status-drawer=""
      data-state={active ? "open" : "closed"}
      aria-hidden={active ? undefined : true}
      onTransitionEnd={(event) => {
        if (active || event.target !== event.currentTarget) return;
        stripSnapshotRef.current = null;
        setTick((n) => n + 1);
      }}
    >
      {goalPanelOpen && canExpandGoal && markdownBody ? (
        <div
          ref={panelRef}
          id="nanobot-goal-panel-root"
          role="dialog"
          aria-modal="false"
          aria-labelledby="nanobot-goal-panel-title"
          tabIndex={-1}
          className={cn(
            "absolute bottom-[calc(100%+8px)] left-3 right-3 z-[50] flex max-w-none flex-col overflow-hidden",
            "rounded-2xl",
            floatingSurfaceElevationClassName,
          )}
          style={{ maxHeight: `${Math.round(panelMaxPx)}px` }}
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-black/[0.06] px-3 py-2 dark:border-white/[0.08]">
            <h2
              id="nanobot-goal-panel-title"
              className="min-w-0 truncate text-[13px] font-semibold tracking-tight text-foreground"
            >
              {t("thread.composer.goalStateSheetTitle")}
            </h2>
            <button
              type="button"
              className={cn(
                "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                "text-muted-foreground transition-colors hover:text-foreground",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
              aria-label={t("thread.composer.goalStateCloseAria")}
              onClick={() => setGoalPanelOpen(false)}
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
          <div
            id="nanobot-goal-panel-scroll"
            className="min-h-0 flex-1 overflow-y-auto scrollbar-thin px-3 pb-3 pt-2"
          >
            <MarkdownText className="max-w-none text-[13.5px] leading-relaxed text-foreground/90">
              {markdownBody}
            </MarkdownText>
          </div>
        </div>
      ) : null}
      <div className="composer-status-drawer-clip">
        {display ? (
          <div
            className="composer-status-drawer-content flex min-h-[36px] items-center gap-2 px-3 py-2"
            role="status"
            aria-label={ariaLabel}
          >
            <GoalIcon className="h-4 w-4 shrink-0 text-primary/75" aria-hidden />
            <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[12px] font-medium text-foreground/75">
              {displayStripLabel ? (
                <span className="truncate">
                  {t("thread.composer.goalStateStrip", { label: displayStripLabel })}
                </span>
              ) : null}
            </span>
            {canExpandGoal ? (
              <button
                ref={expandToggleRef}
                type="button"
                className={cn(
                  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                  "text-muted-foreground transition-colors hover:text-foreground",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
                aria-expanded={goalPanelOpen}
                aria-controls={goalPanelOpen ? "nanobot-goal-panel-root" : undefined}
                aria-label={t("thread.composer.goalStateExpandAria")}
                title={t("thread.composer.goalStateExpandAria")}
                onClick={() => setGoalPanelOpen((o) => !o)}
              >
                {goalPanelOpen ? (
                  <ChevronDown className="h-4 w-4" aria-hidden />
                ) : (
                  <ChevronUp className="h-4 w-4" aria-hidden />
                )}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ThreadComposer({
  onSend,
  disabled,
  placeholder,
  inputAriaLabel,
  compactWhenIdle = false,
  isStreaming = false,
  activeTurnId = null,
  completedTurnIds = EMPTY_COMPLETED_TURN_IDS,
  modelLabel = null,
  modelDetail = null,
  modelPreset = null,
  modelPresets = [],
  onModelPresetChange,
  modelProvider = null,
  modelProviderLabel = null,
  modelNeedsSetup = false,
  onModelBadgeClick,
  onManageModels,
  contextUsage = null,
  recentRoundUsage = [],
  variant = "thread",
  slashCommands = [],
  onMentionSearch,
  cliApps = [],
  mcpPresets = [],
  sessions = [],
  skills = [],
  onStop,
  surfaceRef,
  onTranscribeAudio,
  goalState,
  workspaceScope = null,
  workspaceControlsHidden = false,
  workspacePickerLayoutAnchor,
  workspaceDefaultScope = null,
  workspaceControls = null,
  workspaceScopeDisabled = false,
  workspaceError = null,
  onLoadWorkspaceProjects,
  onResolveWorkspaceProject,
  onFavoriteWorkspaceProject,
  onBrowseWorkspaceDirectories,
  onWorkspaceScopeChange,
  pendingQueueKey = null,
  draftKey,
  draftStore,
  persistDraft = false,
  transcriptionProvider = null,
  ingressLimits = null,
  quotedContext = null,
  focusRequest = 0,
  onQuotedContextChange,
}: ThreadComposerProps) {
  const { t } = useTranslation();
  const [initialDraft] = useState(() => draftKey ? draftStore?.get(draftKey, persistDraft) : undefined);
  const [value, setValue] = useState(initialDraft?.text ?? "");
  const [composerFocused, setComposerFocused] = useState(false);
  const blurFrame = useRef<number | null>(null);
  const [selectedSessionMentions, setSelectedSessionMentions] = useState<SessionMention[]>(
    initialDraft?.sessionMentions ?? [],
  );
  const [sessionDragPreview, setSessionDragPreview] = useState<{
    mention: SessionMention;
    start: number;
    end: number;
  } | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [sendPending, setSendPending] = useState(false);
  const [modelSetupAttentionRequest, setModelSetupAttentionRequest] = useState(0);
  const queuedPromptStorageKey = queuedPromptsStorageKey(pendingQueueKey);
  const queuedPromptStore = useMemo(() => queuedPromptStoreFor(queuedPromptStorageKey), [queuedPromptStorageKey]);
  const queueSnapshot = useSyncExternalStore(queuedPromptStore.subscribe, queuedPromptStore.getSnapshot);
  const queuedPrompt = queueSnapshot.prompt;
  const setQueuedPrompt = queuedPromptStore.set;
  const interactionDisabled = !!disabled || sendPending || queueSnapshot.sending;
  useEffect(() => {
    if (queueSnapshot.error) setInlineError(queueSnapshot.error);
  }, [queueSnapshot.error]);
  const [voiceErrorFading, setVoiceErrorFading] = useState(false);
  const [slashMenuDismissed, setSlashMenuDismissed] = useState(false);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const [cliAppMenuDismissed, setCliAppMenuDismissed] = useState(false);
  const [selectedCliAppIndex, setSelectedCliAppIndex] = useState(0);
  const [cursorPosition, setCursorPosition] = useState(0);
  const [recentSlashCommands, setRecentSlashCommands] = useState<string[]>(() => readSlashRecents());
  const hasTouchPrimaryPointer = useMediaQuery("(hover: none) and (pointer: coarse)");
  // Coarser than hasTouchPrimaryPointer on purpose: tablets with a physical
  // keyboard still get the newline-on-Enter behavior.
  const hasCoarsePointer = useMediaQuery("(pointer: coarse)");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mentionOverlayRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const [compactControls, setCompactControls] = useState(false);

  useLayoutEffect(() => {
    const form = formRef.current;
    if (!form) return;
    let previousWidth = 0;
    const update = () => {
      const width = form.getBoundingClientRect().width;
      if (width <= 0 || width === previousWidth) return;
      previousWidth = width;
      setCompactControls(width <= 512);
      const input = textareaRef.current;
      if (input) {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 260)}px`;
      }
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(form);
    window.addEventListener("resize", update);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chipRefs = useRef(new Map<string, HTMLButtonElement>());
  const queuedPromptCounterRef = useRef(0);
  // A fresh queue submission arms Enter for the complete pending message.
  const secondEnterPromptIdRef = useRef<string | null>(null);
  const previousPendingQueueKeyRef = useRef(pendingQueueKey);
  const previousQueueRunRef = useRef({ key: pendingQueueKey, isStreaming });
  const voiceShortcutDownRef = useRef(false);
  const voiceErrorFadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isHero = variant === "hero";
  const voiceShortcutLabel = useMemo(getVoiceShortcutLabel, []);
  const projectPickerAvailable =
    isHero
    && !!workspaceDefaultScope
    && !!onWorkspaceScopeChange
    && !!onLoadWorkspaceProjects
    && !!onBrowseWorkspaceDirectories
    && !!onResolveWorkspaceProject
    && !!onFavoriteWorkspaceProject
    && workspaceControls?.can_change_project !== false;
  const showProjectPicker = projectPickerAvailable && !workspaceControlsHidden;

  useEffect(() => {
    secondEnterPromptIdRef.current = null;
  }, [pendingQueueKey, queuedPromptStorageKey]);

  useEffect(() => {
    if (!isStreaming || !activeTurnId) return;
    setQueuedPrompt((prompt) => (
      !prompt || prompt.autoPaused || prompt.autoAfterTurnId === activeTurnId
        ? prompt
        : { ...prompt, autoAfterTurnId: activeTurnId }
    ));
  }, [activeTurnId, isStreaming, pendingQueueKey, setQueuedPrompt]);

  const resolvedPlaceholder = isStreaming
    ? t("thread.composer.placeholderStreaming")
    : placeholder ?? t("thread.composer.placeholderThread");

  const maxAttachments = ingressLimits?.attachments.max_count
    ?? MAX_ATTACHMENTS_PER_MESSAGE;
  const maxTextBytes = ingressLimits?.message.max_text_bytes ?? 64 * 1024;
  const { images, enqueue, remove, clear, restoreReadyImages, encoding, full } =
    useAttachedImages({ ingressLimits });
  const restoredDraftAttachments = useRef(false);
  const [draftAttachmentsReady, setDraftAttachmentsReady] = useState(!initialDraft?.files.length);
  useLayoutEffect(() => {
    if (restoredDraftAttachments.current) return;
    restoredDraftAttachments.current = true;
    if (initialDraft?.files.length) enqueue(initialDraft.files, { restoringDraft: true });
    setDraftAttachmentsReady(true);
  }, [enqueue, initialDraft]);

  const formatRejection = useCallback(
    (reason: AttachmentError): string => {
      const key = `thread.composer.imageRejected.${reason}`;
      const fallback = reason === "too_many_attachments"
        ? `Max ${maxAttachments} attachments per message`
        : reason === "empty_file"
          ? "Empty files cannot be attached"
          : reason === "total_too_large"
            ? "Attachments are too large together — remove some or use smaller files"
            : reason === "too_large"
              ? "File is too large"
              : "Unsupported file type";
      return t(key, { max: maxAttachments, defaultValue: fallback });
    },
    [maxAttachments, t],
  );

  const textTooLargeMessage = useCallback(
    () => t("thread.composer.textTooLarge", {
      max: formatBytes(maxTextBytes),
      defaultValue: `Message text is too large (max ${formatBytes(maxTextBytes)})`,
    }),
    [maxTextBytes, t],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      if (interactionDisabled || files.length === 0) return;
      secondEnterPromptIdRef.current = null;
      const { rejected } = enqueue(files);
      if (rejected.length > 0) {
        setInlineError(formatRejection(rejected[0].reason));
      } else {
        setInlineError(null);
      }
    },
    [enqueue, formatRejection, interactionDisabled],
  );

  const {
    isDragging,
    onPaste,
    onDragEnter,
    onDragOver,
    onDragLeave,
    onDrop,
  } = useClipboardAndDrop(addFiles);

  useEffect(() => {
    if (compactWhenIdle || interactionDisabled || hasTouchPrimaryPointer || (workspaceError && showProjectPicker)) {
      return;
    }
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [compactWhenIdle, hasTouchPrimaryPointer, interactionDisabled, showProjectPicker, workspaceError]);

  useEffect(() => () => {
    if (blurFrame.current !== null) cancelAnimationFrame(blurFrame.current);
  }, []);

  useEffect(() => {
    if (!focusRequest || interactionDisabled) return;
    const id = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [focusRequest, interactionDisabled]);

  const normalizedQuotedContext = quotedContext?.trim() || null;

  const readyImages = useMemo(
    () => images.filter((img): img is AttachedImage & { dataUrl: string } =>
      img.status === "ready" && typeof img.dataUrl === "string",
    ),
    [images],
  );
  const hasErrors = images.some((img) => img.status === "error");

  const hasComposerContent = value.trim().length > 0 || readyImages.length > 0;
  const canSend =
    !interactionDisabled
    && !modelNeedsSetup
    && !encoding
    && !hasErrors
    && hasComposerContent;
  const canOpenModelSettings = Boolean(
    modelNeedsSetup && onModelBadgeClick && !interactionDisabled,
  );
  const canQueueGuidance =
    isStreaming
    && !interactionDisabled
    && !modelNeedsSetup
    && !encoding
    && !hasErrors
    && hasComposerContent
    // Without command metadata, let the gateway classify slash input immediately.
    && (slashCommands.length > 0
      ? !isRegisteredSlashCommand(value, slashCommands)
      : !value.trimStart().startsWith("/"));

  const slashQuery = useMemo(() => {
    if (interactionDisabled || slashMenuDismissed || !value.startsWith("/")) return null;
    const commandToken = value.slice(1);
    if (/\s/.test(commandToken)) return null;
    return commandToken.toLowerCase();
  }, [interactionDisabled, slashMenuDismissed, value]);

  const skillQuery = useMemo(() => {
    if (interactionDisabled || slashMenuDismissed) return null;
    const caret = Math.min(Math.max(cursorPosition, 0), value.length);
    const beforeCaret = value.slice(0, caret);
    const match = /\$([A-Za-z0-9_-]*)$/i.exec(beforeCaret);
    if (!match) return null;
    return {
      end: caret,
      start: match.index,
      text: match[1].toLowerCase(),
    };
  }, [cursorPosition, interactionDisabled, slashMenuDismissed, value]);

  const skillMenuActive = skillQuery !== null;
  useEffect(() => {
    // Also refresh an empty menu: skills may have been installed by the agent.
    if (skillMenuActive) requestSkillsRefresh();
  }, [skillMenuActive]);

  const visibleSlashCommands = useMemo(() => {
    if (!(isStreaming && onStop)) return slashCommands;
    const stopCommand = slashCommands.find((command) => command.command === "/stop");
    if (!stopCommand) return slashCommands;
    return [
      stopCommand,
      ...slashCommands.filter((command) => command.command !== "/stop"),
    ];
  }, [isStreaming, onStop, slashCommands]);

  const filteredSlashCommands = useMemo<SlashPaletteCommand[]>(() => {
    if (skillQuery !== null) {
      const query = skillQuery.text;
      return skills
        .filter((skill) => skill.enabled !== false && skill.available)
        .flatMap((skill) => {
          const matchRank = skillMatchRank(skill, query);
          return matchRank === null
            ? []
            : [{
                command: `$${skill.name}`,
                matchRank,
                skill,
              }];
        })
        .sort((a, b) => {
          if (a.matchRank !== b.matchRank) return a.matchRank - b.matchRank;
          if (query !== "") return 0;
          const aRecent = recentSlashCommands.indexOf(a.command);
          const bRecent = recentSlashCommands.indexOf(b.command);
          if (aRecent === -1 && bRecent === -1) return 0;
          if (aRecent === -1) return 1;
          if (bRecent === -1) return -1;
          return aRecent - bRecent;
        })
        .slice(0, 8)
        .map(({ command, skill }) => {
          const description = skill.description || skill.name;
          return {
            command,
            title: skill.name,
            description,
            detail: description,
            icon: "brain",
            kind: "skill" as const,
            recent: recentSlashCommands.includes(command),
          };
        });
    }
    if (slashQuery === null) return [];
    const withDetails = visibleSlashCommands
      .filter((command) => {
        if (
          slashQuery === ""
          && (
            command.command === "/restart"
            || (command.command === "/stop" && !(isStreaming && onStop))
          )
        ) {
          return false;
        }
        const commandKey = slashCommandI18nKey(command.command);
        const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
          defaultValue: command.title,
        });
        const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
          defaultValue: command.description,
        });
        const haystack = [
          command.command,
          command.title,
          command.description,
          command.argHint ?? "",
          title,
          description,
        ].join(" ").toLowerCase();
        return haystack.includes(slashQuery);
      })
      .map((command) => {
        const commandKey = slashCommandI18nKey(command.command);
        const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
          defaultValue: command.description,
        });
        let detail = description;
        let badge: string | undefined;
        if (command.command === "/model" && modelLabel) {
          detail = modelLabel;
          badge = t("thread.composer.slash.badges.current");
        } else if (command.command === "/goal") {
          detail = goalState?.active
            ? t("thread.composer.slash.details.goalActive")
            : t("thread.composer.slash.details.goalReady");
        } else if (command.command === "/stop" && isStreaming) {
          detail = t("thread.composer.slash.details.stopRunning");
        } else if (command.command === "/history") {
          detail = t("thread.composer.slash.details.history");
        }
        return {
          ...command,
          detail,
          badge,
          recent: recentSlashCommands.includes(command.command),
        };
      })
      .sort((a, b) => {
        if (isStreaming) {
          if (a.command === "/stop") return -1;
          if (b.command === "/stop") return 1;
        }
        if (slashQuery !== "") return 0;
        const aRecent = recentSlashCommands.indexOf(a.command);
        const bRecent = recentSlashCommands.indexOf(b.command);
        if (aRecent !== -1 || bRecent !== -1) {
          if (aRecent === -1) return 1;
          if (bRecent === -1) return -1;
          return aRecent - bRecent;
        }
        return 0;
      });

    return withDetails
      .slice(0, 8);
  }, [goalState?.active, isStreaming, modelLabel, recentSlashCommands, skills, skillQuery, slashQuery, t, visibleSlashCommands]);

  const showSlashMenu = filteredSlashCommands.length > 0;
  const cliAppMention = useMemo<CliAppMentionQuery | null>(() => {
    if (interactionDisabled || cliAppMenuDismissed) return null;
    const caret = Math.min(Math.max(cursorPosition, 0), value.length);
    const beforeCaret = value.slice(0, caret);
    const match = /(?:^|\s)@([\p{L}\p{N}_-]*)$/iu.exec(beforeCaret);
    if (!match) return null;
    const query = match[1].toLowerCase();
    return {
      query,
      start: caret - query.length - 1,
      end: caret,
    };
  }, [cliAppMenuDismissed, cursorPosition, interactionDisabled, value]);

  const mentionSearchActive = cliAppMention !== null;
  useEffect(() => {
    if (mentionSearchActive) onMentionSearch?.();
  }, [mentionSearchActive, onMentionSearch]);

  const availableSessionMentions = useMemo(
    () => sessionMentionOptions(sessions),
    [sessions],
  );
  const mentionSegments = useMemo(
    () => splitCapabilityMentionSegments(value, cliApps, mcpPresets, selectedSessionMentions),
    [cliApps, mcpPresets, selectedSessionMentions, value],
  );
  const editMentionInput = useCallback((next: string, cursor: number) => {
    secondEnterPromptIdRef.current = null;
    setValue(next);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setCursorPosition(cursor);
  }, []);
  const mentionInput = useComposerMentionInput({
    segments: mentionSegments,
    inputRef: textareaRef,
    onEdit: editMentionInput,
    resetKey: pendingQueueKey,
  });
  const { rawSelection, replace: replaceMentionInput } = mentionInput;
  const draftText = composerMentionText(mentionInput.segments).raw;
  useLayoutEffect(() => {
    if (!draftKey || !draftStore || !draftAttachmentsReady) return;
    if (!draftText && images.length === 0 && !quotedContext) {
      draftStore.delete(draftKey);
      return;
    }
    draftStore.set(draftKey, {
      text: draftText,
      files: images.map((image) => image.file),
      sessionMentions: selectedSessionMentions,
      quotedContext,
    }, persistDraft);
  }, [draftAttachmentsReady, draftKey, draftStore, images, persistDraft, quotedContext, selectedSessionMentions, draftText]);
  const sessionDragInsertion = sessionDragPreview
    ? mentionInsertion(
        value,
        sessionDragPreview.mention.name,
        sessionDragPreview.start,
        sessionDragPreview.end,
      )
    : null;
  const displayMentionSegments = sessionDragInsertion && sessionDragPreview
    ? splitCapabilityMentionSegments(
        sessionDragInsertion.value,
        cliApps,
        mcpPresets,
        [...selectedSessionMentions, sessionDragPreview.mention],
      )
    : mentionInput.segments;
  const activeSessionMentions = useMemo(() => {
    const seen = new Set<string>();
    return mentionSegments.flatMap((segment) => {
      if (segment.kind !== "session" || seen.has(segment.mention.session_key)) return [];
      seen.add(segment.mention.session_key);
      return [segment.mention];
    });
  }, [mentionSegments]);
  const filteredMentionCandidates = useMemo<MentionCandidate[]>(() => {
    if (!cliAppMention) return [];
    const sessionCandidates: MentionCandidate[] = availableSessionMentions
      .filter((mention) => (
        activeSessionMentions.length < SESSION_MENTIONS_LIMIT
        || activeSessionMentions.some(
          (selected) => selected.session_key === mention.session_key,
        )
      ))
      .filter((mention) => [
        mention.name,
        mention.title,
      ].join(" ").toLowerCase().includes(cliAppMention.query))
      .map((mention) => ({
        kind: "session",
        name: mention.name,
        displayName: mention.title || mention.name,
        mention,
      }));
    const sessionNames = new Set(
      availableSessionMentions.map((mention) => mention.name.toLowerCase()),
    );
    const cliCandidates: MentionCandidate[] = cliApps
      .filter((app) => app.installed)
      .filter((app) => !sessionNames.has(app.name.toLowerCase()))
      .filter((app) => {
        const haystack = [
          app.name,
          app.display_name,
          app.category,
          app.description,
          app.entry_point,
        ].join(" ").toLowerCase();
        return haystack.includes(cliAppMention.query);
      })
      .map((app) => ({
        kind: "cli",
        name: app.name,
        displayName: app.display_name,
        brandColor: app.brand_color ?? null,
        logoUrl: app.logo_url ?? null,
        initials: cliAppInitials(app),
      }));
    const mcpCandidates: MentionCandidate[] = mcpPresets
      .filter((preset) => preset.installed && preset.configured)
      .filter((preset) => !sessionNames.has(preset.name.toLowerCase()))
      .filter((preset) => {
        const haystack = [
          preset.name,
          preset.display_name,
          preset.category,
          preset.description,
          preset.transport,
        ].join(" ").toLowerCase();
        return haystack.includes(cliAppMention.query);
      })
      .map((preset) => ({
        kind: "mcp",
        name: preset.name,
        displayName: preset.display_name,
        brandColor: preset.brand_color ?? null,
        logoUrl: preset.logo_url ?? null,
        initials: mcpPresetInitials(preset),
      }));
    const groups = [
      { candidates: sessionCandidates, reserved: 4 },
      { candidates: cliCandidates, reserved: 2 },
      { candidates: mcpCandidates, reserved: 2 },
    ];
    let remaining = 8;
    const counts = groups.map(({ candidates, reserved }) => {
      const count = Math.min(candidates.length, reserved);
      remaining -= count;
      return count;
    });
    for (const index of [0, 1, 2]) {
      const extra = Math.min(remaining, groups[index].candidates.length - counts[index]);
      counts[index] += extra;
      remaining -= extra;
    }
    return groups.flatMap(({ candidates }, index) => candidates.slice(0, counts[index]));
  }, [activeSessionMentions, availableSessionMentions, cliAppMention, cliApps, mcpPresets]);

  const showCliAppMenu = filteredMentionCandidates.length > 0;
  const showAnyPalette = showSlashMenu || showCliAppMenu;
  const hasMentionDecorations = displayMentionSegments.some(
    (segment) => segment.kind !== "text",
  );
  const activeCliMentionApps = useMemo(() => {
    const seen = new Set<string>();
    return mentionSegments.flatMap((segment) => {
      if (segment.kind !== "cli" || seen.has(segment.app.name)) return [];
      seen.add(segment.app.name);
      return [segment.app];
    });
  }, [mentionSegments]);
  const activeMcpPresetMentions = useMemo(() => {
    const seen = new Set<string>();
    return mentionSegments.flatMap((segment) => {
      if (segment.kind !== "mcp" || seen.has(segment.preset.name)) return [];
      seen.add(segment.preset.name);
      return [segment.preset];
    });
  }, [mentionSegments]);
  const [slashPaletteLayout, setSlashPaletteLayout] = useState<SlashPaletteLayout>({
    placement: "above",
    maxHeight: SLASH_PALETTE_MAX_HEIGHT_PX,
  });

  useEffect(() => {
    setSelectedCommandIndex(0);
  }, [slashQuery]);

  useEffect(() => {
    setSelectedCliAppIndex(0);
  }, [cliAppMention?.query]);

  useEffect(() => {
    if (selectedCommandIndex >= filteredSlashCommands.length) {
      setSelectedCommandIndex(0);
    }
  }, [filteredSlashCommands.length, selectedCommandIndex]);

  useEffect(() => {
    if (selectedCliAppIndex >= filteredMentionCandidates.length) {
      setSelectedCliAppIndex(0);
    }
  }, [filteredMentionCandidates.length, selectedCliAppIndex]);

  useEffect(() => {
    if (!showAnyPalette) return;

    const dismissOnPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && formRef.current?.contains(target)) return;
      setSlashMenuDismissed(true);
      setCliAppMenuDismissed(true);
    };

    document.addEventListener("pointerdown", dismissOnPointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown, true);
    };
  }, [showAnyPalette]);

  useLayoutEffect(() => {
    if (!showAnyPalette) return;

    const updateLayout = () => {
      const form = formRef.current;
      if (!form) return;
      const rect = form.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;

      const bounds = getVisibleBounds(form);
      const spaceAbove = Math.max(0, rect.top - bounds.top - SLASH_PALETTE_GAP_PX);
      const spaceBelow = Math.max(0, bounds.bottom - rect.bottom - SLASH_PALETTE_GAP_PX);
      // A landscape keyboard can leave less height than one input and option.
      // Use the available width instead of clipping an absolute menu in the
      // short viewport's scrollable composer footer.
      const beside = rect.width >= 640
        && !!form.closest("#root.short-visual-viewport");
      const placement: SlashPalettePlacement =
        beside ? "beside" : spaceAbove >= SLASH_PALETTE_MIN_HEIGHT_PX || spaceAbove >= spaceBelow
          ? "above"
          : "below";
      const available = beside
        ? Math.max(0, bounds.bottom - bounds.top)
        : placement === "above" ? spaceAbove : spaceBelow;
      const maxHeight = Math.min(SLASH_PALETTE_MAX_HEIGHT_PX, available);

      setSlashPaletteLayout((current) =>
        current.placement === placement && current.maxHeight === maxHeight
          ? current
          : { placement, maxHeight },
      );
    };

    updateLayout();
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", updateLayout);
    viewport?.addEventListener("scroll", updateLayout);
    window.addEventListener("resize", updateLayout);
    document.addEventListener("scroll", updateLayout, true);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateLayout);
    if (formRef.current) observer?.observe(formRef.current);
    return () => {
      observer?.disconnect();
      viewport?.removeEventListener("resize", updateLayout);
      viewport?.removeEventListener("scroll", updateLayout);
      window.removeEventListener("resize", updateLayout);
      document.removeEventListener("scroll", updateLayout, true);
    };
  }, [filteredMentionCandidates.length, filteredSlashCommands.length, showAnyPalette]);

  const resizeTextarea = useCallback((restoreFocus = true) => {
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
      if (restoreFocus) el.focus();
    });
  }, []);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el || mentionInput.isComposing) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
    if (mentionOverlayRef.current) mentionOverlayRef.current.scrollTop = el.scrollTop;
  }, [compactControls, mentionInput.isComposing, mentionInput.value]);

  // Runs before paint so switching sessions never flashes stale draft text.
  useLayoutEffect(() => {
    if (previousPendingQueueKeyRef.current === pendingQueueKey) return;
    previousPendingQueueKeyRef.current = pendingQueueKey;
    secondEnterPromptIdRef.current = null;
    setValue("");
    setSelectedSessionMentions([]);
    setInlineError(null);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setCursorPosition(0);
    clear();
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
    });
  }, [clear, pendingQueueKey]);

  const appendTranscription = useCallback((text: string) => {
    const transcript = text.trim();
    if (!transcript) return;
    secondEnterPromptIdRef.current = null;
    setValue((current) => {
      if (!current.trim()) return transcript;
      const separator = /[\s\n]$/.test(current) ? "" : " ";
      return `${current}${separator}${transcript}`;
    });
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setInlineError(null);
    resizeTextarea();
  }, [resizeTextarea]);

  const clearVoiceErrorTimers = useCallback(() => {
    if (voiceErrorFadeTimerRef.current !== null) clearTimeout(voiceErrorFadeTimerRef.current);
    voiceErrorFadeTimerRef.current = null;
  }, []);
  const clearInlineError = useCallback(() => {
    clearVoiceErrorTimers();
    setVoiceErrorFading(false);
    setInlineError(null);
  }, [clearVoiceErrorTimers]);
  const setVoiceError = useCallback((key: VoiceRecorderErrorKey) => {
    clearVoiceErrorTimers();
    setVoiceErrorFading(false);
    setInlineError(t(`thread.composer.voiceErrors.${key}`));
    voiceErrorFadeTimerRef.current = setTimeout(() => {
      setVoiceErrorFading(true);
      voiceErrorFadeTimerRef.current = setTimeout(() => {
        setInlineError(null);
        setVoiceErrorFading(false);
        voiceErrorFadeTimerRef.current = null;
      }, VOICE_ERROR_FADE_MS);
    }, VOICE_ERROR_VISIBLE_MS);
  }, [clearVoiceErrorTimers, t]);
  const voiceRecorder = useVoiceRecorder({
    disabled: interactionDisabled,
    onClearError: clearInlineError,
    onError: setVoiceError,
    onTranscript: appendTranscription,
    onTranscribeAudio,
    wantsWav: transcriptionProvider === "xiaomi_mimo",
  });

  useEffect(() => () => clearVoiceErrorTimers(), [clearVoiceErrorTimers]);

  useEffect(() => {
    if (!onTranscribeAudio) return;

    function onKeyDown(event: KeyboardEvent): void {
      if (!isVoiceShortcutDown(event) || event.repeat || voiceShortcutDownRef.current) return;
      event.preventDefault();
      secondEnterPromptIdRef.current = null;
      voiceShortcutDownRef.current = true;
      voiceRecorder.beginShortcutHold();
    }

    function onKeyUp(event: KeyboardEvent): void {
      if (!voiceShortcutDownRef.current || !isVoiceShortcutRelease(event)) return;
      event.preventDefault();
      voiceShortcutDownRef.current = false;
      voiceRecorder.endShortcutHold();
    }

    function onWindowBlur(): void {
      if (!voiceShortcutDownRef.current) return;
      voiceShortcutDownRef.current = false;
      voiceRecorder.endShortcutHold();
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onWindowBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onWindowBlur);
    };
  }, [onTranscribeAudio, voiceRecorder.beginShortcutHold, voiceRecorder.endShortcutHold]);

  const handleStop = useCallback(() => {
    secondEnterPromptIdRef.current = null;
    setQueuedPrompt((prompt) => prompt ? pauseQueuedPrompt(prompt) : null);
    onStop?.();
  }, [onStop, setQueuedPrompt]);

  const chooseSlashCommand = useCallback(
    (command: SlashPaletteCommand) => {
      if (command.command === "/stop" && isStreaming && onStop) {
        handleStop();
        setValue("");
        setSlashMenuDismissed(true);
        setCliAppMenuDismissed(false);
        setInlineError(null);
        resizeTextarea();
        return;
      }

      const nextRecents = [
        command.command,
        ...recentSlashCommands.filter((item) => item !== command.command),
      ].slice(0, SLASH_RECENTS_LIMIT);
      setRecentSlashCommands(nextRecents);
      storeSlashRecents(nextRecents);

      if (skillQuery !== null) {
        const suffix = value.slice(skillQuery.end);
        const inserted = `${command.command}${suffix.startsWith(" ") ? "" : " "}`;
        const next = `${value.slice(0, skillQuery.start)}${inserted}${suffix}`;
        const nextCursor = skillQuery.start + inserted.length;
        replaceMentionInput(next, nextCursor);
      } else {
        setValue(command.argHint ? `${command.command} ` : command.command);
      }
      setSlashMenuDismissed(true);
      setCliAppMenuDismissed(false);
      setInlineError(null);
      resizeTextarea();
    },
    [handleStop, isStreaming, onStop, recentSlashCommands, replaceMentionInput, resizeTextarea, skillQuery, value],
  );

  const insertMentionCandidate = useCallback(
    (candidate: MentionCandidate, start: number, end: number) => {
      if (candidate.kind === "session") {
        const alreadySelected = activeSessionMentions.some(
          (mention) => mention.session_key === candidate.mention.session_key,
        );
        if (!alreadySelected && activeSessionMentions.length >= SESSION_MENTIONS_LIMIT) return;
        const name = candidate.name.toLowerCase();
        setSelectedSessionMentions([
          ...activeSessionMentions.filter((mention) => (
            mention.name.toLowerCase() !== name
            && mention.session_key !== candidate.mention.session_key
          )),
          candidate.mention,
        ]);
      }
      const insertion = mentionInsertion(value, candidate.name, start, end);
      replaceMentionInput(insertion.value, insertion.cursor);
      setCliAppMenuDismissed(true);
      setSlashMenuDismissed(false);
      setInlineError(null);
      resizeTextarea();
    },
    [activeSessionMentions, replaceMentionInput, resizeTextarea, value],
  );

  const chooseMentionCandidate = useCallback(
    (candidate: MentionCandidate) => {
      if (!cliAppMention) return;
      insertMentionCandidate(candidate, cliAppMention.start, cliAppMention.end);
    },
    [cliAppMention, insertMentionCandidate],
  );

  const handleSessionDrop = useCallback((event: React.DragEvent) => {
    if (!hasDraggedSession(event.dataTransfer)) return false;
    event.preventDefault();
    clearDraggedSession();
    const preview = sessionDragPreview;
    setSessionDragPreview(null);
    if (interactionDisabled) return true;
    const sessionKey = readDraggedSession(event.dataTransfer);
    const mention = availableSessionMentions.find(
      (candidate) => candidate.session_key === (sessionKey ?? preview?.mention.session_key),
    );
    if (!mention) return true;
    const caret = preview?.start ?? rawSelection().start;
    insertMentionCandidate(
      {
        kind: "session",
        name: mention.name,
        displayName: mention.title || mention.name,
        mention,
      },
      caret,
      preview?.end ?? rawSelection().end,
    );
    return true;
  }, [
    availableSessionMentions,
    insertMentionCandidate,
    interactionDisabled,
    rawSelection,
    sessionDragPreview,
    value.length,
  ]);

  const previewSessionDrop = useCallback((event: React.DragEvent) => {
    if (!hasDraggedSession(event.dataTransfer)) return false;
    if (interactionDisabled) {
      event.dataTransfer.dropEffect = "none";
      setSessionDragPreview(null);
      return true;
    }
    const sessionKey = readDraggedSession(event.dataTransfer);
    const mention = availableSessionMentions.find(
      (candidate) => candidate.session_key === sessionKey,
    );
    const alreadySelected = mention && activeSessionMentions.some(
      (candidate) => candidate.session_key === mention.session_key,
    );
    if (!mention || (!alreadySelected && activeSessionMentions.length >= SESSION_MENTIONS_LIMIT)) {
      event.dataTransfer.dropEffect = "none";
      setSessionDragPreview(null);
      return true;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    const { start, end } = rawSelection();
    setSessionDragPreview((current) => (
      current?.mention.session_key === mention.session_key
      && current.start === start
      && current.end === end
        ? current
        : { mention, start, end }
    ));
    return true;
  }, [activeSessionMentions, availableSessionMentions, interactionDisabled, rawSelection]);

  useEffect(() => {
    if (!sessionDragPreview) return;
    const clearPreview = () => {
      clearDraggedSession();
      setSessionDragPreview(null);
    };
    document.addEventListener("dragend", clearPreview);
    return () => document.removeEventListener("dragend", clearPreview);
  }, [sessionDragPreview]);

  const clearComposerText = useCallback((restoreFocus = true) => {
    setValue("");
    setSelectedSessionMentions([]);
    setInlineError(null);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setCursorPosition(0);
    resizeTextarea(restoreFocus);
  }, [resizeTextarea]);

  const queuedPromptError = useCallback((prompt: QueuedPrompt): string | null => {
    if (utf8Bytes(formatQuotedUserMessage(prompt.text, prompt.quotedContext)) > maxTextBytes) {
      return textTooLargeMessage();
    }
    const attachments = prompt.images ?? [];
    if (attachments.length > maxAttachments) return formatRejection("too_many_attachments");
    const sizes = attachments.map(queuedAttachmentBytes);
    if (sizes.some((size) => size > (ingressLimits?.attachments.max_file_bytes ?? MAX_ATTACHMENT_BYTES))) {
      return formatRejection("too_large");
    }
    if (sizes.reduce((sum, size) => sum + size, 0) > (ingressLimits?.attachments.max_total_bytes ?? MAX_TOTAL_ATTACHMENT_BYTES)) {
      return formatRejection("total_too_large");
    }
    if ((prompt.sessionMentions?.length ?? 0) > SESSION_MENTIONS_LIMIT) {
      return t("thread.composer.queued.tooManyMentions", { max: SESSION_MENTIONS_LIMIT });
    }
    return null;
  }, [formatRejection, ingressLimits, maxAttachments, maxTextBytes, t, textTooLargeMessage]);

  const collectGuidancePrompt = useCallback((): QueuedPrompt => {
    queuedPromptCounterRef.current += 1;
    const prompt: QueuedPrompt = {
      id: `queued-prompt-${Date.now()}-${queuedPromptCounterRef.current}`,
      text: value.trim(),
      images: readyImagesToQueuedImages(readyImages),
      ...(activeTurnId ? { autoAfterTurnId: activeTurnId } : {}),
      ...(normalizedQuotedContext ? { quotedContext: normalizedQuotedContext } : {}),
      sessionMentions: activeSessionMentions,
    };
    return queuedPrompt ? mergeQueuedPrompt(queuedPrompt, prompt) : prompt;
  }, [activeSessionMentions, activeTurnId, normalizedQuotedContext, queuedPrompt, readyImages, value]);

  const queueGuidancePrompt = useCallback(() => {
    if (!canQueueGuidance) return;
    const prompt = collectGuidancePrompt();
    const error = queuedPromptError(prompt);
    if (error) {
      setInlineError(error);
      return;
    }
    secondEnterPromptIdRef.current = prompt.id;
    setQueuedPrompt(prompt);
    clear();
    clearComposerText();
    onQuotedContextChange?.(null);
  }, [canQueueGuidance, clear, clearComposerText, collectGuidancePrompt, onQuotedContextChange, queuedPromptError, setQueuedPrompt]);

  const removeQueuedPrompt = useCallback(() => {
    secondEnterPromptIdRef.current = null;
    setQueuedPrompt(null);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [setQueuedPrompt]);

  const editQueuedPrompt = useCallback((pending: QueuedPrompt) => {
    const prompt = hasComposerContent || normalizedQuotedContext ? collectGuidancePrompt() : pending;
    secondEnterPromptIdRef.current = null;
    setQueuedPrompt(null);
    replaceMentionInput(prompt.text, prompt.text.length);
    setSelectedSessionMentions(prompt.sessionMentions ?? []);
    setInlineError(null);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    onQuotedContextChange?.(prompt.quotedContext ?? null);
    if (prompt.images?.length) {
      restoreReadyImages(prompt.images as RestoredReadyImage[]);
    } else {
      clear();
    }
    resizeTextarea();
  }, [clear, collectGuidancePrompt, hasComposerContent, normalizedQuotedContext, onQuotedContextChange, replaceMentionInput, resizeTextarea, restoreReadyImages, setQueuedPrompt]);

  const sendQueuedPrompt = useCallback(
    (prompt: QueuedPrompt, extraOptions?: SendOptions) => {
      if (interactionDisabled) return;
      secondEnterPromptIdRef.current = null;
      const error = queuedPromptError(prompt);
      if (error) {
        setQueuedPrompt(pauseQueuedPrompt(prompt));
        setInlineError(error);
        return;
      }
      const text = prompt.text.trim();
      const queuedImages = queuedImagesToSendImages(prompt.images);
      const options: SendOptions | undefined = (
        extraOptions || prompt.quotedContext || prompt.sessionMentions?.length || isStreaming
      )
        ? {
            ...extraOptions,
            ...(prompt.quotedContext ? { quotedContext: prompt.quotedContext } : {}),
            ...(prompt.sessionMentions?.length ? { sessionMentions: prompt.sessionMentions } : {}),
            ...(isStreaming ? { continueActiveTurn: true } : {}),
          }
        : undefined;
      queuedPromptStore.send(prompt, () => (
        options ? onSend(text, queuedImages, options)
          : queuedImages?.length ? onSend(text, queuedImages)
          : onSend(text)
      ));
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
    [interactionDisabled, isStreaming, onSend, queuedPromptStore, queuedPromptError, setQueuedPrompt],
  );

  useEffect(() => {
    const previous = previousQueueRunRef.current;
    previousQueueRunRef.current = { key: pendingQueueKey, isStreaming };
    if (!isStreaming) secondEnterPromptIdRef.current = null;
    // Switching to an idle session is not completion of the previous session's run.
    if (previous.key !== pendingQueueKey) return;
    if (isStreaming || interactionDisabled || !queuedPrompt || queuedPrompt.autoPaused) return;
    const waitingTurnCompleted = queuedPromptStorageKey !== null && queuedPrompt.autoAfterTurnId !== undefined
      ? completedTurnIds.includes(queuedPrompt.autoAfterTurnId)
      : previous.isStreaming;
    if (!waitingTurnCompleted) return;
    sendQueuedPrompt(queuedPrompt);
  }, [completedTurnIds, interactionDisabled, sendQueuedPrompt, isStreaming, pendingQueueKey, queuedPrompt, queuedPromptStorageKey]);

  const submit = useCallback(() => {
    if (modelNeedsSetup) {
      if (hasComposerContent) {
        setModelSetupAttentionRequest((request) => request + 1);
      }
      return;
    }
    if (!canSend) return;
    const trimmed = value.trim();
    const content = trimmed;
    if (utf8Bytes(formatQuotedUserMessage(content, normalizedQuotedContext)) > maxTextBytes) {
      setInlineError(textTooLargeMessage());
      return;
    }
    // Keep self-contained local previews across drafts and optimistic bubbles.
    // The client decodes these to HTTP binary; WS messages contain only refs.
    const payload: SendAttachment[] | undefined =
      readyImages.length > 0
        ? readyImages.map((img) => ({
            media: {
              data_url: img.dataUrl,
              name: img.file.name,
            },
            preview: { kind: img.kind, url: img.dataUrl, name: img.file.name },
          }))
        : undefined;
    const attachedCliApps = activeCliMentionApps.map(cliAppMentionPayload);
    const attachedMcpPresets = activeMcpPresetMentions.map(mcpPresetMentionPayload);
    const options: SendOptions | undefined =
      attachedCliApps.length > 0
      || attachedMcpPresets.length > 0
      || activeSessionMentions.length > 0
      || normalizedQuotedContext
        ? {
            ...(attachedCliApps.length > 0 ? { cliApps: attachedCliApps } : {}),
            ...(attachedMcpPresets.length > 0 ? { mcpPresets: attachedMcpPresets } : {}),
            ...(activeSessionMentions.length > 0
              ? { sessionMentions: activeSessionMentions }
              : {}),
            ...(normalizedQuotedContext ? { quotedContext: normalizedQuotedContext } : {}),
          }
        : undefined;
    const hasPlainTextCommandPayload =
      payload === undefined
      && attachedCliApps.length === 0
      && attachedMcpPresets.length === 0
      && activeSessionMentions.length === 0;
    const slashLifecycle = hasPlainTextCommandPayload
      ? slashCommandLifecycle(content, slashCommands)
      : null;
    if (
      slashLifecycle === "stop_active_turn"
      && isStreaming
      && onStop
    ) {
      handleStop();
      clear();
      clearComposerText();
      onQuotedContextChange?.(null);
      return;
    }
    const isSlashSideChannel = isSideChannelLifecycle(slashLifecycle);
    const finalizeActiveTurn =
      slashLifecycle === "finalize_active_turn";
    if (!slashLifecycle) {
      const prompt = collectGuidancePrompt();
      const error = queuedPromptError(prompt);
      if (error) {
        setInlineError(error);
        return;
      }
      if (queuedPrompt) {
        sendQueuedPrompt(prompt, options);
        if (draftKey) draftStore?.delete(draftKey);
        clear();
        clearComposerText(!hasTouchPrimaryPointer);
        onQuotedContextChange?.(null);
        return;
      }
    }
    const submittedDraft = draftKey ? draftStore?.get(draftKey) : undefined;
    const finishSend = () => {
      // A pending send can finish after this composer unmounts and a newer draft is started.
      if (draftKey && draftStore && draftStore.get(draftKey) !== submittedDraft) return;
      if (draftKey) draftStore?.delete(draftKey);
      if (hasTouchPrimaryPointer) textareaRef.current?.blur();
      if (!isStreaming || finalizeActiveTurn) setQueuedPrompt(null);
      // Bubble owns the data URL copy; safe to revoke every staged blob
      // preview here without affecting the rendered message.
      clear();
      clearComposerText(!hasTouchPrimaryPointer);
      onQuotedContextChange?.(null);
    };
    const result = onSend(
      content,
      payload,
      isSlashSideChannel
        ? {
            ...options,
            sideChannel: true,
            ...(finalizeActiveTurn ? { finalizeActiveTurn } : {}),
          }
        : isStreaming ? { ...options, continueActiveTurn: true } : options,
    );
    if (result instanceof Promise) {
      setSendPending(true);
      void result
        .then((accepted) => {
          if (accepted !== false) finishSend();
        })
        .catch((error: unknown) => {
          setInlineError(error instanceof Error ? error.message : "Failed to send message");
        })
        .finally(() => setSendPending(false));
      return;
    }
    if (result !== false) finishSend();
  }, [
    activeCliMentionApps,
    activeMcpPresetMentions,
    activeSessionMentions,
    canSend,
    draftKey,
    draftStore,
    clear,
    clearComposerText,
    collectGuidancePrompt,
    queuedPrompt,
    queuedPromptError,
    sendQueuedPrompt,
    setQueuedPrompt,
    hasTouchPrimaryPointer,
    hasComposerContent,
    handleStop,
    isStreaming,
    maxTextBytes,
    modelNeedsSetup,
    onSend,
    onStop,
    onQuotedContextChange,
    normalizedQuotedContext,
    readyImages,
    slashCommands,
    textTooLargeMessage,
    value,
  ]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    mentionInput.onKeyDown(e);
    if (e.defaultPrevented || e.nativeEvent.isComposing || mentionInput.isComposing) return;
    if (showCliAppMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCliAppIndex((idx) => (idx + 1) % filteredMentionCandidates.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedCliAppIndex(
          (idx) => (idx - 1 + filteredMentionCandidates.length) % filteredMentionCandidates.length,
        );
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        chooseMentionCandidate(filteredMentionCandidates[selectedCliAppIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setCliAppMenuDismissed(true);
        return;
      }
    }
    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCommandIndex((idx) => (idx + 1) % filteredSlashCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedCommandIndex(
          (idx) => (idx - 1 + filteredSlashCommands.length) % filteredSlashCommands.length,
        );
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        chooseSlashCommand(filteredSlashCommands[selectedCommandIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashMenuDismissed(true);
        return;
      }
    }
    // Touch keyboards: a plain Enter inserts a newline; sending stays on the
    // send button. The select-on-Enter menu branches above take precedence.
    if (
      e.key === "Enter"
      && !e.shiftKey
      && !e.altKey
      && !e.ctrlKey
      && !e.metaKey
      && !e.nativeEvent.isComposing
      && hasCoarsePointer
    ) {
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canQueueGuidance) {
        if (!e.repeat) queueGuidancePrompt();
        return;
      }
      const secondEnterPrompt = queuedPrompt?.id === secondEnterPromptIdRef.current ? queuedPrompt : null;
      if (
        isStreaming
        && value.length === 0
        && images.length === 0
        && !e.altKey
        && !e.ctrlKey
        && !e.metaKey
        && secondEnterPrompt
      ) {
        if (!e.repeat) sendQueuedPrompt(secondEnterPrompt);
        return;
      }
      secondEnterPromptIdRef.current = null;
      submit();
    }
  };

  const onInput: React.FormEventHandler<HTMLTextAreaElement> = (e) => {
    if ((e.nativeEvent as InputEvent).isComposing) return;
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  };

  const onFilePick: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    addFiles(files);
  };

  const removeChip = useCallback(
    (id: string) => {
      const { nextFocusId } = remove(id);
      setInlineError(null);
      requestAnimationFrame(() => {
        const el = nextFocusId ? chipRefs.current.get(nextFocusId) : null;
        if (el) {
          el.focus();
        } else {
          textareaRef.current?.focus();
        }
      });
    },
    [remove],
  );

  const onChipKey = useCallback(
    (id: string) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
      if (
        e.key === "Delete" ||
        e.key === "Backspace" ||
        e.key === "Enter" ||
        e.key === " "
      ) {
        e.preventDefault();
        removeChip(id);
      }
    },
    [removeChip],
  );

  const attachButtonDisabled = interactionDisabled || full;
  const showVoiceButton = Boolean(onTranscribeAudio) && (
    voiceRecorder.state !== "idle"
    || (!hasComposerContent && images.length === 0 && !isStreaming && !modelNeedsSetup)
  );
  const voiceRecordingStatusLabel = t("thread.composer.voice.recordingStatus", {
    time: voiceRecorder.elapsedLabel,
    defaultValue: `Recording ${voiceRecorder.elapsedLabel}`,
  });
  const voiceButtonLabel =
    voiceRecorder.state === "recording"
      ? t("thread.composer.voice.stop")
      : voiceRecorder.state === "transcribing"
        ? t("thread.composer.voice.transcribing")
        : t("thread.composer.tools.voice");
  const voiceButtonTooltip =
    voiceRecorder.state === "recording"
      ? t("thread.composer.voice.stop")
      : voiceRecorder.state === "transcribing"
        ? t("thread.composer.voice.transcribing")
        : t("thread.composer.voice.hint");
  // Touch users need an explicit send action; keep Stop while sending is unavailable.
  const showStopButton = isStreaming && !!onStop && !canSend;
  const relaxedHeroInput = isHero && images.length === 0 && !isStreaming;
  const compactIdle = compactWhenIdle && !compactControls && !isHero && !composerFocused
    && value.length === 0 && images.length === 0 && !inlineError
    && !normalizedQuotedContext && !queuedPrompt && !goalState?.active
    && !isDragging && !sessionDragPreview && !voiceRecorder.isRecording && !showProjectPicker;
  useLayoutEffect(() => {
    if (!compactWhenIdle || compactControls) return;
    const form = formRef.current;
    const primary = form?.querySelector<HTMLElement>(".thread-composer-footer-primary");
    const actions = form?.querySelector<HTMLElement>(".thread-composer-footer-actions");
    if (!form || !primary || !actions) return;
    const controls = Array.from(primary.children).filter((child) => getComputedStyle(child).display !== "none");
    // Reserve the real toolbar width, including translated model labels, while
    // the footer slides beneath the input. Neither control is remounted.
    const measure = () => {
      const gap = parseFloat(getComputedStyle(primary).columnGap) || 0;
      const width = controls.reduce((sum, child) => sum + child.getBoundingClientRect().width, 0)
        + Math.max(0, controls.length - 1) * gap + actions.getBoundingClientRect().width;
      form.style.setProperty("--composer-compact-controls-width", `${width}px`);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    controls.forEach((control) => observer?.observe(control));
    observer?.observe(actions);
    return () => observer?.disconnect();
  }, [compactControls, compactWhenIdle, modelLabel, voiceRecorder.isRecording, workspaceScope]);
  const accessControl = workspaceScope && !workspaceControlsHidden ? (
    <WorkspaceAccessToggle
      scope={workspaceScope}
      disabled={interactionDisabled || workspaceScopeDisabled}
      isHero={isHero}
      onChange={onWorkspaceScopeChange}
    />
  ) : null;
  const workspaceControl = showProjectPicker ? (
    <WorkspaceProjectPicker
      layoutAnchor={workspacePickerLayoutAnchor}
      isHero={isHero}
      disabled={interactionDisabled || workspaceScopeDisabled}
      scope={workspaceScope}
      defaultScope={workspaceDefaultScope}
      controls={workspaceControls}
      error={workspaceError}
      onFavoriteProject={onFavoriteWorkspaceProject}
      onResolveProject={onResolveWorkspaceProject}
      onLoadProjects={onLoadWorkspaceProjects}
      onBrowseDirectories={onBrowseWorkspaceDirectories}
      onChange={onWorkspaceScopeChange}
    />
  ) : null;
  const modelControl = modelLabel && !voiceRecorder.isRecording ? (
    <ModelPresetBadge
      label={modelLabel}
      modelDetail={modelDetail}
      modelPreset={modelPreset}
      modelPresets={modelPresets}
      onPresetChange={onModelPresetChange}
      onManageModels={onManageModels}
      onRequestComposerFocus={() => textareaRef.current?.focus()}
      provider={modelProvider}
      providerLabel={modelProviderLabel}
      needsSetup={modelNeedsSetup}
      attentionRequest={modelSetupAttentionRequest}
      isHero={isHero && !compactControls}
      onClick={modelNeedsSetup ? onModelBadgeClick : undefined}
    />
  ) : null;
  const usageControl = !voiceRecorder.isRecording ? (
    <ComposerUsagePopover context={contextUsage} rounds={recentRoundUsage} showLabel={compactControls} bottomSheet={compactControls} />
  ) : null;
  const inputTextClasses = cn(
    // Keep the overlay's CJK/Latin spacing aligned with the native textarea caret.
    "w-full resize-none bg-transparent [text-autospace:no-autospace]",
    compactControls
      ? "min-h-[52px] px-4 pb-2 pt-3 text-[16px] leading-6"
      : isHero
        ? cn(
            "min-h-[78px] px-4 text-[16px] leading-6 sm:px-5",
            relaxedHeroInput ? "pb-2 pt-[27px]" : "pb-1.5 pt-4",
          )
        : "min-h-[50px] px-3.5 pb-1.5 pt-3 text-[16px] leading-5 sm:px-4",
  );
  const paletteBeside = showAnyPalette && slashPaletteLayout.placement === "beside";

  return (
    <form
      ref={formRef}
      data-compact-controls={compactControls ? "true" : undefined}
      data-palette-beside={paletteBeside || undefined}
      onFocusCapture={() => {
        if (!compactWhenIdle) return;
        // Portaled model controls belong to this composer too: keep its layout
        // stable while moving between the input, toolbar, and model picker.
        if (blurFrame.current !== null) cancelAnimationFrame(blurFrame.current);
      }}
      onBlurCapture={() => {
        if (!compactWhenIdle) return;
        if (blurFrame.current !== null) cancelAnimationFrame(blurFrame.current);
        blurFrame.current = requestAnimationFrame(() => {
          blurFrame.current = null;
          setComposerFocused(false);
        });
      }}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragEnter={(event) => {
        if (!previewSessionDrop(event)) onDragEnter(event);
      }}
      onDragOver={(event) => {
        if (!previewSessionDrop(event)) onDragOver(event);
      }}
      onDragLeave={(event) => {
        if (!hasDraggedSession(event.dataTransfer)) {
          onDragLeave(event);
          return;
        }
        const nextTarget = event.relatedTarget;
        if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
          setSessionDragPreview(null);
        }
      }}
      onDrop={(event) => {
        if (!handleSessionDrop(event)) onDrop(event);
      }}
      className={cn(
        "relative w-full",
        isHero ? "px-0" : "px-1 pb-1.5 pt-1 sm:px-0",
        compactWhenIdle && "thread-composer-collapsible-layout",
        paletteBeside && "grid grid-cols-2 items-start gap-2 p-0",
      )}
    >
      {showSlashMenu ? (
        <SlashCommandPalette
          commands={filteredSlashCommands}
          selectedIndex={selectedCommandIndex}
          layout={slashPaletteLayout}
          isHero={isHero}
          onHover={setSelectedCommandIndex}
          onChoose={chooseSlashCommand}
        />
      ) : null}
      {showCliAppMenu ? (
        <CliAppMentionPalette
          candidates={filteredMentionCandidates}
          selectedIndex={selectedCliAppIndex}
          layout={slashPaletteLayout}
          isHero={isHero}
          onHover={setSelectedCliAppIndex}
          onChoose={chooseMentionCandidate}
        />
      ) : null}
      <div
        ref={surfaceRef}
        data-compact={compactIdle || undefined}
        style={paletteBeside ? { maxHeight: slashPaletteLayout.maxHeight, overflowY: "auto" } : undefined}
        className={cn(
          "thread-composer-surface group/composer relative mx-auto flex w-full flex-col overflow-visible transition-all duration-200",
          paletteBeside && "col-start-1 row-start-1",
          isHero
            ? "max-w-[58rem] rounded-prominent bg-muted/80 focus-within:bg-muted dark:bg-card dark:focus-within:bg-white/[0.06]"
            : "max-w-[49.5rem] rounded-panel bg-muted/80 focus-within:bg-muted dark:bg-card dark:focus-within:bg-white/[0.06]",
          compactWhenIdle && "thread-composer-collapsible transition-colors motion-reduce:transition-none",
          interactionDisabled && "opacity-60",
          sessionDragPreview && "ring-1 ring-primary/25",
          isDragging && "ring-2 ring-primary/40 motion-reduce:ring-0 motion-reduce:border-primary",
          goalState?.active &&
            "goal-shell-glow ring-1 ring-sky-400/35 motion-reduce:ring-sky-400/25 dark:ring-sky-400/45",
        )}
      >
        {queuedPrompt ? (
          <QueuedPromptPreview
            prompt={queuedPrompt}
            disabled={interactionDisabled}
            editDisabled={encoding || hasErrors}
            label={t("thread.composer.queued.label")}
            guideLabel={t("thread.composer.queued.guide")}
            deleteLabel={t("thread.composer.queued.delete")}
            editLabel={t("thread.composer.queued.edit")}
            onGuide={() => sendQueuedPrompt(queuedPrompt)}
            onDelete={removeQueuedPrompt}
            onEdit={() => editQueuedPrompt(queuedPrompt)}
          />
        ) : null}
        {images.length > 0 ? (
          <div
            className="flex flex-wrap gap-2 px-3 pt-3"
            aria-label={t("thread.composer.attachImage")}
          >
            {images.map((img) => (
              <AttachmentChip
                key={img.id}
                image={img}
                labelRemove={t("thread.composer.remove")}
                labelEncoding={t("thread.composer.encoding")}
                normalizedHint={(orig, current) =>
                  t("thread.composer.normalizedSizeHint", {
                    orig: formatBytes(orig),
                    current: formatBytes(current),
                  })
                }
                formatError={formatRejection}
                onRemove={() => removeChip(img.id)}
                onKeyDown={onChipKey(img.id)}
                registerRef={(el) => {
                  if (el) chipRefs.current.set(img.id, el);
                  else chipRefs.current.delete(img.id);
                }}
              />
            ))}
          </div>
        ) : null}
        {normalizedQuotedContext ? (
          <div
            className="mx-3 mt-3 flex min-w-0 items-start gap-2 border-l-2 border-muted-foreground/25 pl-3 pr-1 text-muted-foreground"
            aria-label={t("thread.composer.quotedContext")}
          >
            <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <p className="line-clamp-2 min-w-0 flex-1 text-[13px]/[1.45]">
              {normalizedQuotedContext}
            </p>
            <button
              type="button"
              className="touch-target -mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("thread.composer.removeQuotedContext")}
              onClick={() => {
                onQuotedContextChange?.(null);
                requestAnimationFrame(() => textareaRef.current?.focus());
              }}
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ) : null}
        <GoalStateStrip goalState={goalState} />
        <div className="thread-composer-input relative min-w-0">
          {hasMentionDecorations ? (
            <ComposerCliMentionOverlay
              overlayRef={mentionOverlayRef}
              segments={displayMentionSegments}
              isHero={isHero}
              isComposing={mentionInput.isComposing}
              className={inputTextClasses}
              ghostRange={sessionDragInsertion
                ? { start: sessionDragInsertion.tokenStart, end: sessionDragInsertion.tokenEnd }
                : null}
            />
          ) : null}
          <textarea
            ref={textareaRef}
            value={mentionInput.value}
            onFocus={() => {
              if (compactWhenIdle) setComposerFocused(true);
            }}
            onChange={mentionInput.onChange}
            onCompositionStart={mentionInput.onCompositionStart}
            onCompositionEnd={mentionInput.onCompositionEnd}
            onBlur={() => {
              secondEnterPromptIdRef.current = null;
            }}
            onInput={onInput}
            onKeyDown={onKeyDown}
            onKeyUp={() => setCursorPosition(rawSelection().start)}
            onSelect={() => setCursorPosition(rawSelection().start)}
            onClick={() => setCursorPosition(rawSelection().start)}
            onCopy={mentionInput.onCopy}
            onCut={mentionInput.onCut}
            onScroll={(e) => {
              if (mentionOverlayRef.current) mentionOverlayRef.current.scrollTop = e.currentTarget.scrollTop;
            }}
            onPaste={onPaste}
            rows={1}
            enterKeyHint={hasCoarsePointer ? "enter" : undefined}
            placeholder={sessionDragPreview ? "" : resolvedPlaceholder}
            disabled={interactionDisabled}
            aria-label={inputAriaLabel ?? t("thread.composer.inputAria")}
            className={cn(
              inputTextClasses,
              "relative z-10 block caret-foreground placeholder:text-muted-foreground",
              "focus:outline-none focus-visible:outline-none",
              "disabled:cursor-not-allowed",
              hasMentionDecorations && "text-transparent selection:bg-primary/20",
            )}
          />
        </div>
        {inlineError ? (
          <div
            role="alert"
            className={cn(
              "mx-3 mb-1 max-h-24 overflow-hidden rounded-md border border-destructive/40 bg-destructive/8 px-2.5 py-1",
              "text-[11.5px] font-medium text-destructive transition-[max-height,margin,padding,opacity] [transition-duration:220ms] ease-out motion-reduce:transition-none",
              voiceErrorFading && "mb-0 max-h-0 border-transparent py-0 opacity-0",
            )}
          >
            {inlineError}
          </div>
        ) : null}
        <div
          className={cn(
            "thread-composer-footer flex flex-nowrap items-center motion-safe:transition-[padding-bottom] motion-safe:[transition-duration:220ms] motion-safe:ease-in-out",
            isHero
              ? cn(
                  "gap-x-1.5 px-3 sm:px-4",
                  showProjectPicker && compactControls ? "pb-1.5" : "pb-3.5",
                )
              : "gap-x-2 px-2.5 pb-2 sm:px-3",
          )}
        >
          <div
            className={cn(
              "thread-composer-footer-primary flex min-w-0 flex-1 basis-0 items-center",
              isHero ? "gap-1.5" : "gap-2",
            )}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_ATTR}
              multiple
              hidden
              onChange={onFilePick}
            />
            <Button
              type="button"
              size="icon"
              variant="icon"
              disabled={attachButtonDisabled}
              aria-label={t("thread.composer.attachImage")}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "thread-composer-action thread-composer-round-action touch-target shrink-0 rounded-xl text-muted-foreground hover:text-foreground",
                isHero
                  ? "h-8 w-8"
                  : "h-9 w-9",
              )}
            >
              <AttachIcon className="h-3.5 w-3.5" />
            </Button>
            {voiceRecorder.isRecording ? (
              <VoiceRecordingMeter
                ariaLabel={voiceRecordingStatusLabel}
                className="mx-1 flex-1"
                elapsedLabel={voiceRecorder.elapsedLabel}
                isHero={isHero}
                levels={voiceRecorder.levels}
              />
            ) : compactControls ? modelControl : (
              <div className="thread-composer-workspace-group flex min-w-0 items-center gap-0.5">
                {workspaceControl}
                {accessControl}
              </div>
            )}
          </div>
          <div
            className={cn(
              "thread-composer-footer-actions ml-auto flex min-w-0 items-center justify-end",
              isHero ? "gap-1.5" : "gap-2",
            )}
          >
            {!compactControls ? modelControl : null}
            {!compactControls ? usageControl : null}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type={showVoiceButton || showStopButton || modelNeedsSetup ? "button" : "submit"}
                    size="icon"
                    disabled={showVoiceButton ? voiceRecorder.buttonDisabled : showStopButton ? interactionDisabled : !canSend && !canOpenModelSettings}
                    aria-label={
                      showVoiceButton
                        ? voiceButtonLabel
                        : showStopButton
                          ? t("thread.composer.stop")
                          : modelNeedsSetup
                            ? t("thread.composer.configureModel", { defaultValue: "Configure model" })
                            : t("thread.composer.send")
                    }
                    aria-keyshortcuts={showVoiceButton ? VOICE_SHORTCUT_ARIA : undefined}
                    onPointerDown={showVoiceButton ? voiceRecorder.beginPress : undefined}
                    onPointerUp={showVoiceButton ? voiceRecorder.endPress : undefined}
                    onPointerCancel={showVoiceButton ? voiceRecorder.endPress : undefined}
                    onClickCapture={event => {
                      if (!voiceRecorder.consumeSuppressedClick()) return;
                      event.preventDefault();
                      event.stopPropagation();
                    }}
                    onClick={showVoiceButton ? voiceRecorder.handleClick : showStopButton ? handleStop : modelNeedsSetup ? onModelBadgeClick : undefined}
                    className={cn(
                      "thread-composer-action thread-composer-round-action touch-target rounded-full",
                      showStopButton && !showVoiceButton
                        ? "border border-border/70 bg-card text-foreground/85 hover:text-foreground disabled:text-muted-foreground/50"
                        : "border border-foreground bg-foreground text-background disabled:border-foreground disabled:bg-foreground disabled:text-background",
                      showVoiceButton && voiceRecorder.isRecording && "border-red-500 bg-red-500 text-white hover:bg-red-500 hover:text-white",
                      isHero ? "h-8 w-8" : "h-9 w-9",
                    )}
                  >
                    {showVoiceButton ? (
                      voiceRecorder.state === "transcribing" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : voiceRecorder.isRecording ? (
                        <StopIcon className="h-3.5 w-3.5" fill="currentColor" />
                      ) : (
                        <VoiceIcon className="h-4 w-4" />
                      )
                    ) : showStopButton ? (
                      <StopIcon className={cn("fill-current stroke-current", isHero ? "h-3 w-3" : "h-3.5 w-3.5")} />
                    ) : modelNeedsSetup ? (
                      <ModelsIcon className="h-4 w-4" />
                    ) : canSend || !isStreaming ? (
                      <ArrowUp className="h-4 w-4" />
                    ) : (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    )}
                  </Button>
                </TooltipTrigger>
                {showVoiceButton ? (
                  <TooltipContent
                    side="top"
                    align="center"
                    className="flex items-center gap-2 rounded-full border border-border/70 bg-popover px-3 py-1.5 text-[13px] font-medium text-popover-foreground shadow-[0_8px_24px_rgba(15,23,42,0.13)] dark:border-white/10"
                  >
                    <span>{voiceButtonTooltip}</span>
                    {voiceRecorder.state === "idle" ? (
                      <kbd className="rounded-full bg-muted px-2 py-0.5 font-sans text-[12px] font-semibold leading-none text-muted-foreground dark:bg-white/10">
                        {voiceShortcutLabel}
                      </kbd>
                    ) : null}
                  </TooltipContent>
                ) : null}
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
        {compactControls && projectPickerAvailable ? (
          <div
            className="inline-disclosure"
            data-composer-workspace-drawer=""
            data-state={showProjectPicker ? "open" : "closed"}
            aria-hidden={showProjectPicker ? undefined : true}
          >
            <div className="inline-disclosure-clip">
              <div className="inline-disclosure-content thread-composer-workspace-row flex min-w-0 items-center justify-between gap-2 rounded-b-[28px] bg-muted/45 px-3 py-1.5 dark:bg-white/[0.045] sm:px-4">
                {workspaceControl}
                <div className="ml-auto flex min-w-0 justify-end">{accessControl}</div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
      {compactControls && (!projectPickerAvailable || usageControl) ? (
        <div className="thread-composer-meta mx-auto flex w-full max-w-[58rem] items-center justify-between gap-2 px-3">
          {!projectPickerAvailable ? accessControl : null}
          <div className="ml-auto">{usageControl}</div>
        </div>
      ) : null}
    </form>
  );
}

function QueuedPromptPreview({
  prompt,
  disabled,
  editDisabled,
  label,
  guideLabel,
  deleteLabel,
  editLabel,
  onGuide,
  onDelete,
  onEdit,
}: {
  prompt: QueuedPrompt;
  disabled: boolean;
  editDisabled: boolean;
  label: string;
  guideLabel: string;
  deleteLabel: string;
  editLabel: string;
  onGuide: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  return (
    <div
      role="group"
      data-state="enter"
      className={cn(
        "composer-status-strip relative z-20 mx-3 mt-3 overflow-hidden rounded-floating",
        "border border-black/[0.05] bg-popover/90 p-1.5",
        "shadow-[0_10px_28px_rgba(15,23,42,0.07)] backdrop-blur-md",
        "dark:border-white/[0.08] dark:bg-popover/90 dark:shadow-[0_14px_34px_rgba(0,0,0,0.30)]",
      )}
      style={{ "--composer-strip-max-height": "224px" } as CSSProperties}
      aria-label={label}
    >
      <div className="flex min-w-0 items-center gap-1 px-1 pb-1">
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-semibold text-foreground/75">{label}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-7 shrink-0 rounded-full px-2 text-[11.5px] font-medium text-muted-foreground hover:bg-muted/70 hover:text-foreground dark:hover:bg-white/[0.07]"
          onClick={onGuide}
        >
          <CornerDownRight className="mr-1 h-3 w-3" aria-hidden />
          {guideLabel}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled || editDisabled}
          aria-label={editLabel}
          title={editLabel}
          className="h-7 w-7 shrink-0 rounded-full text-muted-foreground hover:text-foreground"
          onClick={onEdit}
        >
          <EditIcon className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          aria-label={deleteLabel}
          className="h-7 w-7 shrink-0 rounded-full text-muted-foreground hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="h-3 w-3" aria-hidden />
        </Button>
      </div>
      <div className="max-h-40 overflow-y-auto px-2 pb-1 text-[13px]">
        <p className="whitespace-pre-wrap break-words font-medium leading-relaxed text-foreground/88">
          {queuedPromptLabel(prompt)}
        </p>
        {prompt.text && prompt.images?.length ? (
          <p className="mt-1 break-words text-xs text-muted-foreground">
            {prompt.images.map((image) => image.name).filter(Boolean).join(", ")}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ComposerCliMentionOverlay({
  overlayRef,
  segments,
  isHero,
  isComposing,
  className,
  ghostRange,
}: {
  overlayRef: Ref<HTMLDivElement>;
  segments: CapabilityMentionSegment[];
  isHero: boolean;
  isComposing: boolean;
  className: string;
  ghostRange?: { start: number; end: number } | null;
}) {
  let offset = 0;
  const occurrences = new Map<string, number>();
  return (
    <div
      ref={overlayRef}
      aria-hidden
      className={cn(
        className,
        "pointer-events-none absolute inset-0 z-0 overflow-hidden whitespace-pre-wrap break-words text-foreground",
        // Native IME selection backgrounds can be opaque; keep the mirrored glyphs visible.
        isComposing && "z-20",
      )}
    >
      {segments.map((segment, index) => {
        const start = offset;
        offset += segment.text.length;
        if (segment.kind === "text") {
          return <span key={`text-${index}`}>{segment.text}</span>;
        }
        const isGhost = ghostRange?.start === start && ghostRange.end === offset;
        const identity = `${segment.kind}-${segment.kind === "cli"
          ? segment.app.name : segment.kind === "mcp" ? segment.preset.name : segment.mention.session_key}`;
        const occurrence = occurrences.get(identity) ?? 0;
        occurrences.set(identity, occurrence + 1);
        return (
          <span
            key={`${identity}-${occurrence}`}
            data-testid={isGhost ? "composer-session-drag-preview" : undefined}
            className={cn(isGhost && "opacity-45 transition-opacity duration-100")}
          >
            <CapabilityMentionToken
              segment={segment}
              variant="composer"
              isHero={isHero}
            />
          </span>
        );
      })}
      {segments.at(-1)?.text.endsWith("\n") ? "\u200b" : null}
    </div>
  );
}
interface SlashCommandPaletteProps {
  commands: SlashPaletteCommand[];
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (command: SlashPaletteCommand) => void;
}

interface CliAppMentionPaletteProps {
  candidates: MentionCandidate[];
  selectedIndex: number;
  layout: SlashPaletteLayout;
  isHero: boolean;
  onHover: (index: number) => void;
  onChoose: (candidate: MentionCandidate) => void;
}

function useSelectedOptionScroll(selectedIndex: number) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const option = container.querySelector<HTMLElement>(
      `[data-palette-index="${selectedIndex}"]`,
    );
    if (typeof option?.scrollIntoView === "function") {
      option.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  return containerRef;
}

function CliAppMentionPalette({
  candidates,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: CliAppMentionPaletteProps) {
  const { t } = useTranslation();
  const listMaxHeight = Math.max(
    0,
    layout.maxHeight - SLASH_PALETTE_CHROME_PX,
  );
  const listRef = useSelectedOptionScroll(selectedIndex);
  const groupedCandidates = (["session", "cli", "mcp"] as const)
    .map((kind) => ({
      kind,
      label: kind === "session"
        ? t("thread.composer.mentions.sessionGroup")
        : kind === "cli"
          ? t("thread.composer.mentions.cliGroup")
          : t("thread.composer.mentions.mcpGroup"),
      items: candidates
        .map((candidate, index) => ({ candidate, index }))
        .filter(({ candidate }) => candidate.kind === kind),
    }))
    .filter((group) => group.items.length > 0);
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.mentions.ariaLabel")}
      style={{ maxHeight: layout.maxHeight }}
      className={cn(
        floatingSurfaceVisualClassName,
        "z-30 overflow-hidden",
        layout.placement === "beside"
          ? "relative col-start-2 row-start-1 w-full"
          : cn("absolute left-1/2 w-[calc(100%-0.5rem)] -translate-x-1/2",
            layout.placement === "above" ? "bottom-full mb-2" : "top-full mt-2"),
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div ref={listRef} className="overflow-y-auto" style={{ maxHeight: listMaxHeight }}>
        {groupedCandidates.map((group) => (
          <div key={group.kind} role="group" aria-label={group.label} className="mt-1.5 first:mt-0">
            <div className="px-2 pb-1 pt-1 text-[12px] font-medium text-muted-foreground/72">
              {group.label}
            </div>
            {group.items.map(({ candidate, index }) => {
              const selected = index === selectedIndex;
              const name = candidate.name;
              const typeLabel = candidate.kind === "cli"
                ? t("thread.composer.mentions.cliBadge")
                : candidate.kind === "mcp"
                  ? t("thread.composer.mentions.mcpBadge")
                  : t("thread.composer.mentions.sessionBadge");
              const ariaDescription = candidate.kind === "cli"
                ? t("thread.composer.mentions.cliDescription", { name })
                : candidate.kind === "mcp"
                  ? t("thread.composer.mentions.mcpDescription", { name })
                  : t("thread.composer.mentions.sessionDescription", { name });
              return (
                <button
                  key={`${candidate.kind}-${name}`}
                  type="button"
                  role="option"
                  data-palette-index={index}
                  aria-selected={selected}
                  aria-label={`${candidate.displayName} @${name} ${ariaDescription} ${typeLabel}`}
                  onMouseEnter={() => onHover(index)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onChoose(candidate);
                  }}
                  className={cn(
                    floatingItemClassName,
                    floatingItemFocusClassName,
                    "touch-target flex min-h-10 w-full items-center gap-2.5 px-2.5 py-1.5 text-left transition-colors",
                    selected
                      ? "bg-foreground/[0.055] text-foreground"
                      : "text-foreground/90 hover:bg-foreground/[0.04]",
                  )}
                >
                  <MentionCandidateLogo candidate={candidate} selected={selected} />
                  <span className="flex min-w-0 flex-1 items-baseline gap-2">
                    <span className="min-w-0 truncate text-[15px] font-medium tracking-normal text-foreground">
                      {candidate.displayName}
                    </span>
                    <span className="truncate text-[15px] font-normal tracking-normal text-muted-foreground/72">
                      @{name}
                    </span>
                  </span>
                  {candidate.kind !== "session" ? (
                    <span
                      className={cn(
                        "ml-2 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-normal",
                        candidate.kind === "cli"
                          ? "bg-orange-500/10 text-orange-600 dark:text-orange-300"
                          : "bg-sky-500/10 text-sky-600 dark:text-sky-300",
                      )}
                    >
                      {typeLabel}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function MentionCandidateLogo({
  candidate,
  selected,
}: {
  candidate: MentionCandidate;
  selected: boolean;
}) {
  const color = candidate.kind === "session"
    ? candidate.mention.id
      ? sessionHandleColor(candidate.mention.id)
      : INLINE_TOKEN_HIGHLIGHT_COLOR
    : candidate.brandColor || INLINE_TOKEN_HIGHLIGHT_COLOR;
  const rawLogoUrl = candidate.kind === "session" ? null : candidate.logoUrl;
  const logoUrls = useMemo(() => logoFallbackUrls(rawLogoUrl), [rawLogoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  if (candidate.kind === "session") {
    return (
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center"
        style={{ color }}
      >
        <ConversationIcon className="h-4 w-4" aria-hidden />
      </span>
    );
  }
  if (logoUrl) {
    return (
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-compact",
          selected ? "bg-background/55" : "bg-transparent",
        )}
      >
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-5 w-5 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }
  return (
    <span
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-compact text-[7.5px] font-semibold text-white"
      style={{ backgroundColor: color }}
    >
      {candidate.initials}
    </span>
  );
}

function SlashCommandPalette({
  commands,
  selectedIndex,
  layout,
  isHero,
  onHover,
  onChoose,
}: SlashCommandPaletteProps) {
  const { t } = useTranslation();
  const listMaxHeight = Math.max(
    0,
    layout.maxHeight - SLASH_PALETTE_CHROME_PX,
  );
  const listRef = useSelectedOptionScroll(selectedIndex);
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.slash.ariaLabel")}
      style={{ maxHeight: layout.maxHeight }}
      className={cn(
        floatingSurfaceVisualClassName,
        "z-30 overflow-hidden",
        layout.placement === "beside"
          ? "relative col-start-2 row-start-1 w-full"
          : cn("absolute left-1/2 w-[calc(100%-0.5rem)] -translate-x-1/2",
            layout.placement === "above" ? "bottom-full mb-2" : "top-full mt-2"),
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div ref={listRef} className="overflow-y-auto pr-0.5" style={{ maxHeight: listMaxHeight }}>
        {commands.map((command, index) => {
          const Icon = command.kind === "skill" ? SkillsIcon : BUILTIN_COMMAND_ICONS[command.command] ?? COMMAND_ICONS[command.icon] ?? HelpIcon;
          const selected = index === selectedIndex;
          const isSkill = command.kind === "skill";
          const commandKey = slashCommandI18nKey(command.command);
          const title = t(`thread.composer.slash.commands.${commandKey}.title`, {
            defaultValue: command.title,
          });
          const description = t(`thread.composer.slash.commands.${commandKey}.description`, {
            defaultValue: command.description,
          });
          return (
            <button
              key={command.command}
              type="button"
              role="option"
              data-palette-index={index}
              aria-selected={selected}
              onMouseEnter={() => onHover(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onChoose(command);
              }}
              className={cn(
                floatingItemClassName,
                floatingItemFocusClassName,
                "flex min-h-[44px] w-full items-center gap-3 px-3 py-2 text-left transition-colors",
                selected
                  ? "bg-foreground/[0.065] text-foreground dark:bg-white/[0.09]"
                  : "text-foreground/86 hover:bg-foreground/[0.045] dark:hover:bg-white/[0.065]",
              )}
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center text-muted-foreground transition-colors",
                  selected && "text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
                <span
                  className={cn(
                    "text-[13.5px] font-semibold tracking-normal text-foreground",
                    isSkill
                      ? "max-w-full shrink-0 break-all sm:max-w-[55%]"
                      : "min-w-0 truncate",
                  )}
                >
                  {title}
                </span>
                <span className="min-w-0 truncate text-[13px] text-muted-foreground">
                  {command.detail || description}
                </span>
              </span>
              {!isSkill || command.badge || command.recent ? (
                <span className="ml-2 flex max-w-[42%] shrink-0 items-center gap-1.5 sm:max-w-none">
                  {command.badge || command.recent ? (
                    <span className="hidden rounded-full bg-foreground/[0.055] px-2 py-1 text-[11px] font-medium text-muted-foreground sm:inline-flex">
                      {command.badge ?? t("thread.composer.slash.badges.recent")}
                    </span>
                  ) : null}
                  {!isSkill ? (
                    <span className="font-mono text-[12px] text-muted-foreground/60">
                      {command.argHint ? `${command.command} ${command.argHint}` : command.command}
                    </span>
                  ) : null}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface AttachmentChipProps {
  image: AttachedImage;
  labelRemove: string;
  labelEncoding: string;
  normalizedHint: (origBytes: number, currentBytes: number) => string;
  formatError: (reason: AttachmentError) => string;
  onRemove: () => void;
  onKeyDown: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
  registerRef: (el: HTMLButtonElement | null) => void;
}

function AttachmentChip({
  image,
  labelRemove,
  labelEncoding,
  normalizedHint,
  formatError,
  onRemove,
  onKeyDown,
  registerRef,
}: AttachmentChipProps) {
  const sizeLabel =
    image.status === "ready" && image.normalized && image.encodedBytes
      ? normalizedHint(image.file.size, image.encodedBytes)
      : formatBytes(image.file.size);
  const tone =
    image.status === "error"
      ? "border-destructive/40 bg-destructive/5 text-destructive"
      : "border-border/70 bg-muted/60";

  return (
    <div
      className={cn(
        "group relative flex items-center gap-2 rounded-control border px-2 py-1.5",
        "transition-colors motion-reduce:transition-none",
        tone,
      )}
      data-testid="composer-chip"
    >
      <div className="relative h-10 w-10 overflow-hidden rounded-md bg-background">
        {image.kind === "image" && image.previewUrl ? (
          <img
            src={image.previewUrl}
            alt=""
            aria-hidden
            loading="eager"
            draggable={false}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            {image.kind === "image" ? (
              <ImageIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
            ) : (
              <FileText className="h-4 w-4 text-muted-foreground" aria-hidden />
            )}
          </div>
        )}
        {image.status === "encoding" ? (
          <div
            className="absolute inset-0 flex items-center justify-center bg-background/60"
            aria-label={labelEncoding}
          >
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          </div>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-col text-[11.5px] leading-4">
        <span className="max-w-[min(14rem,calc(100vw-8rem))] truncate font-medium" title={image.file.name}>
          {image.file.name}
        </span>
        <span className="truncate text-muted-foreground">
          {image.status === "error" && image.error
            ? formatError(image.error)
            : sizeLabel}
        </span>
      </div>
      <button
        type="button"
        ref={registerRef}
        onClick={onRemove}
        onKeyDown={onKeyDown}
        aria-label={labelRemove}
        className={cn(
          "ml-1 grid h-5 w-5 flex-none place-items-center rounded-full",
          "text-muted-foreground/80 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
