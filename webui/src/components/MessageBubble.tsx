import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Check,
  ChevronRight,
  Clock3,
  Copy,
  GitFork,
  ImageIcon,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { AttachmentTile } from "@/components/AttachmentTile";
import { CliAppMentionText } from "@/components/CliAppMentionText";
import { ImageLightbox } from "@/components/ImageLightbox";
import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatTurnLatency } from "@/lib/format";
import { toMediaAttachment } from "@/lib/media";
import type {
  CliAppInfo,
  McpPresetInfo,
  UICliAppAttachment,
  UIMcpPresetAttachment,
  UIImage,
  UIMediaAttachment,
  UIMessage,
} from "@/lib/types";

interface MessageBubbleProps {
  message: UIMessage;
  /** When false, hide the assistant reply copy button (mid-turn text before more agent activity). Default true. */
  showAssistantCopyAction?: boolean;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  onOpenFilePreview?: (path: string) => void;
  onForkFromHere?: () => void;
}

/**
 * Render a single message. Following agent-chat-ui: user turns are a rounded
 * "pill" right-aligned with a muted fill; assistant turns render as bare
 * markdown so prose/code read like a document rather than a chat bubble.
 * Each turn fades+slides in for a touch of motion polish.
 *
 * Trace rows (tool-call hints, progress breadcrumbs) render as a subdued
 * collapsible group so intermediate steps never masquerade as replies.
 */
