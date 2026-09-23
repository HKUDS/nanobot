import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Activity,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Copy,
  Quote,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { DisclosureContent } from "@/components/ui/disclosure";

import { AttachmentTile } from "@/components/AttachmentTile";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import { FallbackResponseSources } from "@/components/ResponseSourceBadge";
import { ImageGallery } from "@/components/ImageGallery";
import { InlineImageProvider, useInlineImages } from "@/components/InlineImageContext";
import { MarkdownText } from "@/components/MarkdownText";
import { SlashCommandText } from "@/components/SlashCommandText";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import { ContextCompactionNotice } from "@/components/thread/ContextCompactionNotice";
import { UserMessageText } from "@/components/UserMessageText";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatMessageEndTime } from "@/lib/format";
import { toMediaAttachment } from "@/lib/media";
import { matchingSlashCommand } from "@/lib/slash-command";
import { sessionHandleColor } from "@/lib/session-handle";
import { parseQuotedUserMessage } from "@/lib/user-message-quote";
import type {
  CliAppInfo,
  McpPresetInfo,
  SlashCommand,
  UICliAppAttachment,
  UIMcpPresetAttachment,
  UIImage,
  UIMediaAttachment,
  UIMessage,
  MessageDeliveryErrorKind,
  MessageDeliveryStatus,
} from "@/lib/types";

interface MessageBubbleProps {
  message: UIMessage;
  /** Give temporary-chat user turns the dashed private-mode treatment. */
  temporary?: boolean;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  slashCommands?: SlashCommand[];
  onOpenFilePreview?: (path: string) => void;
  /** Context-menu trigger positioned against this message's visual block. */
  contextMenu?: ReactNode;
}

function ForkArrowIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M16 3h5v5" />
      <path d="M8 3H3v5" />
      <path d="m21 3-7.536 7.536A5 5 0 0 0 12 14.07V21" />
      <path d="m3 3 7.536 7.536A5 5 0 0 1 12 14.07V15" />
    </svg>
  );
}

