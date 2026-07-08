import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import {
  CliAppMentionToken,
  McpPresetMentionToken,
  cliAppInitials,
  mcpPresetInitials,
  splitCapabilityMentionSegments,
  type CapabilityMentionSegment,
} from "@/components/CliAppMentionText";
import {
  Activity,
  ArrowUp,
  BookOpen,
  Brain,
  ChevronDown,
  ChevronUp,
  CircleHelp,
  CornerDownRight,
  GripVertical,
  History,
  ImageIcon,
  Loader2,
  Mic,
  Plus,
  RotateCw,
  Shield,
  Sparkles,
  Square,
  SquarePen,
  Target,
  Trash2,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  WorkspaceAccessMenu,
  WorkspaceProjectPicker,
} from "@/components/thread/WorkspaceControls";
import {
  useAttachedImages,
  type AttachedImage,
  type AttachmentError,
  MAX_IMAGES_PER_MESSAGE,
  type RestoredReadyImage,
} from "@/hooks/useAttachedImages";
import { useClipboardAndDrop } from "@/hooks/useClipboardAndDrop";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import type { SendImage, SendOptions } from "@/hooks/useNanobotStream";
import { useVoiceRecorder, type VoiceRecorderErrorKey } from "@/hooks/useVoiceRecorder";
import type {
  CliAppInfo,
  GoalStateWsPayload,
  McpPresetInfo,
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  SlashCommand,
  SkillSummary,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import {
  inferProviderFromModelName,
  logoFallbackUrls,
  providerBrand,
} from "@/lib/provider-brand";
import { cn } from "@/lib/utils";

/** ``<input accept>``: aligned with the server's MIME whitelist. SVG is
 * deliberately excluded to avoid an embedded-script XSS surface. */
const ACCEPT_ATTR = "image/png,image/jpeg,image/webp,image/gif";
const VOICE_SHORTCUT_CODE = "KeyD";
const VOICE_SHORTCUT_ARIA = "Control+Shift+D";
type VoiceShortcutPlatform = "apple" | "chromeos" | "linux" | "other" | "windows";
type ResolvedSlashCommandLifecycle =
  | "side_channel"
  | "finalize_active_turn"
  | "stop_active_turn"
  | "agent_turn";

function slashCommandName(content: string): string {
  return content.split(/\s+/, 1)[0];
}

function slashCommandArgs(content: string, commandName: string): string {
  return content.slice(commandName.length).trim();
}

function matchingSlashCommand(content: string, slashCommands: SlashCommand[]): SlashCommand | null {
  const commandName = slashCommandName(content);
  if (!commandName.startsWith("/")) return null;
  const command = slashCommands.find((item) => item.command === commandName);
  if (!command) return null;
  if (slashCommandArgs(content, command.command).length > 0 && !command.acceptsArgs) return null;
  return command;
}

function slashCommandLifecycle(
  content: string,
  slashCommands: SlashCommand[],
): ResolvedSlashCommandLifecycle | null {
  const command = matchingSlashCommand(content, slashCommands);
  if (!command) return null;
  if (command.lifecycle === "agent_turn_with_args") {
    return slashCommandArgs(content, command.command).length > 0
      ? "agent_turn"
      : "side_channel";
  }
  return command.lifecycle;
}

function isSideChannelLifecycle(lifecycle: ResolvedSlashCommandLifecycle | null): boolean {
  return (
    lifecycle === "side_channel"
    || lifecycle === "finalize_active_turn"
    || lifecycle === "stop_active_turn"
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
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
  onSend: (content: string, images?: SendImage[], options?: SendOptions) => void;
  disabled?: boolean;
  placeholder?: string;
  isStreaming?: boolean;
  modelLabel?: string | null;
  modelProvider?: string | null;
  modelProviderLabel?: string | null;
  modelNeedsSetup?: boolean;
  onModelBadgeClick?: () => void;
  variant?: "thread" | "hero";
  slashCommands?: SlashCommand[];
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  skills?: SkillSummary[];
  onStop?: () => void;
  onTranscribeAudio?: (dataUrl: string, options?: { durationMs?: number }) => Promise<string>;
  /** Unix seconds from server; turn elapsed timer above input while set. */
  runStartedAt?: number | null;
  /** Sustained objective for this chat (WebSocket ``goal_state``). */
  goalState?: GoalStateWsPayload;
  workspaceScope?: WorkspaceScopePayload | null;
  workspaceDefaultScope?: WorkspaceScopePayload | null;
  workspaceControls?: WorkspacesPayload["controls"] | null;
  workspaceScopeDisabled?: boolean;
  workspaceError?: string | null;
  onWorkspaceScopeChange?: (scope: WorkspaceScopePayload) => void;
  pendingQueueKey?: string | null;
  transcriptionProvider?: string | null;
}

const COMMAND_ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  "book-open": BookOpen,
  brain: Brain,
  "circle-help": CircleHelp,
  history: History,
  "rotate-cw": RotateCw,
  shield: Shield,
  sparkles: Sparkles,
  square: Square,
  "square-pen": SquarePen,
  "undo-2": Undo2,
};

const SLASH_PALETTE_GAP_PX = 8;
const SLASH_PALETTE_MAX_HEIGHT_PX = 288;
const SLASH_PALETTE_MIN_HEIGHT_PX = 144;
const SLASH_PALETTE_CHROME_PX = 12;
const SLASH_RECENTS_STORAGE_KEY = "nanobot.webui.slashCommandRecents";
const SLASH_RECENTS_LIMIT = 5;
const QUEUED_PROMPTS_STORAGE_PREFIX = "nanobot.webui.composerQueuedGuidance.v1:";
const QUEUED_PROMPTS_LIMIT = 20;
const QUEUED_PROMPT_MAX_CHARS = 4000;

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

type SlashPalettePlacement = "above" | "below";

interface SlashPaletteLayout {
  placement: SlashPalettePlacement;
  maxHeight: number;
}

interface QueuedPrompt {
  id: string;
  text: string;
  images?: QueuedPromptImage[];
}

interface QueuedPromptImage {
  dataUrl: string;
  name?: string;
}

interface CliAppMentionQuery {
  query: string;
  start: number;
  end: number;
}

type MentionCandidate =
  | { kind: "cli"; name: string; app: CliAppInfo }
  | { kind: "mcp"; name: string; preset: McpPresetInfo };

interface SlashPaletteCommand {
  command: string;
  title: string;
  description: string;
  icon: string;
  argHint?: string;
  detail: string;
  badge?: string;
  recent: boolean;
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

function normalizeQueuedPrompt(item: unknown, index: number): QueuedPrompt | null {
  if (!item || typeof item !== "object") return null;
  const record = item as Partial<QueuedPrompt>;
  if (typeof record.text !== "string") return null;
  const text = record.text.trim().slice(0, QUEUED_PROMPT_MAX_CHARS);
  const images = Array.isArray(record.images)
    ? record.images.flatMap((image) => {
        if (!image || typeof image !== "object") return [];
        const candidate = image as Partial<QueuedPromptImage>;
        if (typeof candidate.dataUrl !== "string" || !candidate.dataUrl.startsWith("data:image/")) {
          return [];
        }
        return [{
          dataUrl: candidate.dataUrl,
          ...(typeof candidate.name === "string" && candidate.name.trim()
            ? { name: candidate.name.trim() }
            : {}),
        }];
      }).slice(0, MAX_IMAGES_PER_MESSAGE)
    : [];
  if (!text && images.length === 0) return null;
  const id = typeof record.id === "string" && record.id.trim()
    ? record.id
    : `queued-prompt-restored-${index}`;
  return { id, text, ...(images.length > 0 ? { images } : {}) };
}

function readQueuedPrompts(storageKey: string): QueuedPrompt[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item, index) => normalizeQueuedPrompt(item, index))
      .filter((item): item is QueuedPrompt => item != null)
      .slice(0, QUEUED_PROMPTS_LIMIT);
  } catch {
    return [];
  }
}

