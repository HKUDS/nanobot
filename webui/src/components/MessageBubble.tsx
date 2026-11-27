import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Activity, Check, ChevronRight, CircleAlert, Copy, Quote, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DisclosureContent } from "@/components/ui/disclosure";
import { LoadingRing } from "@/components/ui/loading-ring";

import { AttachmentTile } from "@/components/AttachmentTile";
import { CodeBlock } from "@/components/CodeBlock";
import { SessionHandleLabel } from "@/components/SessionHandleLabel";
import { FallbackResponseSources } from "@/components/ResponseSourceBadge";
import { ImageGallery } from "@/components/ImageGallery";
import { InlineImageProvider, useInlineImages } from "@/components/InlineImageContext";
import { INLINE_REFERENCE_HIGHLIGHT_COLOR, InlineTokenHighlight } from "@/components/InlineTokenHighlight";
import { MarkdownText } from "@/components/MarkdownText";
import { PendingEdgeOverlay, usePendingEdgeState, type PendingEdgeState } from "@/components/PendingEdgeOverlay";
import { SlashCommandText } from "@/components/SlashCommandText";
import { DiffViewportContext } from "@/components/thread/activity/DiffViewportContext";
import { ReasoningRow } from "@/components/thread/activity/ReasoningRow";
import { StreamingLabelSheen } from "@/components/ui/streaming-label-sheen";
import { ContextCompactionNotice } from "@/components/thread/ContextCompactionNotice";
import { UserMessageText } from "@/components/UserMessageText";
import { HoverHint } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { copyTextToClipboard } from "@/lib/clipboard";
import { fmtDateTime, formatMessageEndTime, formatMessageHoverTime } from "@/lib/format-time";
import { toMediaAttachment } from "@/lib/media";
import { matchingSlashCommand } from "@/lib/slash-command";
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
  temporary?: boolean;
  cliApps?: CliAppInfo[];
  mcpPresets?: McpPresetInfo[];
  slashCommands?: SlashCommand[];
  onOpenFilePreview?: (path: string) => void;
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
  const showToast = useToast();
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
      if (!ok) {
        showToast?.({ message: t("fileActions.failed"), tone: "error", dedupeKey: "copy-failed" });
        return;
      }
      setCopied(true);
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => {
        setCopied(false);
        copyResetRef.current = null;
      }, 1_500);
    });
  }, [content, showToast, t]);

  const label = copied ? t("message.copiedReply") : t("message.copyReply");
  return { copied, label, onCopy };
}

export function MessageCopyButton({ message, className }: { message: UIMessage; className?: string }) {
  const content = message.content;
  const { copied, label, onCopy } = useMessageCopy(content);
  if (!content.trim()) return null;
  return <HoverHint content={label} side="top" align="center"><button type="button" data-message-block-copy-action
    onClick={onCopy} aria-label={label}
    className={cn(
      "inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] items-center justify-center rounded-control",
      "text-muted-foreground transition-[color] hover:text-foreground",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transform-none",
      className,
    )}>
    {copied ? <Check className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />
      : <Copy className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />}
  </button></HoverHint>;
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
  sheet?: boolean;
}