function useMessageCopy(content: string) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copyResetRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
    };
  }, []);

  const onCopy = useCallback(() => {
    void copyTextToClipboard(content).then((ok) => {
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
  }, [content]);

  const label = copied ? t("message.copiedReply") : t("message.copyReply");
  return { copied, label, onCopy };
}

interface MessageBlockMenuActivity {
  label: string;
  expanded: boolean;
  controls: string;
  onToggle: () => void;
}

interface MessageBlockMenuActionsProps {
  message: UIMessage;
  isTurnStreaming?: boolean;
  onForkFromHere?: () => void;
  activity?: MessageBlockMenuActivity;
}

/** Actions and metadata shown after opening a visual message block's context panel. */
export function MessageBlockMenuActions({
  message,
  isTurnStreaming = false,
  onForkFromHere,
  activity,
}: MessageBlockMenuActionsProps) {
  const { t } = useTranslation();
  const content = message.role === "assistant"
    ? message.compactReply === "empty"
      ? t("thread.compaction.empty")
      : message.compactReply === "failed"
        ? t("thread.compaction.failed")
        : message.content
    : message.content;
  const hasText = content.trim().length > 0;
  const { copied, label: copyLabel, onCopy } = useMessageCopy(content);
  const showFork = message.role === "assistant"
    && !message.isStreaming
    && !isTurnStreaming
    && hasText
    && onForkFromHere !== undefined;
  const timestamp = message.role === "assistant"
    && typeof message.completedAt === "number"
    && Number.isFinite(message.completedAt)
    ? message.completedAt
    : message.createdAt;
  const timestampLabel = typeof timestamp === "number" && Number.isFinite(timestamp)
    ? formatMessageEndTime(timestamp)
    : "";
  const automationSourceLabel = message.role === "assistant"
    && ["cron", "local_trigger", "trigger"].includes(message.source?.kind ?? "")
    ? message.source?.label?.trim() || t("message.automationSourceFallback")
    : "";

  return (
    <TooltipProvider>
      <div
        data-message-block-menu-actions
        className="flex w-max max-w-full flex-col items-start gap-1"
      >
        {hasText || showFork || activity ? (
          <div
            data-message-block-toolbar
            className="flex w-full flex-wrap items-center gap-x-1 gap-y-1"
          >
            {hasText || showFork ? (
              <div className="flex min-h-[var(--message-block-control-size)] items-center gap-0.5">
                {hasText ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        data-message-block-copy-action
                        data-assistant-copy-action={message.role === "assistant" || undefined}
                        onClick={onCopy}
                        aria-label={copyLabel}
                        className={cn(
                          "inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] items-center justify-center rounded-control",
                          "text-muted-foreground transition-[color,background-color,scale]",
                          "hover:bg-muted/70 hover:text-foreground active:scale-[0.96]",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          "motion-reduce:transform-none",
                        )}
                      >
                        {copied ? (
                          <Check
                            className="h-3.5 w-3.5 -translate-x-px"
                            strokeWidth={1.75}
                            aria-hidden
                          />
                        ) : (
                          <Copy
                            className="h-3.5 w-3.5 -translate-x-px"
                            strokeWidth={1.75}
                            aria-hidden
                          />
                        )}
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="center">{copyLabel}</TooltipContent>
                  </Tooltip>
                ) : null}
                {showFork ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        data-message-block-fork-action
                        data-assistant-fork-action
                        onClick={onForkFromHere}
                        aria-label={t("message.forkFromHere")}
                        className={cn(
                          "inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] items-center justify-center rounded-control",
                          "text-muted-foreground transition-[color,background-color,scale]",
                          "hover:bg-muted/70 hover:text-foreground active:scale-[0.96]",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          "motion-reduce:transform-none",
                        )}
                      >
                        <ForkArrowIcon className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="center">
                      {t("message.forkFromHere")}
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </div>
            ) : null}
            {activity ? (
              <button
                type="button"
                data-message-block-activity-action
                onClick={activity.onToggle}
                aria-expanded={activity.expanded}
                aria-controls={activity.controls}
                className={cn(
                  "group inline-flex min-h-[var(--message-block-control-size)] self-start items-center gap-1.5 whitespace-nowrap",
                  "text-start text-[11px] leading-4",
                  "text-muted-foreground transition-colors hover:text-foreground",
                  "focus-visible:outline-none",
                )}
              >
                <span
                  data-message-block-activity-icon
                  className={cn(
                    "inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] shrink-0 items-center justify-center rounded-control",
                    "transition-[background-color,box-shadow,scale]",
                    "group-hover:bg-muted/70 group-active:scale-[0.96]",
                    "group-focus-visible:ring-2 group-focus-visible:ring-ring",
                    "motion-reduce:transform-none",
                  )}
                >
                  <Activity className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
                </span>
                <span>{activity.label}</span>
              </button>
            ) : null}
          </div>
        ) : null}
        <FallbackResponseSources
          sources={message.role === "assistant" ? message.responseSources : undefined}
          className="min-h-[var(--message-block-control-size)] gap-1"
          badgeClassName="h-[var(--message-block-control-size)] min-h-[var(--message-block-control-size)]"
        />
        {timestampLabel || automationSourceLabel ? (
          <div
            data-message-block-metadata
            className="mt-0.5 w-full border-t border-border/45 px-1.5 pt-1 text-[10px] leading-4 text-muted-foreground/45"
          >
            {timestampLabel ? (
              <time
                data-message-timestamp
                data-message-created-at={message.role === "user" || undefined}
                data-assistant-completed-at={
                  message.role === "assistant" && timestamp === message.completedAt || undefined
                }
                dateTime={new Date(timestamp).toISOString()}
                className="flex min-h-[var(--message-block-control-size)] items-center tabular-nums"
              >
                {timestampLabel}
              </time>
            ) : null}
            {automationSourceLabel ? (
              <span
                data-automation-trigger
                className="flex min-h-[var(--message-block-control-size)] items-center break-words"
              >
                {t("message.automationTriggered")} · {automationSourceLabel}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </TooltipProvider>
  );
}

function deliveryErrorCopy(
  kind: MessageDeliveryErrorKind | undefined,
  t: (key: string) => string,
): { title: string; body: string } {
  switch (kind) {
    case "message_too_big":
      return {
        title: t("errors.messageTooBig.title"),
        body: t("errors.messageTooBig.body"),
      };
    case "workspace_scope_rejected":
      return {
        title: t("errors.workspaceScopeRejected.title"),
        body: t("errors.workspaceScopeRejected.body"),
      };
    case "turn_rejected":
    case undefined:
      return {
        title: t("errors.turnRejected.title"),
        body: t("errors.turnRejected.body"),
      };
    default: {
      const _exhaustive: never = kind;
      return { title: String(_exhaustive), body: "" };
    }
  }
}

function UserDeliveryStatus({
  status,
  errorKind,
}: {
  status: MessageDeliveryStatus | undefined;
  errorKind: MessageDeliveryErrorKind | undefined;
}) {
  const { t } = useTranslation();
  if (status !== "sending" && status !== "failed") return null;
  if (status === "sending") {
    return (
      <span
        role="status"
        className="inline-flex items-center gap-1 text-[12px] leading-none text-muted-foreground"
      >
        <Clock3 className="h-3.5 w-3.5" aria-hidden />
        {t("message.delivery.sending")}
      </span>
    );
  }

  const label = t("message.delivery.failed");
  const { title, body } = deliveryErrorCopy(errorKind, t);
  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`${label}: ${title}`}
            className={cn(
              "inline-flex items-center gap-1 rounded-sm text-[12px] leading-none",
              "text-destructive/80 transition-colors hover:text-destructive",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "dark:text-red-400/80 dark:hover:text-red-400",
            )}
          >
            <CircleAlert className="h-3.5 w-3.5" aria-hidden />
            {label}
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="end"
          className="max-w-72 px-3 py-2.5 text-left"
        >
          <p className="font-medium text-popover-foreground">{title}</p>
          <p className="mt-1 leading-relaxed text-muted-foreground">{body}</p>
        </TooltipContent>
      </Tooltip>
      <span role="alert" aria-live="assertive" className="sr-only">
        {title}. {body}
      </span>
    </>
  );
}

function IncomingSessionMessage({
  message,
  contextMenu,
  onOpenFilePreview,
}: {
  message: UIMessage;
  contextMenu?: ReactNode;
  onOpenFilePreview?: (path: string) => void;
}) {
  const handle = message.sessionMessage!.session;
  const color = sessionHandleColor(handle.id);
  const handleName = `@${handle.name}`;

  return (
    <div
      data-session-message
      className="group relative w-full text-[15px]"
      style={{ lineHeight: "var(--cjk-line-height)" }}
    >
      {contextMenu}
      <div
        className="min-w-0 rounded-es-[16px] border-s-2 bg-background pb-1 ps-2.5"
        style={{ borderInlineStartColor: color }}
      >
        <div className="mb-1.5 flex items-center text-[12px] text-muted-foreground">
          <SessionHandleLabel id={handle.id}>{handleName}</SessionHandleLabel>
        </div>
        <div data-assistant-selectable="true" className="min-w-0">
          <MarkdownText
            preserveStreamingLayout
            onOpenFilePreview={onOpenFilePreview}
          >
            {message.content}
          </MarkdownText>
        </div>
      </div>
    </div>
  );
}

/** Render user turns as compact bubbles and assistant turns as document-like prose. */
export function MessageBubble({
  message,
  temporary = false,
  cliApps = [],
  mcpPresets = [],
  slashCommands = [],
  onOpenFilePreview,
  contextMenu,
}: MessageBubbleProps) {
  const { t } = useTranslation();
  const mentionCliApps = useMemo(
    () => mergeCliMentionApps(cliApps, message.cliApps),
    [cliApps, message.cliApps],
  );
  const mentionMcpPresets = useMemo(
    () => mergeMcpMentionPresets(mcpPresets, message.mcpPresets),
    [mcpPresets, message.mcpPresets],
  );

  if (message.kind === "compaction" && message.compaction) {
    return <ContextCompactionNotice compaction={message.compaction} />;
  }

  if (message.kind === "trace") {
    return <TraceGroup message={message} />;
  }

  if (message.role === "user" && message.sessionMessage) {
    return (
      <IncomingSessionMessage
        message={message}
        contextMenu={contextMenu}
        onOpenFilePreview={onOpenFilePreview}
      />
    );
  }

  if (message.role === "user") {
    const images = message.images ?? [];
    const media = message.media ?? [];
    const hasImages = images.length > 0;
    const hasMedia = media.length > 0;
    const parsedMessage = parseQuotedUserMessage(message.content);
    const userContent = parsedMessage.content;
    const hasText = userContent.trim().length > 0;
    const showDeliveryStatus =
      message.deliveryStatus === "sending" || message.deliveryStatus === "failed";
    const quotedContext = parsedMessage.quotedContext;
    const slashCommand = matchingSlashCommand(userContent, slashCommands);
    const messageText = slashCommand ? (
      <>
        <SlashCommandText command={slashCommand.command} />
        <UserMessageText
          text={userContent.slice(slashCommand.command.length)}
          cliApps={mentionCliApps}
          mcpPresets={mentionMcpPresets}
          sessionMentions={message.sessionMentions}
        />
      </>
    ) : (
      <UserMessageText
        text={userContent}
        cliApps={mentionCliApps}
        mcpPresets={mentionMcpPresets}
        sessionMentions={message.sessionMentions}
      />
    );
    return (
      <div
        data-user-text-bubble={hasText && !hasImages && !hasMedia && !quotedContext || undefined}
        className="group relative ml-auto flex w-fit max-w-[min(85%,36rem)] flex-col items-end gap-1.5"
      >
        {contextMenu}
        {hasImages ? <ImageGallery images={images} align="right" size="compact" /> : null}
        {!hasImages && hasMedia ? (
          <MessageMedia media={media} align="right" />
        ) : null}
        {quotedContext ? (
          <UserQuotedContext
            text={quotedContext}
            label={t("thread.composer.quotedContext")}
          />
        ) : null}
        {hasText ? (
          <p
            data-temporary-message={temporary ? "true" : undefined}
            className={cn(
              "ml-auto w-fit max-w-full min-w-0 rounded-floating px-4 py-2",
              "text-left text-[16px]/[1.75] whitespace-pre-wrap [overflow-wrap:anywhere]",
              temporary
                ? "border border-dashed border-muted-foreground/40 bg-transparent"
                : "bg-secondary/70",
            )}
          >
            {messageText}
          </p>
        ) : null}
        {showDeliveryStatus ? (
          <TooltipProvider>
            <div className="flex min-h-8 items-center justify-end gap-1.5 text-muted-foreground">
              <UserDeliveryStatus
                status={message.deliveryStatus}
                errorKind={message.deliveryErrorKind}
              />
            </div>
          </TooltipProvider>
        ) : null}
      </div>
    );
  }

  const assistantContent = message.compactReply === "empty"
    ? t("thread.compaction.empty")
    : message.compactReply === "failed"
      ? t("thread.compaction.failed")
      : message.content;
  const empty = assistantContent.trim().length === 0;
  const media = message.media ?? [];
  const reasoning = message.role === "assistant" ? message.reasoning ?? "" : "";
  const reasoningStreaming = !!(message.role === "assistant" && message.reasoningStreaming);
  const hasReasoning = reasoning.length > 0 || reasoningStreaming;
  return (
    <div
      data-assistant-message
      className="group/assistant relative w-full text-[15px]"
      style={{ lineHeight: "var(--cjk-line-height)" }}
    >
      {contextMenu}
      {hasReasoning ? (
        <ReasoningBubble
          text={reasoning}
          streaming={reasoningStreaming}
          hasBodyBelow={!empty}
        />
      ) : null}
      {empty && message.isStreaming && !hasReasoning ? (
        <ThinkingState />
      ) : empty && message.isStreaming ? null : (
        <InlineImageProvider>
          <div data-assistant-selectable={message.isStreaming ? undefined : "true"}>
            {/* A mode switch rebuilds Streamdown's subtree and moves the scroll anchor. */}
            <MarkdownText
              streaming={!!message.isStreaming}
              preserveStreamingLayout
              onOpenFilePreview={onOpenFilePreview}
            >
              {assistantContent}
            </MarkdownText>
          </div>
          {media.length > 0 ? <MessageMedia media={media} align="left" /> : null}
        </InlineImageProvider>
      )}
    </div>
  );
}

function UserQuotedContext({ text, label }: { text: string; label: string }) {
  return (
    <blockquote
      className={cn(
        "ml-auto flex w-fit max-w-full min-w-0 items-start gap-2 rounded-control",
        "border border-border/60 bg-muted/35 px-3 py-2 text-left text-muted-foreground",
      )}
      aria-label={label}
    >
      <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p className="min-w-0 line-clamp-3 whitespace-pre-wrap text-[13px]/[1.45] [overflow-wrap:anywhere]">
        {text}
      </p>
    </blockquote>
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
  const inlineImages = useInlineImages();
  if (media.length === 0) return null;
  const images: UIImage[] = [];
  const seen = new Set<string>();
  const nonImages: UIMediaAttachment[] = [];
  for (const item of media) {
    const normalized = toMediaAttachment(item);
    if (normalized.kind === "image") {
      if (normalized.url && (inlineImages.has(normalized.url) || seen.has(normalized.url))) continue;
      if (normalized.url) seen.add(normalized.url);
      images.push({ url: normalized.url, name: normalized.name });
    } else {
      nonImages.push(normalized);
    }
  }
  if (images.length === 0 && nonImages.length === 0) return null;

  return (
    <div
      className={cn(
        "mt-2 flex flex-wrap gap-2",
        align === "right" ? "justify-end" : "justify-start",
      )}
    >
      {images.length > 0 ? (
        <ImageGallery images={images} align={align} size={align === "left" ? "large" : "compact"} />
      ) : null}
      {nonImages.map((item, i) => (
        <AttachmentTile key={`${item.url ?? item.name ?? item.kind}-${i}`} attachment={item} />
      ))}
    </div>
  );
}

/** Quiet pre-token state that occupies a stable line in the answer column. */
function ThinkingState() {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t("message.assistantTyping")}
      className="inline-flex min-h-7 items-center py-1 text-[13px]"
    >
      <StreamingLabelSheen active>
        {t("message.reasoningStreaming", { defaultValue: "Thinking…" })}
      </StreamingLabelSheen>
    </span>
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
          "block w-fit max-w-full truncate pr-0.5 font-medium leading-normal",
          active ? "streaming-text-sheen after:pr-0.5" : "text-muted-foreground",
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
}

function ReasoningBubble({
  text,
  streaming,
  hasBodyBelow,
}: ReasoningBubbleProps) {
  return (
    <ReasoningRow
      text={text}
      streaming={streaming}
      className={cn(
        "animate-in fade-in-0 slide-in-from-top-1 duration-200",
        hasBodyBelow && "mb-2",
      )}
    />
  );
}

interface TraceGroupProps {
  message: UIMessage;
}

/**
 * Collapsible group of tool-call / progress breadcrumbs. Defaults to
 * collapsed because tool traces are supporting evidence, not the answer.
 * A single click expands the exact calls when the user wants details.
 */
function TraceGroup({ message }: TraceGroupProps) {
  const { t } = useTranslation();
  const lines = message.traces ?? [message.content];
  const count = lines.length;
  const [open, setOpen] = useState(false);
  const [hasOpened, setHasOpened] = useState(false);
  const releaseContent = useCallback(() => setHasOpened(false), []);
  const contentId = useId();
  return (
    <div className="w-full">
      <button
        type="button"
        onClick={() => {
          if (!open) setHasOpened(true);
          setOpen((value) => !value);
        }}
        className={cn(
          "group flex w-full items-center gap-2 rounded-md px-2 py-1.5",
          "text-xs text-muted-foreground transition-colors hover:bg-muted/45",
        )}
        aria-expanded={open}
        aria-controls={contentId}
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
            "ml-auto h-3.5 w-3.5 transition-transform duration-200 motion-reduce:transition-none",
            open && "rotate-90",
          )}
        />
      </button>
      <DisclosureContent id={contentId} open={open} onExitComplete={releaseContent}>
        {hasOpened && <ul
          className="mt-1 space-y-0.5 border-l border-muted-foreground/20 pl-3"
        >
          {lines.map((line, i) => (
            <li
              key={i}
              className="whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed text-muted-foreground/90"
            >
              {line}
            </li>
          ))}
        </ul>}
      </DisclosureContent>
    </div>
  );
}