function storeQueuedPrompts(storageKey: string, prompts: QueuedPrompt[]): void {
  if (typeof window === "undefined") return;
  try {
    if (prompts.length === 0) {
      window.localStorage.removeItem(storageKey);
      return;
    }
    window.localStorage.setItem(
      storageKey,
      JSON.stringify(
        prompts.slice(0, QUEUED_PROMPTS_LIMIT).map((prompt) => ({
          id: prompt.id,
          text: prompt.text.slice(0, QUEUED_PROMPT_MAX_CHARS),
          ...(prompt.images?.length ? { images: prompt.images.slice(0, MAX_IMAGES_PER_MESSAGE) } : {}),
        })),
      ),
    );
  } catch {
    // localStorage persistence is a convenience; the in-memory queue still works.
  }
}

function readyImagesToQueuedImages(
  images: Array<AttachedImage & { dataUrl: string }>,
): QueuedPromptImage[] {
  return images.map((img) => ({
    dataUrl: img.dataUrl,
    name: img.file.name,
  }));
}

function queuedImagesToSendImages(images?: QueuedPromptImage[]): SendImage[] | undefined {
  if (!images?.length) return undefined;
  return images.map((img) => ({
    media: {
      data_url: img.dataUrl,
      ...(img.name ? { name: img.name } : {}),
    },
    preview: {
      url: img.dataUrl,
      ...(img.name ? { name: img.name } : {}),
    },
  }));
}

function queuedPromptLabel(prompt: QueuedPrompt): string {
  const text = prompt.text.trim();
  if (text) return text;
  return prompt.images?.map((img) => img.name).filter(Boolean).join(", ") || "Image attachment";
}