export function MessageBlockMenuActions({
  message,
  isTurnStreaming = false,
  onForkFromHere,
  activity,
  sheet = false,
}: MessageBlockMenuActionsProps) {
  const { t } = useTranslation();
  const content = message.content;
  const hasText = content.trim().length > 0;
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
    ? (sheet ? formatMessageEndTime(timestamp) : formatMessageHoverTime(timestamp))
    : "";
  const automationSourceLabel = message.role === "assistant"
    && ["cron", "local_trigger", "trigger"].includes(message.source?.kind ?? "")
    ? message.source?.label?.trim() || t("message.automationSourceFallback")
    : "";

  const fallbackSources = (
    <FallbackResponseSources
      sources={message.role === "assistant" ? message.responseSources : undefined}
      className={cn("min-h-[var(--message-block-control-size)] gap-1", !sheet && "min-w-8 max-w-24 flex-nowrap overflow-x-auto")}
      badgeClassName={cn("h-[var(--message-block-control-size)] min-h-[var(--message-block-control-size)]", !sheet && "min-w-8 gap-0.5 px-0")}
    />
  );
  const automation = automationSourceLabel && `${t("message.automationTriggered")} ${automationSourceLabel}`;
  const time = timestampLabel && (
    <time data-message-timestamp data-message-hover-time={!sheet || undefined}
      data-message-created-at={message.role === "user" || undefined}
      data-assistant-completed-at={message.role === "assistant" && timestamp === message.completedAt || undefined}
      dateTime={new Date(timestamp).toISOString()} tabIndex={sheet ? undefined : 0}
      className={cn("tabular-nums", sheet ? "flex min-h-[var(--message-block-control-size)] items-center"
        : "shrink-0 rounded-mark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring")}>
      {timestampLabel}
    </time>
  );
  const activityAction = activity && (
    <button type="button" data-message-block-activity-action onClick={activity.onToggle}
      aria-expanded={activity.expanded} aria-controls={activity.controls} aria-label={activity.label}
      className={cn("inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] items-center justify-center rounded-control text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        sheet && "w-full justify-start gap-2 px-2 text-sm hover:bg-muted/70")}>
      <Activity className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
      {sheet ? activity.label : null}
    </button>
  );
  return (
    <div className={sheet ? "flex w-full flex-col gap-1" : "flex min-w-0 flex-col items-start"}>
      <div className={sheet ? "flex flex-col items-stretch gap-1" : "flex max-w-full items-center"}>
        {!sheet && hasText ? <MessageCopyButton message={message} className="shrink-0" /> : null}
        {!sheet && fallbackSources}
        {showFork ? (
          <HoverHint content={t("message.forkFromHere")}>
            <button type="button" onClick={onForkFromHere}
              aria-label={t("message.forkFromHere")}
              className={cn("inline-flex h-[var(--message-block-control-size)] w-[var(--message-block-action-width)] items-center justify-center rounded-control text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                sheet && "w-full justify-start gap-2 px-2 text-sm")}>
              <ForkArrowIcon className="h-3.5 w-3.5" />
              {sheet ? t("message.forkFromHere") : null}
            </button>
          </HoverHint>
        ) : null}
        {activityAction && !sheet ? <HoverHint content={activity.label}>{activityAction}</HoverHint> : activityAction}
      </div>
      {sheet && fallbackSources}
      {(time || automation) && (
        <div data-message-block-metadata className={cn("leading-4 text-muted-foreground", sheet
          ? "mt-0.5 w-full border-t border-border/45 px-2 pt-1 text-xs"
          : "flex max-w-full items-center gap-1 ps-[calc((var(--message-block-action-width)-0.875rem)/2)] text-[10px]")}>
          {time && !sheet ? <HoverHint content={fmtDateTime(timestamp)}>{time}</HoverHint> : time}
          {automation && (sheet
            ? <span data-automation-trigger className="flex min-h-[var(--message-block-control-size)] items-center break-words">{automation}</span>
            : <HoverHint content={automationSourceLabel}>
                <span data-automation-trigger tabIndex={0} className="truncate rounded-mark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("message.automationTriggered")}</span>
              </HoverHint>)}
        </div>
      )}
    </div>
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
  errorDetail,
}: {
  status: MessageDeliveryStatus | undefined;
  errorKind: MessageDeliveryErrorKind | undefined;
  errorDetail?: string;
}) {
  const { t } = useTranslation();
  if (status !== "failed") return null;

  if (errorDetail === "temporary_chat_command_rejected") {
    return <span role="alert" className="text-[12px] text-destructive">{t("errors.turnRejected.temporaryCommand")}</span>;
  }

  const label = t("message.delivery.failed");
  const { title, body } = deliveryErrorCopy(errorKind, t);
  return (
    <>
      <HoverHint
        side="top"
        align="end"
        contentClassName="max-w-72 px-3 py-2.5 text-left"
        content={<>
          <p className="font-medium text-popover-foreground">{title}</p>
          <p className="mt-1 leading-relaxed text-muted-foreground">{body}</p>
        </>}
      >
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
      </HoverHint>
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
  const handleName = `@${handle.name}`;

  return (
    <div
      data-session-message
      className="group relative mr-auto w-fit min-w-0 max-w-[min(85%,36rem)] text-reading"
    >
      <div className="mb-1.5 flex items-center px-4 text-[12px] text-muted-foreground">
        <SessionHandleLabel id={handle.id}>{handleName}</SessionHandleLabel>
      </div>
      <div data-theme-surface className="relative min-w-0 rounded-floating bg-secondary/70 px-4 py-2">
        {contextMenu}
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
  const { edgeState, completeSeal } = usePendingEdgeState(
    message.id,
    message.role === "user" ? message.processingStatus : undefined,
    temporary || message.role !== "user",
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
    const isSending = message.deliveryStatus === "sending";
    const isFailed = message.deliveryStatus === "failed";
    const processingStatus = message.processingStatus;
    const showProcessingStatus = !temporary && processingStatus === "pending";
    const mediaEdgeState: PendingEdgeState = !hasText ? edgeState : "solid";
    const mediaSealEnd = !hasText ? completeSeal : undefined;
    const userMedia = hasImages
      ? <ImageGallery images={images} align="right" size="compact" edgeState={mediaEdgeState} onSealEnd={mediaSealEnd} />
      : hasMedia
        ? <MessageMedia media={media} align="right" pending={isSending} edgeState={mediaEdgeState} onSealEnd={mediaSealEnd} />
        : null;
    const sendingIndicator = isSending ? (
      <span
        aria-hidden="true"
        data-sending-indicator
        className="user-message-sending-indicator pointer-events-none absolute right-full top-1/2 mr-2 -translate-y-1/2 text-muted-foreground/65"
      >
        <LoadingRing className="size-3.5" strokeWidth="2.4" />
      </span>
    ) : null;
    const quotedContext = parsedMessage.quotedContext;
    const slashCommand = matchingSlashCommand(userContent, slashCommands);
    const bangPrefix = /^(\s*)!/.exec(userContent);
    const messageText = bangPrefix ? (
      <>
        {bangPrefix[1]}
        <InlineTokenHighlight testId="message-shell-prefix" className="font-normal" color={INLINE_REFERENCE_HIGHLIGHT_COLOR}>
          <span className="opacity-90">!</span>
        </InlineTokenHighlight>
        {userContent.slice(bangPrefix[0].length)}
      </>
    ) : slashCommand ? (
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
        className="group relative ml-auto flex w-fit max-w-[min(85%,36rem)] flex-col items-end gap-1.5"
      >
        {!hasText ? contextMenu : null}
        {!hasText ? sendingIndicator : null}
        {userMedia ? (
          !hasText ? (
            <div className={cn("transition-opacity duration-200 ease-out motion-reduce:transition-none", isSending && "opacity-65")}>
              {userMedia}
            </div>
          ) : userMedia
        ) : null}
        {quotedContext ? (
          <UserQuotedContext
            text={quotedContext}
            label={t("thread.composer.quotedContext")}
          />
        ) : null}
        {hasText ? (
          <UserTextBubble
            messageId={message.id}
            contentKey={userContent}
            temporary={temporary}
            sendingIndicator={sendingIndicator}
            showProcessingStatus={showProcessingStatus}
            edgeState={edgeState}
            onSealEnd={completeSeal}
            contextMenu={contextMenu}
          >
            {messageText}
          </UserTextBubble>
        ) : null}
        {isSending ? (
          <span role="status" className="sr-only">
            {t("message.delivery.sending")}
          </span>
        ) : !isFailed && showProcessingStatus ? (
          <span role="status" className="sr-only">
            {t("message.delivery.waiting")}
          </span>
        ) : null}
        {isFailed ? (
            <div className="flex min-h-6 items-center justify-end gap-1.5 text-muted-foreground">
              <UserDeliveryStatus
                status={message.deliveryStatus}
                errorKind={message.deliveryErrorKind}
                errorDetail={message.deliveryErrorDetail}
              />
            </div>
        ) : null}
      </div>
    );
  }

  const assistantContent = message.content;
  const empty = assistantContent.trim().length === 0;
  const media = message.media ?? [];
  const reasoning = message.role === "assistant" ? message.reasoning ?? "" : "";
  const reasoningStreaming = !!(message.role === "assistant" && message.reasoningStreaming);
  const hasReasoning = reasoning.length > 0 || reasoningStreaming;
  return (
    <div
      data-assistant-message
      className="group/assistant relative w-full text-reading"
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
            {message.renderAs === "text" ? (
              <CodeBlock language="text" code={assistantContent} highlight={false} ansi={false} />
            ) : (
              /* A mode switch rebuilds Streamdown's subtree and moves the scroll anchor. */
              <MarkdownText
                streaming={!!message.isStreaming}
                preserveStreamingLayout
                onOpenFilePreview={onOpenFilePreview}
              >
                {assistantContent}
              </MarkdownText>
            )}
          </div>
          {media.length > 0 ? <MessageMedia media={media} align="left" /> : null}
        </InlineImageProvider>
      )}
    </div>
  );
}

const USER_MESSAGE_COLLAPSE_THRESHOLD_RATIO = 0.5;
const USER_MESSAGE_COLLAPSED_HEIGHT_RATIO = 0.38;
const MIN_USER_MESSAGE_COLLAPSE_THRESHOLD_PX = 200;
const MIN_USER_MESSAGE_COLLAPSED_BUBBLE_PX = 160;
const MIN_USER_MESSAGE_COLLAPSED_TEXT_PX = 96;
const DEFAULT_COLLAPSIBLE_PADDING_BOTTOM_PX = 40;
const COLLAPSE_SCROLL_TOP_INSET_PX = 48;

interface UserTextCollapseLayout {
  collapsible: boolean;
  fullTextHeight: number;
  collapsedTextHeight: number;
}

interface UserTextBubbleProps {
  messageId: string;
  contentKey: string;
  temporary: boolean;
  sendingIndicator: ReactNode;
  showProcessingStatus: boolean;
  edgeState: PendingEdgeState;
  onSealEnd: () => void;
  contextMenu?: ReactNode;
  children: ReactNode;
}

function UserTextBubble({
  messageId,
  contentKey,
  temporary,
  sendingIndicator,
  showProcessingStatus,
  edgeState,
  onSealEnd,
  contextMenu,
  children,
}: UserTextBubbleProps) {
  const { t } = useTranslation();
  const viewport = useContext(DiffViewportContext);
  const bubbleRef = useRef<HTMLParagraphElement>(null);
  const contentRef = useRef<HTMLSpanElement>(null);
  const contentId = useId();
  const [layout, setLayout] = useState<UserTextCollapseLayout | null>(null);
  const [expandedForId, setExpandedForId] = useState<string | null>(null);
  const expanded = expandedForId === messageId;
  const isCollapsible = layout?.collapsible ?? false;
  const isCollapsed = isCollapsible && !expanded;

  useLayoutEffect(() => {
    const bubble = bubbleRef.current;
    if (!bubble) return;
    const scroller = viewport?.scroller.current ?? null;

    const measure = () => {
      const currentBubble = bubbleRef.current;
      if (!currentBubble) return;
      const scrollerHeight = scroller?.clientHeight ?? 0;
      const referenceHeight = scrollerHeight > 0 ? scrollerHeight : window.innerHeight;
      if (!Number.isFinite(referenceHeight) || referenceHeight <= 0) return;

      const style = getComputedStyle(currentBubble);
      const paddingTop = Number.parseFloat(style.paddingTop) || 0;
      const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;
      const normalPaddingY = paddingTop * 2;
      const content = contentRef.current;
      const fullTextHeight = content
        ? content.scrollHeight
        : Math.max(0, currentBubble.scrollHeight - paddingTop - paddingBottom);
      if (fullTextHeight <= 0) return;

      const naturalBubbleHeight = fullTextHeight + normalPaddingY;
      const collapseThreshold = Math.max(
        MIN_USER_MESSAGE_COLLAPSE_THRESHOLD_PX,
        Math.round(referenceHeight * USER_MESSAGE_COLLAPSE_THRESHOLD_RATIO),
      );
      const collapsible = naturalBubbleHeight > collapseThreshold;
      const collapsedPaddingY = content
        ? paddingTop + paddingBottom
        : paddingTop + DEFAULT_COLLAPSIBLE_PADDING_BOTTOM_PX;
      const targetBubbleHeight = Math.max(
        MIN_USER_MESSAGE_COLLAPSED_BUBBLE_PX,
        Math.round(referenceHeight * USER_MESSAGE_COLLAPSED_HEIGHT_RATIO),
      );
      const collapsedTextHeight = Math.min(
        fullTextHeight,
        Math.max(MIN_USER_MESSAGE_COLLAPSED_TEXT_PX, targetBubbleHeight - collapsedPaddingY),
      );

      setLayout((current) => (
        current?.collapsible === collapsible
        && current.fullTextHeight === fullTextHeight
        && current.collapsedTextHeight === collapsedTextHeight
          ? current
          : { collapsible, fullTextHeight, collapsedTextHeight }
      ));
    };

    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(contentRef.current ?? bubble);
    if (scroller) observer?.observe(scroller);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [contentKey, isCollapsible, messageId, viewport]);

  const toggleCollapsed = useCallback(() => {
    if (expanded) {
      const bubble = bubbleRef.current;
      if (bubble) {
        const scroller = viewport?.scroller.current ?? null;
        if (scroller) {
          const scrollerRect = scroller.getBoundingClientRect();
          const bubbleRect = bubble.getBoundingClientRect();
          if (bubbleRect.top < scrollerRect.top + COLLAPSE_SCROLL_TOP_INSET_PX) {
            const targetTop = Math.max(
              0,
              scroller.scrollTop + (bubbleRect.top - scrollerRect.top) - COLLAPSE_SCROLL_TOP_INSET_PX,
            );
            scroller.scrollTo({ top: targetTop, behavior: "auto" });
          }
        } else if (bubble.getBoundingClientRect().top < 16) {
          bubble.scrollIntoView({ block: "nearest" });
        }
      }
      setExpandedForId(null);
      return;
    }
    setExpandedForId(messageId);
  }, [expanded, messageId, viewport]);

  const clipHeight = layout
    ? (isCollapsed ? layout.collapsedTextHeight : layout.fullTextHeight)
    : undefined;

  return (
    <div
      data-user-text-bubble
      data-user-message-collapsible={isCollapsible ? "true" : undefined}
      data-user-message-collapsed={isCollapsed ? "true" : undefined}
      className="relative ml-auto w-fit max-w-full min-w-0"
    >
      {contextMenu}
      {sendingIndicator}
      <p
        ref={bubbleRef}
        id={isCollapsible ? contentId : undefined}
        data-theme-surface
        data-temporary-message={temporary ? "true" : undefined}
        data-pending-edge={edgeState !== "solid" ? edgeState : undefined}
        className={cn(
          "relative ml-auto w-fit max-w-full min-w-0 rounded-floating px-4 py-2",
          "text-left text-reading whitespace-pre-wrap [overflow-wrap:anywhere]",
          temporary
            ? "border border-dashed border-muted-foreground/40 bg-transparent"
            : "user-message-surface bg-secondary/70",
          showProcessingStatus && "user-message-surface-dashed",
          "transition-opacity duration-200 ease-out motion-reduce:transition-none",
          sendingIndicator && "opacity-65",
          isCollapsible && "user-message-collapsible",
        )}
      >
        <PendingEdgeOverlay state={edgeState} onSealEnd={onSealEnd} />
        {isCollapsible ? (
          <span
            data-user-message-clip
            data-state={isCollapsed ? "closed" : "open"}
            className={cn(
              "user-message-collapsible-body block overflow-hidden",
              isCollapsed && "user-message-collapsible-masked",
            )}
            style={clipHeight !== undefined ? { height: clipHeight } : undefined}
          >
            <span ref={contentRef} className="block">
              {children}
            </span>
          </span>
        ) : (
          children
        )}
      </p>
      {isCollapsible ? (
        <>
          <div
            data-user-message-stack
            data-state={isCollapsed ? "visible" : "hidden"}
            data-temporary={temporary ? "true" : undefined}
            aria-hidden="true"
            className="user-message-stack pointer-events-none flex flex-col"
          >
            <span className="user-message-stack-sheet user-message-stack-sheet-first" />
            <span className="user-message-stack-sheet user-message-stack-sheet-second" />
          </div>
          <div
            data-user-message-toggle-bar
            className="user-message-toggle-bar pointer-events-none absolute inset-x-0 z-[2] flex items-center justify-center px-3 pb-1.5 pt-1"
          >
            <button
              type="button"
              data-thread-disclosure=""
              data-user-message-toggle
              aria-expanded={!isCollapsed}
              aria-controls={contentId}
              onClick={toggleCollapsed}
              className={cn(
                "pointer-events-auto touch-target inline-flex h-7 items-center rounded-full px-3.5",
                "text-ui-label text-muted-foreground transition-colors",
                "hover:bg-foreground/[0.06] hover:text-foreground dark:hover:bg-foreground/[0.09]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
            >
              {isCollapsed ? t("message.expandUserMessage") : t("message.collapseUserMessage")}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

function UserQuotedContext({ text, label }: { text: string; label: string }) {
  return (
    <blockquote
      data-theme-surface
      data-theme-ink
      className={cn(
        "ml-auto flex w-fit max-w-full min-w-0 items-start gap-2 rounded-floating",
        "border border-border/60 bg-muted/35 px-3 py-2 text-left text-muted-foreground",
      )}
      aria-label={label}
    >
      <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p className="min-w-0 line-clamp-3 whitespace-pre-wrap text-reading-small [overflow-wrap:anywhere]">
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
  pending = false,
  edgeState = "solid",
  onSealEnd,
}: {
  media: UIMediaAttachment[];
  align: "left" | "right";
  pending?: boolean;
  edgeState?: PendingEdgeState;
  onSealEnd?: () => void;
}) {
  const inlineImages = useInlineImages();
  if (media.length === 0) return null;
  const images: UIImage[] = [];
  const seen = new Set<string>();
  const videos: UIMediaAttachment[] = [];
  const files: UIMediaAttachment[] = [];
  for (const item of media) {
    const normalized = toMediaAttachment(item);
    if (normalized.kind === "image") {
      if (normalized.url && (inlineImages.has(normalized.url) || seen.has(normalized.url))) continue;
      if (normalized.url) seen.add(normalized.url);
      images.push({ url: normalized.url, name: normalized.name });
    } else if (normalized.kind === "video") {
      videos.push(normalized);
    } else {
      files.push(normalized);
    }
  }
  if (images.length === 0 && videos.length === 0 && files.length === 0) return null;
  const attachSealToImages = images.length > 0;
  const attachSealToVideos = !attachSealToImages && videos.length > 0;
  const attachSealToFiles = !attachSealToImages && !attachSealToVideos;

  return (
    <div
      className={cn(
        "mt-2 flex min-w-0 max-w-full flex-col gap-2",
        align === "right" ? "items-end" : "items-start",
      )}
    >
      {images.length > 0 ? (
        <ImageGallery
          images={images}
          align={align}
          size={align === "left" ? "large" : "compact"}
          edgeState={edgeState}
          onSealEnd={attachSealToImages ? onSealEnd : undefined}
        />
      ) : null}
      {videos.map((item, i) => (
        <AttachmentTile
          key={`video-${i}`}
          attachment={item}
          pending={pending}
          edgeState={edgeState}
          onSealEnd={attachSealToVideos && i === 0 ? onSealEnd : undefined}
          className="my-0"
        />
      ))}
      {files.length > 0 ? (
        <div className={cn("flex w-full min-w-0 flex-wrap items-start gap-2", align === "right" && "justify-end")}>
          {files.map((item, i) => (
            <AttachmentTile
              key={`file-${i}`}
              attachment={item}
              pending={pending}
              edgeState={edgeState}
              onSealEnd={attachSealToFiles && i === 0 ? onSealEnd : undefined}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

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