export function MessageBubble({
  message,
  showAssistantCopyAction = true,
  cliApps = [],
  mcpPresets = [],
  onOpenFilePreview,
  onForkFromHere,
}: MessageBubbleProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copyResetRef = useRef<number | null>(null);
  const baseAnim = "animate-in fade-in-0 slide-in-from-bottom-1 duration-300";
  const mentionCliApps = useMemo(
    () => mergeCliMentionApps(cliApps, message.cliApps),
    [cliApps, message.cliApps],
  );
  const mentionMcpPresets = useMemo(
    () => mergeMcpMentionPresets(mcpPresets, message.mcpPresets),
    [mcpPresets, message.mcpPresets],
  );

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
    };
  }, []);

  const onCopyAssistantReply = useCallback(() => {
    void copyTextToClipboard(message.content).then((ok) => {
      if (!ok) return;
      setCopied(true);
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => {
        setCopied(false);
        copyResetRef.current = null;
      }, 1_500);
    });
  }, [message.content]);

  if (message.kind === "trace") {
    return <TraceGroup message={message} animClass={baseAnim} />;
  }

  if (message.role === "user") {
    const images = message.images ?? [];
    const media = message.media ?? [];
    const hasImages = images.length > 0;
    const hasMedia = media.length > 0;
    const hasText = message.content.trim().length > 0;
    return (
      <div
        className={cn(
          "group ml-auto flex max-w-[min(85%,36rem)] flex-col items-end gap-1.5",
          baseAnim,
        )}
      >
        {hasImages ? <UserImages images={images} align="right" /> : null}
        {!hasImages && hasMedia ? (
          <MessageMedia media={media} align="right" />
        ) : null}
        {hasText ? (
          <p
            className={cn(
              "ml-auto w-fit rounded-[18px] bg-secondary/70 px-4 py-2",
              "text-left text-[16px]/[1.75] whitespace-pre-wrap break-words",
            )}
          >
            <CliAppMentionText
              text={message.content}
              cliApps={mentionCliApps}
              mcpPresets={mentionMcpPresets}
            />
          </p>
        ) : null}
      </div>
    );
  }

  const empty = message.content.trim().length === 0;
  const media = message.media ?? [];
  const reasoning = message.role === "assistant" ? message.reasoning ?? "" : "";
  const reasoningStreaming = !!(message.role === "assistant" && message.reasoningStreaming);
  const hasReasoning = reasoning.length > 0 || reasoningStreaming;
  const automationSourceLabel = message.source?.kind === "cron"
    ? (message.source.label?.trim() || t("message.automationSourceFallback"))
    : "";
  const automationTriggeredLabel = t("message.automationTriggered");

  const showAssistantActions = message.role === "assistant" && !message.isStreaming && !empty;
  const showCopyButton = showAssistantCopyAction && showAssistantActions;
  const showForkButton = showAssistantActions && !!onForkFromHere;
  const copyReplyLabel = copied ? t("message.copiedReply") : t("message.copyReply");
  const forkLabel = t("message.forkFromHere");
  const latencyMs = message.latencyMs;
  const showLatencyFooter =
    message.role === "assistant"
    && latencyMs != null
    && !message.isStreaming
    && (!empty || hasReasoning || media.length > 0);
  const showAssistantFooterRow = showCopyButton || showForkButton || showLatencyFooter;
  return (
    <div className={cn("w-full text-[15px]", baseAnim)} style={{ lineHeight: "var(--cjk-line-height)" }}>
      {hasReasoning ? (
        <ReasoningBubble
          text={reasoning}
          streaming={reasoningStreaming}
          hasBodyBelow={!empty}
          onOpenFilePreview={onOpenFilePreview}
        />
      ) : null}
      {empty && message.isStreaming && !hasReasoning ? (
        <TypingDots />
      ) : empty && message.isStreaming ? null : (
        <>
          {automationSourceLabel ? (
            <AutomationSourceBadge
              label={automationSourceLabel}
              triggerLabel={automationTriggeredLabel}
            />
          ) : null}
          <MarkdownText
            streaming={!!message.isStreaming}
            onOpenFilePreview={onOpenFilePreview}
          >
            {message.content}
          </MarkdownText>
          {media.length > 0 ? <MessageMedia media={media} align="left" /> : null}
          {showAssistantFooterRow ? (
            <TooltipProvider delayDuration={220} skipDelayDuration={80}>
              <div className="mt-2 flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
                {showCopyButton ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={onCopyAssistantReply}
                        aria-label={copyReplyLabel}
                        className={cn(
                          "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                          "transition-colors hover:bg-muted/55 hover:text-foreground",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        )}
                      >
                        {copied ? (
                          <Check className="h-4 w-4" aria-hidden />
                        ) : (
                          <Copy className="h-4 w-4" aria-hidden />
                        )}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="center">{copyReplyLabel}</TooltipContent>
                  </Tooltip>
                ) : null}
                {showForkButton ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        onClick={onForkFromHere}
                        aria-label={forkLabel}
                        className={cn(
                          "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                          "transition-colors hover:bg-muted/55 hover:text-foreground",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        )}
                      >
                        <GitFork className="h-4 w-4" aria-hidden />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="center">{forkLabel}</TooltipContent>
                  </Tooltip>
                ) : null}
                {showLatencyFooter ? (
                  <span
                    className="text-[11px] leading-none text-muted-foreground/70 tabular-nums"
                    title={t("message.turnLatencyTitle")}
                  >
                    {formatTurnLatency(latencyMs)}
                  </span>
                ) : null}
              </div>
            </TooltipProvider>
          ) : null}
        </>
      )}
    </div>
  );
}

function AutomationSourceBadge({ label, triggerLabel }: { label: string; triggerLabel: string }) {
  return (
    <div
      className={cn(
        "mb-2 inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-1",
        "border border-sky-500/15 bg-sky-500/[0.06]",
        "text-[11px] font-medium leading-none text-sky-700",
        "dark:border-sky-300/15 dark:bg-sky-300/[0.08] dark:text-sky-200/80",
      )}
      title={triggerLabel}
    >
      <Clock3 className="h-3 w-3 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">{label}</span>
      <span className="text-current/45" aria-hidden>·</span>
      <span className="shrink-0">{triggerLabel}</span>
    </div>
  );
}

function mergeMcpMentionPresets(
  presets: McpPresetInfo[],
  attachments: UIMcpPresetAttachment[] | undefined,
): McpPresetInfo[] {
  if (!attachments?.length) return presets;
  const byName = new Map(presets.map((preset) => [preset.name.toLowerCase(), preset]));
  for (const attachment of attachments) {
    const name = attachment.name?.trim();
    if (!name) continue;
    const existing = byName.get(name.toLowerCase());
    byName.set(name.toLowerCase(), {
      name,
      display_name: attachment.display_name || existing?.display_name || name,
      category: attachment.category || existing?.category || "mcp",
      description: existing?.description || "",
      docs_url: existing?.docs_url || "",
      transport: attachment.transport || existing?.transport || "mcp",
      requires: existing?.requires || "",
      note: existing?.note || "",
      install_supported: existing?.install_supported ?? true,
      installed: true,
      configured: attachment.configured ?? existing?.configured ?? true,
      available: existing?.available ?? true,
      status: attachment.status || existing?.status || "configured",
      logo_url: attachment.logo_url ?? existing?.logo_url ?? null,
      brand_color: attachment.brand_color ?? existing?.brand_color ?? null,
      required_fields: existing?.required_fields || [],
      connection_summary: existing?.connection_summary || "",
    });
  }
  return Array.from(byName.values());
}

function mergeCliMentionApps(
  cliApps: CliAppInfo[],
  attachments: UICliAppAttachment[] | undefined,
): CliAppInfo[] {
  if (!attachments?.length) return cliApps;
  const byName = new Map(cliApps.map((app) => [app.name.toLowerCase(), app]));
  for (const attachment of attachments) {
    const name = attachment.name?.trim();
    if (!name) continue;
    const existing = byName.get(name.toLowerCase());
    byName.set(name.toLowerCase(), {
      name,
      display_name: attachment.display_name || existing?.display_name || name,
      category: attachment.category || existing?.category || "cli",
      description: existing?.description || "",
      requires: existing?.requires || "",
      source: existing?.source || "attached",
      entry_point: attachment.entry_point || existing?.entry_point || "",
      install_supported: existing?.install_supported ?? true,
      installed: true,
      available: existing?.available ?? true,
      status: existing?.status || "installed",
      logo_url: attachment.logo_url ?? existing?.logo_url ?? null,
      brand_color: attachment.brand_color ?? existing?.brand_color ?? null,
      skill_installed: existing?.skill_installed ?? true,
    });
  }
  return Array.from(byName.values());
}

function MessageMedia({
  media,
  align,
}: {
  media: UIMediaAttachment[];
  align: "left" | "right";
}) {
  if (media.length === 0) return null;
  const images: UIImage[] = [];
  const nonImages: UIMediaAttachment[] = [];
  for (const item of media) {
    const normalized = toMediaAttachment(item);
    if (normalized.kind === "image") {
      images.push({ url: normalized.url, name: normalized.name });
    } else {
      nonImages.push(normalized);
    }
  }

  return (
    <div
      className={cn(
        "mt-2 flex flex-wrap gap-2",
        align === "right" ? "justify-end" : "justify-start",
      )}
    >
      {images.length > 0 ? (
        <UserImages images={images} align={align} size={align === "left" ? "large" : "compact"} />
      ) : null}
      {nonImages.map((item, i) => (
        <AttachmentTile key={`${item.url ?? item.name ?? item.kind}-${i}`} attachment={item} />
      ))}
    </div>
  );
}

/**
 * Right-aligned preview row for images attached to a user turn.
 *
 * Visual follows agent-chat-ui: a single wrapping row of fixed-size square
 * thumbnails that stay modest next to the text pill regardless of how many
 * images are attached.
 *
 * The URL is expected to be a self-contained ``data:`` URL (the Composer
 * hands the normalized base64 payload to the optimistic bubble so that the
 * preview survives React StrictMode double-mount — blob URLs would be
 * revoked by the Composer's cleanup before remount). Historical replays
 * have no URL (the backend strips data URLs before persisting), so we
 * render a labelled placeholder tile instead of a broken ``<img>``.
 */
function UserImages({
  images,
  align = "right",
  size = "compact",
}: {
  images: UIImage[];
  align?: "left" | "right";
  size?: "compact" | "large";
}) {
  const { t } = useTranslation();
  // Only real-URL images can open in the lightbox; historical-replay
  // placeholders (no URL) have nothing to zoom into.
  const viewableImages: UIImage[] = [];
  const originalToViewable = new Map<number, number>();
  for (let i = 0; i < images.length; i += 1) {
    const img = images[i];
    if (typeof img.url !== "string" || img.url.length === 0) continue;
    originalToViewable.set(i, viewableImages.length);
    viewableImages.push(img);
  }

  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  return (
    <>
      <div
        className={cn(
          "flex flex-wrap items-end gap-2",
          size === "large" && "gap-3",
          align === "right" ? "ml-auto justify-end" : "mr-auto justify-start",
        )}
      >
        {images.map((img, i) => (
          <UserImageCell
            key={`${img.url ?? "placeholder"}-${i}`}
            image={img}
            size={size}
            placeholderLabel={t("message.imageAttachment")}
            openLabel={t("lightbox.open")}
            onOpen={
              originalToViewable.has(i)
                ? () => setLightboxIndex(originalToViewable.get(i)!)
                : undefined
            }
          />
        ))}
      </div>
      <ImageLightbox
        images={viewableImages}
        index={lightboxIndex}
        onIndexChange={setLightboxIndex}
        onOpenChange={(open) => {
          if (!open) setLightboxIndex(null);
        }}
      />
    </>
  );
}

function UserImageCell({
  image,
  size,
  placeholderLabel,
  openLabel,
  onOpen,
}: {
  image: UIImage;
  size: "compact" | "large";
  placeholderLabel: string;
  openLabel: string;
  onOpen?: () => void;
}) {
  const hasUrl = typeof image.url === "string" && image.url.length > 0;
  const tileClasses = cn(
    "relative overflow-hidden border border-border/60 bg-muted/40",
    size === "large"
      ? "w-[min(100%,34rem)] rounded-[20px] bg-transparent"
      : "h-24 w-24 rounded-[14px]",
    "shadow-[0_6px_18px_-14px_rgba(0,0,0,0.45)]",
  );

  if (hasUrl && onOpen) {
    return (
      <button
        type="button"
        onClick={onOpen}
        aria-label={image.name ? `${openLabel}: ${image.name}` : openLabel}
        className={cn(
          tileClasses,
          "block cursor-zoom-in p-0 transition-transform duration-150 motion-reduce:transition-none",
          "hover:scale-[1.01] hover:ring-2 hover:ring-primary/25",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        )}
      >
        <img
          src={image.url}
          alt={image.name ?? ""}
          loading="lazy"
          decoding="async"
          draggable={false}
          className={cn(
            "block",
            size === "large"
              ? "h-auto max-h-[36rem] w-full rounded-[inherit] object-contain"
              : "h-full w-full object-cover",
          )}
        />
      </button>
    );
  }

  return (
    <div className={tileClasses} title={image.name ?? undefined}>
      <div
        className="flex h-full w-full flex-col items-center justify-center gap-1 px-2 text-[11px] text-muted-foreground"
        aria-label={placeholderLabel}
      >
        <ImageIcon className="h-4 w-4 flex-none" aria-hidden />
        <span className="line-clamp-2 text-center leading-tight">
          {image.name ?? placeholderLabel}
        </span>
      </div>
    </div>
  );
}

/** Pre-token-arrival placeholder: three bouncing dots. */
function TypingDots() {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t("message.assistantTyping")}
      className="inline-flex items-center gap-1 py-1"
    >
      <Dot delay="0ms" />
      <Dot delay="150ms" />
      <Dot delay="300ms" />
    </span>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      style={{ animationDelay: delay }}
      className={cn(
        "inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/60",
        "animate-bounce",
      )}
    />
  );
}

