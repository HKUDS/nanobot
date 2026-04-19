import { useState } from "react";
import { ChevronRight, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { cn } from "@/lib/utils";
import type { UIMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: UIMessage;
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
export function MessageBubble({ message }: MessageBubbleProps) {
  const baseAnim = "animate-in fade-in-0 slide-in-from-bottom-1 duration-300";

  if (message.kind === "trace") {
    return <TraceGroup message={message} animClass={baseAnim} />;
  }

  if (message.role === "user") {
    return (
      <div
        className={cn(
          "group ml-auto flex max-w-[min(85%,36rem)] items-center gap-2",
          baseAnim,
        )}
      >
        <p
          className={cn(
            "ml-auto w-fit rounded-[18px] border border-border/60 bg-secondary/70 px-4 py-2",
            "text-right text-sm whitespace-pre-wrap break-words",
            "shadow-[0_10px_24px_-18px_rgba(0,0,0,0.55)]",
          )}
        >
          {message.content}
        </p>
      </div>
    );
  }

  const empty = message.content.trim().length === 0;
  return (
    <div className={cn("w-full text-sm leading-relaxed", baseAnim)}>
      {empty && message.isStreaming ? (
        <TypingDots />
      ) : (
        <>
          <MarkdownText>{message.content}</MarkdownText>
          {message.isStreaming && <StreamCursor />}
        </>
      )}
    </div>
  );
}

/** Blinking cursor appended at the end of streaming text. */
function StreamCursor() {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t("message.streaming")}
      className={cn(
        "ml-0.5 inline-block h-[1em] w-[3px] translate-y-[2px] align-middle",
        "rounded-sm bg-foreground/70 animate-pulse",
      )}
    />
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

interface TraceGroupProps {
  message: UIMessage;
  animClass: string;
}

/**
 * Collapsible group of tool-call / progress breadcrumbs. Defaults to
 * expanded for discoverability; a single click on the header folds the
 * group down to a one-line summary so it never dominates the thread.
 */
function TraceGroup({ message, animClass }: TraceGroupProps) {
  const { t } = useTranslation();
  const lines = message.traces ?? [message.content];
  const count = lines.length;
  const [open, setOpen] = useState(true);
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