function suppressNativeDragPreview(dataTransfer: DataTransfer): void {
  if (typeof document === "undefined" || typeof dataTransfer.setDragImage !== "function") {
    return;
  }
  const ghost = document.createElement("div");
  ghost.style.position = "fixed";
  ghost.style.left = "-9999px";
  ghost.style.top = "-9999px";
  ghost.style.width = "1px";
  ghost.style.height = "1px";
  ghost.style.opacity = "0";
  document.body.appendChild(ghost);
  try {
    dataTransfer.setDragImage(ghost, 0, 0);
  } catch {
    ghost.remove();
    return;
  }
  window.setTimeout(() => ghost.remove(), 0);
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
  const viewport = visualViewportBounds();
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

function RunPulseIcon() {
  return (
    <span className="run-pulse-icon relative flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>
      <span className="run-pulse-icon__ring" />
      <span className="run-pulse-icon__dot" />
    </span>
  );
}

function RunElapsedStrip({
  startedAt,
  goalState,
}: {
  startedAt: number | null;
  goalState?: GoalStateWsPayload;
}) {
  const { t } = useTranslation();
  const [goalPanelOpen, setGoalPanelOpen] = useState(false);
  const showTimer = startedAt != null;
  const stripLabel = goalStateStripPreview(goalState, t);
  const showGoal = !!stripLabel?.trim();
  const active = showTimer || showGoal;
  const [renderStrip, setRenderStrip] = useState(active);
  const [leaving, setLeaving] = useState(false);
  const [, setTick] = useState(0);
  const stripWrapperRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const expandToggleRef = useRef<HTMLButtonElement>(null);
  const stripSnapshotRef = useRef<{
    startedAt: number | null;
    goalState?: GoalStateWsPayload;
    stripLabel: string | null;
  } | null>(null);
  const [panelMaxPx, setPanelMaxPx] = useState(280);

  if (active) {
    stripSnapshotRef.current = { startedAt, goalState, stripLabel };
  }

  useEffect(() => {
    if (active) {
      setRenderStrip(true);
      setLeaving(false);
      return;
    }
    setGoalPanelOpen(false);
    if (!renderStrip) return;
    setLeaving(true);
    const id = window.setTimeout(() => {
      setRenderStrip(false);
      setLeaving(false);
    }, 180);
    return () => window.clearTimeout(id);
  }, [active, renderStrip]);

  useEffect(() => {
    if (startedAt == null) return;
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);

  const display = active
    ? { startedAt, goalState, stripLabel }
    : stripSnapshotRef.current;
  const displayStartedAt = display?.startedAt ?? null;
  const displayGoalState = display?.goalState;
  const displayStripLabel = display?.stripLabel ?? null;
  const displayShowTimer = displayStartedAt != null;
  const displayShowGoal = !!displayStripLabel?.trim();

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

    preloadMarkdownText();
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

  if (!renderStrip || !display) return null;

  const elapsed =
    displayStartedAt != null ? Math.max(0, Math.floor(Date.now() / 1000 - displayStartedAt)) : 0;
  const m = Math.floor(elapsed / 60);
  const sec = elapsed % 60;
  const shortElapsed = m > 0 ? `${m}:${sec.toString().padStart(2, "0")}` : `${sec}s`;
  const timerTitle = displayShowTimer
    ? t("thread.composer.runRuntimeTitle", { elapsed: shortElapsed })
    : null;

  const ariaParts = [timerTitle, displayShowGoal ? displayStripLabel : null].filter(Boolean);
  const ariaLabel = ariaParts.join(" · ");

  return (
    <div
      ref={stripWrapperRef}
      className="composer-status-strip relative z-30"
      data-state={leaving ? "exit" : "enter"}
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
            "rounded-2xl border border-black/[0.08] bg-card shadow-[0_12px_40px_rgba(15,23,42,0.14)]",
            "backdrop-blur-sm dark:border-white/[0.1] dark:shadow-[0_16px_48px_rgba(0,0,0,0.45)]",
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
                "text-muted-foreground transition-colors hover:bg-muted/65 hover:text-foreground",
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
      <div
        className="flex min-h-[36px] items-center gap-2 border-b border-black/[0.04] px-3 py-2 dark:border-white/[0.06]"
        role="status"
        aria-label={ariaLabel}
      >
        {displayShowTimer ? (
          <RunPulseIcon />
        ) : (
          <Target className="h-4 w-4 shrink-0 text-primary/75" aria-hidden />
        )}
        <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[12px] font-medium text-foreground/75">
          {timerTitle ? <span className="shrink-0">{timerTitle}</span> : null}
          {timerTitle && displayShowGoal ? (
            <span className="shrink-0 text-muted-foreground/45" aria-hidden>
              ·
            </span>
          ) : null}
          {displayShowGoal ? (
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
              "text-muted-foreground transition-colors hover:bg-muted/55 hover:text-foreground",
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
    </div>
  );
}

export function ThreadComposer({
  onSend,
  disabled,
  placeholder,
  isStreaming = false,
  modelLabel = null,
  modelProvider = null,
  modelProviderLabel = null,
  modelNeedsSetup = false,
  onModelBadgeClick,
  variant = "thread",
  slashCommands = [],
  cliApps = [],
  mcpPresets = [],
  skills = [],
  onStop,
  onTranscribeAudio,
  runStartedAt = null,
  goalState,
  workspaceScope = null,
  workspaceDefaultScope = null,
  workspaceControls = null,
  workspaceScopeDisabled = false,
  workspaceError = null,
  onWorkspaceScopeChange,
  pendingQueueKey = null,
  transcriptionProvider = null,
}: ThreadComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [slashMenuDismissed, setSlashMenuDismissed] = useState(false);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const [cliAppMenuDismissed, setCliAppMenuDismissed] = useState(false);
  const [selectedCliAppIndex, setSelectedCliAppIndex] = useState(0);
  const [cursorPosition, setCursorPosition] = useState(0);
  const [recentSlashCommands, setRecentSlashCommands] = useState<string[]>(() => readSlashRecents());
  const [queuedPrompts, setQueuedPrompts] = useState<QueuedPrompt[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chipRefs = useRef(new Map<string, HTMLButtonElement>());
  const queuedPromptCounterRef = useRef(0);
  const draggedQueuedPromptIdRef = useRef<string | null>(null);
  const previousPendingQueueKeyRef = useRef(pendingQueueKey);
  const wasStreamingRef = useRef(isStreaming);
  const skipNextQueuedFlushRef = useRef(false);
  const skipQueuedPromptPersistRef = useRef(false);
  const voiceShortcutDownRef = useRef(false);
  const isHero = variant === "hero";
  const voiceShortcutLabel = useMemo(getVoiceShortcutLabel, []);
  const queuedPromptStorageKey = useMemo(
    () => queuedPromptsStorageKey(pendingQueueKey),
    [pendingQueueKey],
  );
  const showProjectPicker =
    isHero
    && !!workspaceDefaultScope
    && !!onWorkspaceScopeChange
    && workspaceControls?.can_change_project !== false;

  useEffect(() => {
    skipQueuedPromptPersistRef.current = true;
    setQueuedPrompts(queuedPromptStorageKey ? readQueuedPrompts(queuedPromptStorageKey) : []);
  }, [queuedPromptStorageKey]);

  useEffect(() => {
    if (!queuedPromptStorageKey) return;
    if (skipQueuedPromptPersistRef.current) {
      skipQueuedPromptPersistRef.current = false;
      return;
    }
    storeQueuedPrompts(queuedPromptStorageKey, queuedPrompts);
  }, [queuedPromptStorageKey, queuedPrompts]);

  const resolvedPlaceholder = isStreaming
    ? t("thread.composer.placeholderStreaming")
    : placeholder ?? t("thread.composer.placeholderThread");

  const { images, enqueue, remove, clear, restoreReadyImages, encoding, full } =
    useAttachedImages();

  const formatRejection = useCallback(
    (reason: AttachmentError): string => {
      const key = `thread.composer.imageRejected.${reason}`;
      return t(key, { max: MAX_IMAGES_PER_MESSAGE });
    },
    [t],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const { rejected } = enqueue(files);
      if (rejected.length > 0) {
        setInlineError(formatRejection(rejected[0].reason));
      } else {
        setInlineError(null);
      }
    },
    [enqueue, formatRejection],
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
    if (disabled) return;
    const el = textareaRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => el.focus());
    return () => cancelAnimationFrame(id);
  }, [disabled]);

  const readyImages = useMemo(
    () => images.filter((img): img is AttachedImage & { dataUrl: string } =>
      img.status === "ready" && typeof img.dataUrl === "string",
    ),
    [images],
  );
  const hasErrors = images.some((img) => img.status === "error");

  const hasComposerContent = value.trim().length > 0 || readyImages.length > 0;
  const canSend =
    !disabled
    && !modelNeedsSetup
    && !encoding
    && !hasErrors
    && hasComposerContent;
  const canOpenModelSettings = Boolean(modelNeedsSetup && onModelBadgeClick && !disabled);
  const canQueueGuidance =
    isStreaming
    && !disabled
    && !modelNeedsSetup
    && !encoding
    && !hasErrors
    && hasComposerContent
    && !value.trimStart().startsWith("/");

  const slashQuery = useMemo(() => {
    if (disabled || slashMenuDismissed || !value.startsWith("/")) return null;
    const commandToken = value.slice(1);
    if (/\s/.test(commandToken)) return null;
    return commandToken.toLowerCase();
  }, [disabled, slashMenuDismissed, value]);

  const skillQuery = useMemo(() => {
    if (disabled || slashMenuDismissed) return null;
    const caret = Math.min(Math.max(cursorPosition, 0), value.length);
    const beforeCaret = value.slice(0, caret);
    const match = /\$([A-Za-z0-9_-]*)$/i.exec(beforeCaret);
    if (!match) return null;
    return {
      end: caret,
      start: match.index,
      text: match[1].toLowerCase(),
    };
  }, [cursorPosition, disabled, slashMenuDismissed, value]);

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
        .filter((skill) => skill.available)
        .filter((skill) => {
          const haystack = [
            skill.name,
            skill.description,
          ].join(" ").toLowerCase();
          return haystack.includes(query);
        })
        .map((skill) => {
          const command = `$${skill.name}`;
          const description = skill.description || skill.name;
          return {
            command,
            title: skill.name,
            description,
            detail: description,
            icon: "brain",
            recent: recentSlashCommands.includes(command),
          };
        })
        .slice(0, 8);
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
    if (disabled || cliAppMenuDismissed) return null;
    const caret = Math.min(Math.max(cursorPosition, 0), value.length);
    const beforeCaret = value.slice(0, caret);
    const match = /(?:^|\s)@([a-z0-9_-]*)$/i.exec(beforeCaret);
    if (!match) return null;
    const query = match[1].toLowerCase();
    return {
      query,
      start: caret - query.length - 1,
      end: caret,
    };
  }, [cliAppMenuDismissed, cursorPosition, disabled, value]);

  const filteredMentionCandidates = useMemo<MentionCandidate[]>(() => {
    if (!cliAppMention) return [];
    const cliCandidates: MentionCandidate[] = cliApps
      .filter((app) => app.installed)
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
      .map((app) => ({ kind: "cli", name: app.name, app }));
    const mcpCandidates: MentionCandidate[] = mcpPresets
      .filter((preset) => preset.installed && preset.configured)
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
      .map((preset) => ({ kind: "mcp", name: preset.name, preset }));
    return [...cliCandidates, ...mcpCandidates].slice(0, 8);
  }, [cliAppMention, cliApps, mcpPresets]);

  const showCliAppMenu = filteredMentionCandidates.length > 0;
  const showAnyPalette = showSlashMenu || showCliAppMenu;
  const mentionSegments = useMemo(
    () => splitCapabilityMentionSegments(value, cliApps, mcpPresets),
    [cliApps, mcpPresets, value],
  );
  const hasMentionDecorations = mentionSegments.some(
    (segment) => segment.kind === "cli" || segment.kind === "mcp",
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
      const placement: SlashPalettePlacement =
        spaceAbove >= SLASH_PALETTE_MIN_HEIGHT_PX || spaceAbove >= spaceBelow
          ? "above"
          : "below";
      const available = placement === "above" ? spaceAbove : spaceBelow;
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
    return () => {
      viewport?.removeEventListener("resize", updateLayout);
      viewport?.removeEventListener("scroll", updateLayout);
      window.removeEventListener("resize", updateLayout);
      document.removeEventListener("scroll", updateLayout, true);
    };
  }, [filteredMentionCandidates.length, filteredSlashCommands.length, showAnyPalette]);

  const resizeTextarea = useCallback(() => {
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
      el.focus();
    });
  }, []);

  // Runs before paint so switching sessions never flashes stale draft text.
  useLayoutEffect(() => {
    if (previousPendingQueueKeyRef.current === pendingQueueKey) return;
    previousPendingQueueKeyRef.current = pendingQueueKey;
    setValue("");
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

  const clearInlineError = useCallback(() => setInlineError(null), []);
  const setVoiceError = useCallback((key: VoiceRecorderErrorKey) => {
    setInlineError(t(`thread.composer.voiceErrors.${key}`));
  }, [t]);
  const voiceRecorder = useVoiceRecorder({
    disabled,
    onClearError: clearInlineError,
    onError: setVoiceError,
    onTranscript: appendTranscription,
    onTranscribeAudio,
    wantsWav: transcriptionProvider === "xiaomi_mimo",
  });

  useEffect(() => {
    if (!onTranscribeAudio) return;

    function onKeyDown(event: KeyboardEvent): void {
      if (!isVoiceShortcutDown(event) || event.repeat || voiceShortcutDownRef.current) return;
      event.preventDefault();
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

  const chooseSlashCommand = useCallback(
    (command: SlashPaletteCommand) => {
      if (command.command === "/stop" && isStreaming && onStop) {
        onStop();
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
        setValue(next);
        setCursorPosition(nextCursor);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(nextCursor, nextCursor);
        });
      } else {
        setValue(command.argHint ? `${command.command} ` : command.command);
      }
      setSlashMenuDismissed(true);
      setCliAppMenuDismissed(false);
      setInlineError(null);
      resizeTextarea();
    },
    [isStreaming, onStop, recentSlashCommands, resizeTextarea, skillQuery, value],
  );

  const chooseMentionCandidate = useCallback(
    (candidate: MentionCandidate) => {
      if (!cliAppMention) return;
      const suffix = value.slice(cliAppMention.end);
      const mention = `@${candidate.name}${suffix.startsWith(" ") ? "" : " "}`;
      const next = `${value.slice(0, cliAppMention.start)}${mention}${suffix}`;
      const nextCursor = cliAppMention.start + mention.length;
      setValue(next);
      setCursorPosition(nextCursor);
      setCliAppMenuDismissed(true);
      setSlashMenuDismissed(false);
      setInlineError(null);
      resizeTextarea();
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(nextCursor, nextCursor);
      });
    },
    [cliAppMention, resizeTextarea, value],
  );

  const clearComposerText = useCallback(() => {
    setValue("");
    setInlineError(null);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setCursorPosition(0);
    resizeTextarea();
  }, [resizeTextarea]);

  const queueGuidancePrompt = useCallback(() => {
    const text = value.trim();
    if (!canQueueGuidance || (!text && readyImages.length === 0)) return;
    const queuedImages = readyImagesToQueuedImages(readyImages);
    queuedPromptCounterRef.current += 1;
    setQueuedPrompts((items) => [
      ...items,
      {
        id: `queued-prompt-${Date.now()}-${queuedPromptCounterRef.current}`,
        text,
        ...(queuedImages.length > 0 ? { images: queuedImages } : {}),
      },
    ]);
    clear();
    clearComposerText();
  }, [canQueueGuidance, clear, clearComposerText, readyImages, value]);

  const removeQueuedPrompt = useCallback((id: string) => {
    setQueuedPrompts((items) => items.filter((item) => item.id !== id));
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const editQueuedPrompt = useCallback((prompt: QueuedPrompt) => {
    setQueuedPrompts((items) => items.filter((item) => item.id !== prompt.id));
    setValue(prompt.text);
    setInlineError(null);
    setSlashMenuDismissed(false);
    setCliAppMenuDismissed(false);
    setCursorPosition(prompt.text.length);
    if (prompt.images?.length) {
      restoreReadyImages(prompt.images as RestoredReadyImage[]);
    } else {
      clear();
    }
    resizeTextarea();
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(prompt.text.length, prompt.text.length);
    });
  }, [clear, resizeTextarea, restoreReadyImages]);

  const moveQueuedPrompt = useCallback((dragId: string, targetId: string) => {
    if (dragId === targetId) return;
    setQueuedPrompts((items) => {
      const from = items.findIndex((item) => item.id === dragId);
      const to = items.findIndex((item) => item.id === targetId);
      if (from === -1 || to === -1) return items;
      const next = [...items];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }, []);

  const sendQueuedPrompt = useCallback(
    (prompt: QueuedPrompt) => {
      const text = prompt.text.trim();
      const queuedImages = queuedImagesToSendImages(prompt.images);
      setQueuedPrompts((items) => items.filter((item) => item.id !== prompt.id));
      if (text || queuedImages?.length) {
        if (queuedImages?.length) onSend(text, queuedImages);
        else onSend(text);
      }
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
    [onSend],
  );

  const sendNextQueuedPrompt = useCallback(() => {
    if (queuedPrompts.length === 0) return;
    const nextPrompt = queuedPrompts.find((prompt) => prompt.text.trim());
    if (!nextPrompt) {
      setQueuedPrompts([]);
      return;
    }
    setQueuedPrompts((items) => items.filter((item) => item.id !== nextPrompt.id));
    const queuedImages = queuedImagesToSendImages(nextPrompt.images);
    if (queuedImages?.length) onSend(nextPrompt.text.trim(), queuedImages);
    else onSend(nextPrompt.text.trim());
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [onSend, queuedPrompts]);

  useEffect(() => {
    const wasStreaming = wasStreamingRef.current;
    wasStreamingRef.current = isStreaming;
    if (!wasStreaming || isStreaming || queuedPrompts.length === 0) return;
    if (skipNextQueuedFlushRef.current) {
      skipNextQueuedFlushRef.current = false;
      return;
    }
    sendNextQueuedPrompt();
  }, [sendNextQueuedPrompt, isStreaming, queuedPrompts.length]);

  const handleStop = useCallback(() => {
    if (queuedPrompts.length > 0) {
      skipNextQueuedFlushRef.current = true;
    }
    onStop?.();
  }, [onStop, queuedPrompts.length]);

  const submit = useCallback(() => {
    if (modelNeedsSetup) {
      onModelBadgeClick?.();
      return;
    }
    if (!canSend) return;
    const trimmed = value.trim();
    const content = trimmed;
    // Share the same normalized ``data:`` URL with both the wire payload and
    // the optimistic bubble preview: data URLs are self-contained (no blob
    // lifetime, safe under React StrictMode double-mount) and keep the
    // bubble in sync with whatever the backend actually sees.
    const payload: SendImage[] | undefined =
      readyImages.length > 0
        ? readyImages.map((img) => ({
            media: {
              data_url: img.dataUrl,
              name: img.file.name,
            },
            preview: { url: img.dataUrl, name: img.file.name },
          }))
        : undefined;
    const attachedCliApps = activeCliMentionApps.map(cliAppMentionPayload);
    const attachedMcpPresets = activeMcpPresetMentions.map(mcpPresetMentionPayload);
    const options: SendOptions | undefined =
      attachedCliApps.length > 0 || attachedMcpPresets.length > 0
        ? {
            ...(attachedCliApps.length > 0 ? { cliApps: attachedCliApps } : {}),
            ...(attachedMcpPresets.length > 0 ? { mcpPresets: attachedMcpPresets } : {}),
          }
        : undefined;
    const hasPlainTextCommandPayload =
      payload === undefined
      && attachedCliApps.length === 0
      && attachedMcpPresets.length === 0;
    const slashLifecycle = hasPlainTextCommandPayload
      ? slashCommandLifecycle(content, slashCommands)
      : null;
    if (
      slashLifecycle === "stop_active_turn"
      && isStreaming
      && onStop
    ) {
      handleStop();
      setQueuedPrompts([]);
      clear();
      clearComposerText();
      return;
    }
    const isSlashSideChannel = isSideChannelLifecycle(slashLifecycle);
    const finalizeActiveTurn =
      slashLifecycle === "finalize_active_turn";
    onSend(
      content,
      payload,
      isSlashSideChannel
        ? {
            ...options,
            sideChannel: true,
            ...(finalizeActiveTurn ? { finalizeActiveTurn } : {}),
          }
        : options,
    );
    setQueuedPrompts([]);
    // Bubble owns the data URL copy; safe to revoke every staged blob
    // preview here without affecting the rendered message.
    clear();
    clearComposerText();
  }, [
    activeCliMentionApps,
    activeMcpPresetMentions,
    canSend,
    clear,
    clearComposerText,
    handleStop,
    isStreaming,
    modelNeedsSetup,
    onModelBadgeClick,
    onSend,
    onStop,
    readyImages,
    slashCommands,
    value,
  ]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
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
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canQueueGuidance) {
        queueGuidancePrompt();
        return;
      }
      submit();
    }
  };

  const onInput: React.FormEventHandler<HTMLTextAreaElement> = (e) => {
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

  const attachButtonDisabled = disabled || full;
  const showVoiceButton = Boolean(onTranscribeAudio);
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
  const showStopButton = isStreaming && !!onStop;
  const relaxedHeroInput = isHero && images.length === 0 && !isStreaming;
  const inputTextClasses = cn(
    "w-full resize-none bg-transparent",
    isHero
      ? cn(
          "min-h-[78px] px-4 text-[16px] leading-6 sm:px-5",
          relaxedHeroInput ? "pb-2 pt-[27px]" : "pb-1.5 pt-4",
        )
      : "min-h-[50px] px-3.5 pb-1.5 pt-3 text-[16px] leading-5 sm:px-4",
  );

  return (
    <form
      ref={formRef}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn("relative w-full", isHero ? "px-0" : "px-1 pb-1.5 pt-1 sm:px-0")}
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
        className={cn(
          "group/composer relative mx-auto flex w-full flex-col overflow-visible transition-all duration-200",
          "after:pointer-events-none after:absolute after:inset-[-1px] after:rounded-[inherit] after:border after:border-blue-300/75 after:opacity-0 after:transition-opacity after:duration-200 focus-within:after:opacity-100 dark:after:border-blue-400/55",
          isHero
            ? "max-w-[58rem] rounded-[28px] border border-black/[0.035] bg-card shadow-[0_20px_55px_rgba(15,23,42,0.08)] dark:border-white/[0.06] dark:shadow-[0_24px_55px_rgba(0,0,0,0.34)]"
            : "max-w-[49.5rem] rounded-[22px] border border-black/[0.035] bg-card shadow-[0_12px_30px_rgba(15,23,42,0.07)] dark:border-white/[0.06] dark:shadow-[0_16px_34px_rgba(0,0,0,0.28)]",
          "focus-within:border-blue-300/75 dark:focus-within:border-blue-400/55",
          disabled && "opacity-60",
          isDragging && "ring-2 ring-primary/40 motion-reduce:ring-0 motion-reduce:border-primary",
          goalState?.active &&
            "goal-shell-glow ring-1 ring-sky-400/35 motion-reduce:ring-sky-400/25 dark:ring-sky-400/45",
        )}
      >
        {queuedPrompts.length > 0 ? (
          <QueuedPromptStack
            prompts={queuedPrompts}
            isHero={isHero}
            label={t("thread.composer.queued.label")}
            guideLabel={t("thread.composer.queued.guide")}
            deleteLabel={t("thread.composer.queued.delete")}
            dragLabel={t("thread.composer.queued.drag")}
            editLabel={t("thread.composer.queued.edit")}
            onGuide={sendQueuedPrompt}
            onDelete={removeQueuedPrompt}
            onEdit={editQueuedPrompt}
            onDragStart={(id) => {
              draggedQueuedPromptIdRef.current = id;
            }}
            onDragEnd={() => {
              draggedQueuedPromptIdRef.current = null;
            }}
            onDrop={(targetId) => {
              const dragId = draggedQueuedPromptIdRef.current;
              if (dragId) moveQueuedPrompt(dragId, targetId);
            }}
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
        <RunElapsedStrip startedAt={runStartedAt} goalState={goalState} />
        <div className="relative">
          {hasMentionDecorations ? (
            <ComposerCliMentionOverlay
              segments={mentionSegments}
              isHero={isHero}
              className={inputTextClasses}
            />
          ) : null}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setSlashMenuDismissed(false);
              setCliAppMenuDismissed(false);
              setCursorPosition(e.target.selectionStart ?? e.target.value.length);
            }}
            onInput={onInput}
            onKeyDown={onKeyDown}
            onKeyUp={(e) => setCursorPosition(e.currentTarget.selectionStart ?? e.currentTarget.value.length)}
            onSelect={(e) => setCursorPosition(e.currentTarget.selectionStart ?? e.currentTarget.value.length)}
            onClick={(e) => setCursorPosition(e.currentTarget.selectionStart ?? e.currentTarget.value.length)}
            onPaste={onPaste}
            rows={1}
            placeholder={resolvedPlaceholder}
            disabled={disabled}
            aria-label={t("thread.composer.inputAria")}
            className={cn(
              inputTextClasses,
              "relative z-10 caret-foreground placeholder:text-muted-foreground/70",
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
              "mx-3 mb-1 rounded-md border border-destructive/40 bg-destructive/8 px-2.5 py-1",
              "text-[11.5px] font-medium text-destructive",
            )}
          >
            {inlineError}
          </div>
        ) : null}
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-y-2",
            isHero
              ? cn("gap-x-1.5 px-3 sm:px-4", showProjectPicker ? "pb-1.5" : "pb-3.5")
              : "gap-x-2 px-2.5 pb-2 sm:px-3",
          )}
        >
          <div className={cn("flex min-w-0 flex-1 basis-[8rem] items-center", isHero ? "gap-1.5" : "gap-2")}>
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
              variant="ghost"
              disabled={attachButtonDisabled}
              aria-label={t("thread.composer.attachImage")}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "rounded-full text-muted-foreground hover:text-foreground",
                isHero
                  ? "h-8 w-8 border border-border/55 bg-card shadow-[0_2px_8px_rgba(15,23,42,0.05)] hover:bg-card"
                  : "h-9 w-9 border border-border/55 bg-card shadow-[0_2px_8px_rgba(15,23,42,0.05)] hover:bg-card",
              )}
            >
              <Plus className={cn(isHero ? "h-[18px] w-[18px]" : "h-4 w-4")} />
            </Button>
            {voiceRecorder.isRecording ? (
              <VoiceRecordingMeter
                ariaLabel={voiceRecordingStatusLabel}
                className="mx-1 flex-1"
                elapsedLabel={voiceRecorder.elapsedLabel}
                isHero={isHero}
                levels={voiceRecorder.levels}
              />
            ) : workspaceScope ? (
              <WorkspaceAccessMenu
                scope={workspaceScope}
                disabled={disabled || workspaceScopeDisabled}
                canUseFullAccess={workspaceControls?.can_use_full_access !== false}
                isHero={isHero}
                onChange={onWorkspaceScopeChange}
              />
            ) : null}
          </div>
          <div className={cn("ml-auto flex min-w-0 shrink-0 items-center", isHero ? "gap-1.5" : "gap-2")}>
            {modelLabel && !voiceRecorder.isRecording ? (
              <ComposerModelBadge
                label={modelLabel}
                provider={modelProvider}
                providerLabel={modelProviderLabel}
                needsSetup={modelNeedsSetup}
                isHero={isHero}
                onClick={modelNeedsSetup ? onModelBadgeClick : undefined}
              />
            ) : null}
            {showVoiceButton ? (
              <TooltipProvider delayDuration={220} skipDelayDuration={80}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      disabled={voiceRecorder.buttonDisabled}
                      aria-label={voiceButtonLabel}
                      aria-keyshortcuts={VOICE_SHORTCUT_ARIA}
                      title={voiceButtonTooltip}
                      onPointerDown={voiceRecorder.beginPress}
                      onPointerUp={voiceRecorder.endPress}
                      onPointerCancel={voiceRecorder.endPress}
                      onClick={voiceRecorder.handleClick}
                      className={cn(
                        "rounded-full border border-transparent text-muted-foreground hover:bg-muted/65 hover:text-foreground",
                        isHero ? "h-8 w-8" : "h-9 w-9",
                        voiceRecorder.isRecording &&
                          "bg-red-500 text-white shadow-[0_8px_20px_rgba(239,68,68,0.22)] hover:bg-red-500 hover:text-white",
                      )}
                    >
                      {voiceRecorder.state === "transcribing" ? (
                        <Loader2 className={cn(isHero ? "h-4 w-4" : "h-4 w-4", "animate-spin")} />
                      ) : voiceRecorder.isRecording ? (
                        <Square className={cn(isHero ? "h-3.5 w-3.5" : "h-3.5 w-3.5")} fill="currentColor" />
                      ) : (
                        <Mic className={cn(isHero ? "h-4 w-4" : "h-4 w-4")} />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    align="center"
                    className="flex items-center gap-2 rounded-full border border-border/70 bg-background px-3 py-1.5 text-[13px] font-medium text-foreground shadow-[0_8px_24px_rgba(15,23,42,0.13)] dark:border-white/10 dark:bg-neutral-900 dark:text-white"
                  >
                    <span>{voiceButtonTooltip}</span>
                    {voiceRecorder.state === "idle" ? (
                      <kbd className="rounded-full bg-muted px-2 py-0.5 font-sans text-[12px] font-semibold leading-none text-muted-foreground dark:bg-white/10 dark:text-white/80">
                        {voiceShortcutLabel}
                      </kbd>
                    ) : null}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : null}
            <Button
              type={showStopButton || modelNeedsSetup ? "button" : "submit"}
              size="icon"
              disabled={showStopButton ? disabled : !canSend && !canOpenModelSettings}
              aria-label={
                showStopButton
                  ? t("thread.composer.stop")
                  : modelNeedsSetup
                    ? t("thread.composer.configureModel", { defaultValue: "Configure model" })
                    : t("thread.composer.send")
              }
              onClick={showStopButton ? handleStop : modelNeedsSetup ? onModelBadgeClick : undefined}
              className={cn(
                "rounded-full transition-transform",
                showStopButton
                  ? "border border-border/70 bg-card text-foreground/85 shadow-[0_3px_10px_rgba(15,23,42,0.08)] hover:bg-muted/65 hover:text-foreground disabled:text-muted-foreground/50"
                  : isHero
                    ? "border border-foreground bg-foreground text-background shadow-[0_4px_12px_rgba(15,23,42,0.20)] hover:bg-foreground/90 disabled:border-foreground disabled:bg-foreground disabled:text-background"
                    : "border border-foreground bg-foreground text-background shadow-[0_3px_10px_rgba(15,23,42,0.18)] hover:bg-foreground/90 disabled:border-foreground disabled:bg-foreground disabled:text-background",
                isHero ? "h-8 w-8" : "h-9 w-9",
                (canSend || canOpenModelSettings || showStopButton) && "hover:scale-[1.03] active:scale-95",
              )}
            >
              {showStopButton ? (
                <Square className={cn("fill-current stroke-current", isHero ? "h-3 w-3" : "h-3.5 w-3.5")} />
              ) : isStreaming ? (
                <Loader2 className={cn(isHero ? "h-4 w-4" : "h-4 w-4", "animate-spin")} />
              ) : (
                <ArrowUp className={cn(isHero ? "h-4 w-4" : "h-4 w-4")} />
              )}
            </Button>
          </div>
        </div>
        <WorkspaceProjectPicker
          isHero={isHero}
          disabled={disabled || workspaceScopeDisabled}
          scope={workspaceScope}
          defaultScope={workspaceDefaultScope}
          controls={workspaceControls}
          error={workspaceError}
          onChange={onWorkspaceScopeChange}
        />
      </div>
    </form>
  );
}

function QueuedPromptStack({
  prompts,
  isHero,
  label,
  guideLabel,
  deleteLabel,
  dragLabel,
  editLabel,
  onGuide,
  onDelete,
  onEdit,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  prompts: QueuedPrompt[];
  isHero: boolean;
  label: string;
  guideLabel: string;
  deleteLabel: string;
  dragLabel: string;
  editLabel: string;
  onGuide: (prompt: QueuedPrompt) => void;
  onDelete: (id: string) => void;
  onEdit: (prompt: QueuedPrompt) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onDrop: (targetId: string) => void;
}) {
  const stripMaxHeight = Math.min(240, 14 + prompts.length * 34 + Math.max(0, prompts.length - 1) * 4);

  return (
    <div
      role="group"
      data-state="enter"
      className={cn(
        "composer-status-strip relative z-20 mx-3 mt-3 overflow-hidden rounded-[18px]",
        "border border-black/[0.05] bg-popover/90 p-1.5",
        "shadow-[0_10px_28px_rgba(15,23,42,0.07)] backdrop-blur-md",
        "dark:border-white/[0.08] dark:bg-popover/90 dark:shadow-[0_14px_34px_rgba(0,0,0,0.30)]",
        isHero ? "max-w-none" : "max-w-none",
      )}
      style={{ "--composer-strip-max-height": `${stripMaxHeight}px` } as CSSProperties}
      aria-label={label}
    >
      <div className="flex max-h-[216px] flex-col gap-1 overflow-y-auto">
        {prompts.map((prompt) => (
          <QueuedPromptRow
            key={prompt.id}
            prompt={prompt}
            isHero={isHero}
            guideLabel={guideLabel}
            deleteLabel={deleteLabel}
            dragLabel={dragLabel}
            editLabel={editLabel}
            onGuide={onGuide}
            onDelete={onDelete}
            onEdit={onEdit}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDrop={onDrop}
          />
        ))}
      </div>
    </div>
  );
}

function QueuedPromptRow({
  prompt,
  isHero,
  guideLabel,
  deleteLabel,
  dragLabel,
  editLabel,
  onGuide,
  onDelete,
  onEdit,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  prompt: QueuedPrompt;
  isHero: boolean;
  guideLabel: string;
  deleteLabel: string;
  dragLabel: string;
  editLabel: string;
  onGuide: (prompt: QueuedPrompt) => void;
  onDelete: (id: string) => void;
  onEdit: (prompt: QueuedPrompt) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onDrop: (targetId: string) => void;
}) {
  const displayLabel = queuedPromptLabel(prompt);

  return (
    <div
      data-queued-prompt-row="true"
      onDragEnter={(event) => {
        event.preventDefault();
        onDrop(prompt.id);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDrop(prompt.id);
      }}
      onDragEnd={onDragEnd}
      className={cn(
        "queued-prompt-row group/queued flex min-h-8 items-center gap-1.5 rounded-[12px] px-2 py-0.5",
        "text-[13px] transition-colors hover:bg-muted/55 dark:hover:bg-white/[0.055]",
        isHero && "text-[13.5px]",
      )}
    >
      <span
        draggable
        role="button"
        tabIndex={0}
        aria-label={dragLabel}
        onDragStart={(event) => {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", prompt.id);
          suppressNativeDragPreview(event.dataTransfer);
          onDragStart(prompt.id);
        }}
        onDragEnd={onDragEnd}
        className={cn(
          "inline-flex h-7 w-7 shrink-0 cursor-grab items-center justify-center rounded-lg",
          "text-muted-foreground/45 transition-colors hover:bg-background/80 hover:text-muted-foreground",
          "active:cursor-grabbing dark:hover:bg-white/[0.06]",
        )}
      >
        <GripVertical className="pointer-events-none h-3.5 w-3.5" aria-hidden />
      </span>
      <div className="flex min-h-7 min-w-0 flex-1 items-center">
        <p
          title={displayLabel}
          className={cn(
            "line-clamp-3 whitespace-pre-wrap break-words font-medium leading-[1.28] text-foreground/88",
            isHero && "text-[13.5px]",
          )}
        >
          {displayLabel}
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 shrink-0 rounded-full px-2 text-[11.5px] font-medium text-muted-foreground hover:bg-muted/70 hover:text-foreground dark:hover:bg-white/[0.07]"
        onClick={() => onGuide(prompt)}
      >
        <CornerDownRight className="mr-1 h-3 w-3" aria-hidden />
        {guideLabel}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={editLabel}
        title={editLabel}
        className="h-7 w-7 shrink-0 rounded-full text-muted-foreground hover:bg-background/85 hover:text-foreground dark:hover:bg-white/[0.07]"
        onClick={() => onEdit(prompt)}
      >
        <SquarePen className="h-3.5 w-3.5" aria-hidden />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={deleteLabel}
        className="h-7 w-7 shrink-0 rounded-full text-muted-foreground hover:bg-background/85 hover:text-destructive dark:hover:bg-white/[0.07]"
        onClick={() => onDelete(prompt.id)}
      >
        <Trash2 className="h-3 w-3" aria-hidden />
      </Button>
    </div>
  );
}

function ComposerModelBadge({
  label,
  provider,
  providerLabel,
  needsSetup,
  isHero,
  onClick,
}: {
  label: string;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  isHero: boolean;
  onClick?: () => void;
}) {
  const inferredProvider = needsSetup ? null : provider || inferProviderFromModelName(label);
  const brand = providerBrand(inferredProvider);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const showLogo = !!logoUrl;
  const title = providerLabel ? `${label} · ${providerLabel}` : label;
  const interactive = Boolean(onClick);
  const Container = interactive ? "button" : "span";

  return (
    <Container
      title={title}
      type={interactive ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "inline-flex min-w-0 items-center rounded-full border border-border/55 bg-card font-medium text-foreground/82",
        "shadow-[0_2px_8px_rgba(15,23,42,0.045)]",
        interactive && "cursor-pointer hover:bg-accent/55 hover:text-foreground",
        needsSetup && "border-amber-500/35 bg-amber-50/70 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200",
        isHero
          ? "h-8 max-w-[min(12.5rem,44vw)] gap-1.5 px-2 text-[11.5px]"
          : "h-9 max-w-[min(12rem,44vw)] gap-2 px-2.5 text-[12px]",
      )}
    >
      <span
        data-testid={needsSetup ? "composer-model-setup-icon" : inferredProvider ? `composer-model-logo-${inferredProvider}` : "composer-model-logo"}
        className={cn(
          "grid shrink-0 place-items-center overflow-hidden",
          needsSetup
            ? "text-amber-800 dark:text-amber-200"
            : "rounded-full border bg-background",
          isHero ? "h-[18px] w-[18px]" : "h-5 w-5",
        )}
        style={{
          borderColor: !needsSetup && brand ? `${brand.color}28` : undefined,
          boxShadow: !needsSetup && brand ? `inset 0 0 0 1px ${brand.color}18` : undefined,
        }}
        aria-hidden
      >
        {needsSetup ? (
          <CircleHelp className={cn(isHero ? "h-3 w-3" : "h-3.5 w-3.5")} strokeWidth={1.8} />
        ) : showLogo ? (
          <img
            src={logoUrl}
            alt=""
            decoding="async"
            loading="lazy"
            className={cn("object-contain", isHero ? "h-3 w-3" : "h-3.5 w-3.5")}
            onLoad={onLogoLoad}
            onError={onLogoError}
          />
        ) : brand ? (
          <span
            className={cn(
              "grid h-full w-full place-items-center rounded-full text-white",
              isHero ? "text-[7.5px]" : "text-[8px]",
            )}
            style={{ backgroundColor: brand.color }}
          >
            {brand.initials.slice(0, 2)}
          </span>
        ) : (
          <Sparkles className={cn("text-muted-foreground/65", isHero ? "h-3 w-3" : "h-3 w-3")} />
        )}
      </span>
      <span className="truncate">{label}</span>
    </Container>
  );
}