/** L→R sheen on the glyphs themselves; inactive labels stay solid muted text. */
export function StreamingLabelSheen({
  children,
  active,
  className,
}: {
  children: ReactNode;
  active: boolean;
  className?: string;
}) {
  const sheenText =
    typeof children === "string" || typeof children === "number"
      ? String(children)
      : undefined;
  return (
    <span className={cn("block min-w-0 overflow-hidden py-px", className)}>
      <span
        data-sheen-text={active ? sheenText : undefined}
        className={cn(
          "block w-fit max-w-full truncate font-medium leading-normal",
          active ? "streaming-text-sheen" : "text-muted-foreground",
        )}
      >
        {children}
      </span>
    </span>
  );
}

interface ReasoningBubbleProps {
  text: string;
  streaming: boolean;
  hasBodyBelow: boolean;
  /** When true, skip the slide-in wrapper (used inside ``AgentActivityCluster``). */
  embeddedInCluster?: boolean;
  onOpenFilePreview?: (path: string) => void;
}

/**
 * Subordinate "thinking" trace shown above an assistant turn.
 *
 * Lifecycle:
 *   - While ``streaming`` is true (``reasoning_delta`` frames still arriving),
 *     the bubble defaults to open and the header shows a sheen + pulse so
 *     the user sees the model "thinking out loud" in real time.
 *   - Expanded reasoning uses the same Markdown pipeline as assistant replies
 *     (deferred while streaming to reduce parser thrash), so headings and
 *     emphasis render instead of leaking raw ``###`` / ``**``.
 *   - On ``reasoning_end`` the bubble auto-collapses for prose density —
 *     the user can re-expand to inspect the chain of thought. The local
 *     toggle persists once the user interacts.
 */
export function ReasoningBubble({
  text,
  streaming,
  hasBodyBelow,
  embeddedInCluster = false,
  onOpenFilePreview,
}: ReasoningBubbleProps) {
  const { t } = useTranslation();
  const [userToggled, setUserToggled] = useState(false);
  const [openLocal, setOpenLocal] = useState(true);
  const open = userToggled ? openLocal : streaming;
  const onToggle = () => {
    setUserToggled(true);
    setOpenLocal((v) => (userToggled ? !v : !open));
  };
  useEffect(() => {
    if (open && text.length > 0) {
      preloadMarkdownText();
    }
  }, [open, text.length]);
  return (
    <div
      className={cn(
        "w-full",
        !embeddedInCluster && "animate-in fade-in-0 slide-in-from-top-1 duration-200",
        hasBodyBelow && "mb-2",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={open}
        aria-live={streaming ? "polite" : undefined}
      >
        <Sparkles
          className={cn("h-3.5 w-3.5", streaming && "animate-pulse")}
          aria-hidden
        />
        <StreamingLabelSheen active={streaming} className="min-w-0 flex-1 text-left">
          {streaming
            ? t("message.reasoningStreaming", { defaultValue: "Thinking…" })
            : t("message.reasoning", { defaultValue: "Thinking" })}
        </StreamingLabelSheen>
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform duration-200",
            open && "rotate-90",
          )}
        />
      </button>
      {open && text.length > 0 && (
        <div
          className={cn(
            "mt-1 min-w-0 border-l border-muted-foreground/20 pl-3",
            !embeddedInCluster && "animate-in fade-in-0 slide-in-from-top-1 duration-200",
          )}
        >
          <MarkdownText
            streaming={streaming}
            onOpenFilePreview={onOpenFilePreview}
            className={cn(
              "text-[12.5px] italic text-muted-foreground/88",
              "prose-p:my-1.5 prose-li:my-0.5",
              "prose-headings:mt-2 prose-headings:mb-1 prose-headings:font-medium",
              "prose-headings:text-muted-foreground/92 prose-strong:text-muted-foreground",
              "prose-h1:text-[15px] prose-h2:text-[13.5px] prose-h3:text-[12.5px] prose-h4:text-[12px]",
              "prose-a:text-brand prose-a:underline hover:prose-a:text-brand/80",
              "prose-code:text-[0.92em]",
            )}
          >
            {text}
          </MarkdownText>
        </div>
      )}
    </div>
  );
}

interface TraceGroupProps {
  message: UIMessage;
  animClass: string;
}

/**
 * Collapsible group of tool-call / progress breadcrumbs. Defaults to
 * collapsed because tool traces are supporting evidence, not the answer.
 * A single click expands the exact calls when the user wants details.
 */
export function TraceGroup({ message, animClass }: TraceGroupProps) {
  const { t } = useTranslation();
  const lines = message.traces ?? [message.content];
  const count = lines.length;
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("w-full", animClass)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={open}
      >
        <Wrench className="h-3.5 w-3.5" aria-hidden />
        <span className="font-medium">
          {count === 1
            ? t("message.toolSingle")
            : t("message.toolMany", { count })}
        </span>
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform duration-200",
            open && "rotate-90",
          )}
        />
      </button>
      {open && (
        <ul
          className={cn(
            "mt-1 space-y-0.5 border-l border-muted-foreground/20 pl-3",
            "animate-in fade-in-0 slide-in-from-top-1 duration-200",
          )}
        >
          {lines.map((line, i) => (
            <li
              key={i}
              className="whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed text-muted-foreground/90"
            >
              {line}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