function ComposerCliMentionOverlay({
  segments,
  isHero,
  className,
}: {
  segments: CapabilityMentionSegment[];
  isHero: boolean;
  className: string;
}) {
  return (
    <div
      aria-hidden
      className={cn(
        className,
        "pointer-events-none absolute inset-0 z-0 overflow-hidden whitespace-pre-wrap break-words text-foreground",
      )}
    >
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <span key={`text-${index}`}>{segment.text}</span>;
        }
        if (segment.kind === "cli") return (
          <CliAppMentionToken
            key={`cli-${segment.app.name}-${index}`}
            app={segment.app}
            label={segment.text}
            variant="composer"
            isHero={isHero}
          />
        );
        return (
          <McpPresetMentionToken
            key={`mcp-${segment.preset.name}-${index}`}
            preset={segment.preset}
            label={segment.text}
            variant="composer"
            isHero={isHero}
          />
        );
      })}
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
  return (
    <div
      role="listbox"
      aria-label={t("thread.composer.mentions.ariaLabel")}
      style={{ maxHeight: layout.maxHeight }}
      className={cn(
        "absolute left-1/2 z-30 w-[calc(100%-0.5rem)] -translate-x-1/2 overflow-hidden rounded-[22px] border",
        layout.placement === "above" ? "bottom-full mb-2" : "top-full mt-2",
        "border-border/70 bg-popover p-2 text-popover-foreground shadow-[0_20px_60px_rgba(15,23,42,0.12)]",
        "dark:border-white/10 dark:shadow-[0_24px_60px_rgba(0,0,0,0.42)]",
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div className="px-2 pb-1.5 pt-0.5 text-[13px] font-semibold text-muted-foreground/78">
        {t("thread.composer.mentions.label")}
      </div>
      <div ref={listRef} className="overflow-y-auto" style={{ maxHeight: listMaxHeight }}>
        {candidates.map((candidate, index) => {
          const selected = index === selectedIndex;
          const name = candidate.name;
          const displayName = candidate.kind === "cli"
            ? candidate.app.display_name
            : candidate.preset.display_name;
          const typeLabel = candidate.kind === "cli"
            ? t("thread.composer.mentions.cliBadge")
            : t("thread.composer.mentions.mcpBadge");
          const ariaDescription = candidate.kind === "cli"
            ? t("thread.composer.mentions.cliDescription", { name })
            : t("thread.composer.mentions.mcpDescription", { name });
          return (
            <button
              key={`${candidate.kind}-${name}`}
              type="button"
              role="option"
              data-palette-index={index}
              aria-selected={selected}
              aria-label={`${displayName} @${name} ${ariaDescription} ${typeLabel}`}
              onMouseEnter={() => onHover(index)}
              onMouseDown={(e) => {
                e.preventDefault();
                onChoose(candidate);
              }}
              className={cn(
                "flex min-h-10 w-full items-center gap-2.5 rounded-[13px] px-2.5 py-1.5 text-left transition-colors",
                selected
                  ? "bg-foreground/[0.055] text-foreground"
                  : "text-foreground/90 hover:bg-foreground/[0.04]",
              )}
            >
              <MentionCandidateLogo candidate={candidate} selected={selected} />
              <span className="flex min-w-0 flex-1 items-baseline gap-2">
                <span className="min-w-0 truncate text-[15px] font-medium tracking-normal text-foreground">
                  {displayName}
                </span>
                <span className="truncate text-[15px] font-normal tracking-normal text-muted-foreground/72">
                  @{name}
                </span>
              </span>
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
            </button>
          );
        })}
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
  const color = (candidate.kind === "cli"
    ? candidate.app.brand_color
    : candidate.preset.brand_color) || "hsl(var(--primary))";
  const rawLogoUrl = candidate.kind === "cli" ? candidate.app.logo_url : candidate.preset.logo_url;
  const logoUrls = useMemo(() => logoFallbackUrls(rawLogoUrl), [rawLogoUrl]);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  if (logoUrl) {
    return (
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-[5px]",
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
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-[5px] text-[7.5px] font-semibold text-white"
      style={{ backgroundColor: color }}
    >
      {candidate.kind === "cli"
        ? cliAppInitials(candidate.app)
        : mcpPresetInitials(candidate.preset)}
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
        "absolute left-1/2 z-30 w-[calc(100%-0.5rem)] -translate-x-1/2 overflow-hidden rounded-[18px] border",
        layout.placement === "above" ? "bottom-full mb-2" : "top-full mt-2",
        "border-border/65 bg-popover p-1.5 text-popover-foreground shadow-[0_18px_55px_rgba(15,23,42,0.16)]",
        "dark:border-white/10 dark:shadow-[0_22px_55px_rgba(0,0,0,0.45)]",
        isHero ? "max-w-[58rem]" : "max-w-[49.5rem]",
      )}
    >
      <div ref={listRef} className="overflow-y-auto pr-0.5" style={{ maxHeight: listMaxHeight }}>
        {commands.map((command, index) => {
          const Icon = COMMAND_ICONS[command.icon] ?? CircleHelp;
          const selected = index === selectedIndex;
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
                "flex min-h-[44px] w-full items-center gap-3 rounded-[13px] px-3 py-2 text-left transition-colors",
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
                <span className="min-w-0 truncate text-[13.5px] font-semibold tracking-normal text-foreground">
                  {title}
                </span>
                <span className="min-w-0 truncate text-[13px] text-muted-foreground">
                  {command.detail || description}
                </span>
              </span>
              <span className="ml-2 flex max-w-[42%] shrink-0 items-center gap-1.5 sm:max-w-none">
                {command.badge || command.recent ? (
                  <span className="hidden rounded-full bg-foreground/[0.055] px-2 py-1 text-[11px] font-medium text-muted-foreground sm:inline-flex">
                    {command.badge ?? t("thread.composer.slash.badges.recent")}
                  </span>
                ) : null}
                <span className="font-mono text-[12px] text-muted-foreground/60">
                  {command.argHint ? `${command.command} ${command.argHint}` : command.command}
                </span>
              </span>
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
        "group relative flex items-center gap-2 rounded-[12px] border px-2 py-1.5",
        "transition-colors motion-reduce:transition-none",
        tone,
      )}
      data-testid="composer-chip"
    >
      <div className="relative h-10 w-10 overflow-hidden rounded-md bg-background">
        {image.previewUrl ? (
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
            <ImageIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
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
          "text-muted-foreground/80 hover:bg-foreground/8 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
        )}
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
