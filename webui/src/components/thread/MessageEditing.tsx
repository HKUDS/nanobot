import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/hover-hint";
import { useClient } from "@/providers/ClientProvider";
import { parseQuotedUserMessage } from "@/lib/user-message-quote";
import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import type { UIMessage } from "@/lib/types";

interface EditDraft {
  message: UIMessage;
  text: string;
  turnId: string;
  revision: string | null;
  needsReview: boolean;
  submitting: boolean;
  error: string | null;
}

interface EditActions {
  scope: string;
  message: UIMessage | null;
  reason: (message: UIMessage) => string | null;
  begin: (message: UIMessage) => void;
}

interface EditorContext {
  draft: EditDraft | null;
  busy: boolean;
  retryRead: () => void;
  change: (text: string) => void;
  cancel: () => void;
  confirm: () => void;
}

// Typing updates only the editor, not the transcript or its memoized message rows.
const Actions = createContext<EditActions | null>(null);
const Editor = createContext<EditorContext | null>(null);
export function useMessageEditing(scope?: string | null) {
  const actions = useContext(Actions);
  return actions && actions.scope === scope ? actions : null;
}

function textRestriction(text: string): string | null {
  if (text.trimStart().startsWith("/") || text.trimStart().startsWith("!")) return "edit_commands_unsupported";
  if (/(^|\s)@[\p{L}\p{N}_-]+/u.test(text)) return "edit_mentions_unsupported";
  if (parseQuotedUserMessage(text).quotedContext) return "edit_context_unsupported";
  return null;
}

/** Deliberately separate from Composer drafts, attachments and waiting input. */
export function MessageEditingProvider({ chatId, busy, enabled, onBegin, onReviewLatest, children }: {
  chatId: string | null;
  busy: boolean;
  enabled: boolean;
  onBegin?: (messageId: string) => void;
  onReviewLatest?: () => void;
  children: ReactNode;
}) {
  const { client, getToken } = useClient();
  const { t } = useTranslation();
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const selected = draft?.message ?? null;
  const read = useRef<AbortController | null>(null);
  const submitting = useRef<string | null>(null);
  useLayoutEffect(() => {
    setDraft(null);
    submitting.current = null;
    return () => { read.current?.abort(); read.current = null; submitting.current = null; };
  }, [chatId, client, enabled]);
  const errorLabel = useCallback((
    error: unknown,
    fallbackKey: "message.editFailed" | "message.editLoadFailed" = "message.editFailed",
  ) => {
    const code = error instanceof Error ? error.message : "";
    return t(`message.editErrors.${code}`, { defaultValue: t(fallbackKey) });
  }, [t]);
  const readRevision = useCallback((turnId: string, reviewLatest = false) => {
    if (!chatId || read.current) return;
    const controller = new AbortController();
    read.current = controller;
    setDraft((value) => value?.turnId === turnId ? { ...value, error: null } : value);
    void fetchLatestWebuiThread(client, getToken(), `websocket:${chatId}`, controller.signal).then((body) => {
      if (controller.signal.aborted) return;
      const revision = body?.source_revision;
      if (!revision) throw new Error("Missing source revision");
      if (reviewLatest) {
        // Show the very snapshot that the next explicit resend will be checked against.
        webuiThreadCache.set(`websocket:${chatId}`, body);
        onReviewLatest?.();
      }
      setDraft((value) => value?.turnId === turnId ? { ...value, revision, needsReview: false } : value);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setDraft((value) => value?.turnId === turnId ? { ...value, error: errorLabel(error, "message.editLoadFailed") } : value);
      }
    }).finally(() => { if (read.current === controller) read.current = null; });
  }, [chatId, client, errorLabel, getToken, onReviewLatest]);
  const actions = useMemo<EditActions | null>(() => {
    if (!chatId || !enabled) return null;
    const reason = (message: UIMessage): string | null => {
      if (busy) return t("message.editErrors.edit_session_busy");
      if (selected) return t("message.editFinishCurrent");
      if (message.role !== "user" || message.source || message.sessionMessage) return t("message.editErrors.edit_special_message");
      if (message.media?.length || message.images?.length) return t("message.editErrors.edit_attachments_unsupported");
      if (message.cliApps?.length || message.mcpPresets?.length || message.sessionMentions?.length) return t("message.editErrors.edit_mentions_unsupported");
      if (!message.content.trim() || message.deliveryStatus === "sending" || message.deliveryStatus === "failed") return t("message.editErrors.edit_plain_text_only");
      const restriction = textRestriction(message.content);
      return restriction ? t(`message.editErrors.${restriction}`) : null;
    };
    return { scope: `websocket:${chatId}`, message: selected, reason, begin(message) {
      if (reason(message) || read.current || submitting.current) return;
      const turnId = crypto.randomUUID();
      onBegin?.(message.id);
      setDraft({ message, text: message.content, turnId, revision: null, needsReview: false, submitting: false, error: null });
      readRevision(turnId);
    } };
  }, [busy, chatId, enabled, onBegin, readRevision, selected, t]);
  const cancel = () => {
    if (submitting.current) return;
    read.current?.abort();
    read.current = null;
    setDraft(null);
  };
  const confirm = () => {
    const current = draft;
    if (!enabled || !chatId || !current?.revision || busy || submitting.current || !current.text.trim()) return;
    const restriction = textRestriction(current.text);
    if (restriction) {
      setDraft({ ...current, error: t(`message.editErrors.${restriction}`) });
      return;
    }
    submitting.current = current.turnId;
    setDraft({ ...current, submitting: true, error: null });
    void client.requestMutation<{ accepted: boolean }>("chat.fork", {
      mode: "replace", chat_id: chatId, text: current.text, turn_id: current.turnId,
      source: { revision: current.revision, message_id: current.message.id,
        turn_id: current.message.turnId, text: current.message.content },
    }).then(() => {
      if (submitting.current === current.turnId) setDraft((value) => value?.turnId === current.turnId ? null : value);
    }, (error: unknown) => {
      if (submitting.current !== current.turnId) return;
      const stale = error instanceof Error && error.message === "edit_source_changed";
      setDraft((value) => value?.turnId === current.turnId ? {
        ...value, submitting: false, error: errorLabel(error),
        ...(stale ? { revision: null, needsReview: true } : {}),
      } : value);
    }).finally(() => { if (submitting.current === current.turnId) submitting.current = null; });
  };
  return <Actions.Provider value={actions}><Editor.Provider value={{ draft, busy, confirm, cancel,
    retryRead: () => { if (draft && !draft.revision) readRevision(draft.turnId, draft.needsReview); },
    change: (text) => setDraft((current) => current && !submitting.current
      ? { ...current, text, error: current.revision ? null : current.error }
      : current),
  }}>{children}</Editor.Provider></Actions.Provider>;
}

export function messageEditorSlots(sourceMissing = false) {
  return {
    input: <EditInput sourceMissing={sourceMissing} />,
    actions: <EditActionsRow sourceMissing={sourceMissing} />,
  };
}

function EditInput({ sourceMissing }: { sourceMissing: boolean }) {
  const editing = useContext(Editor);
  const { t } = useTranslation();
  const input = useRef<HTMLTextAreaElement>(null);
  const id = editing?.draft?.message.id;
  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.focus({ preventScroll: true });
    const end = el.value.length;
    el.setSelectionRange(end, end);
  }, [id]);
  if (!editing?.draft) return null;
  const { draft, busy, change, cancel, confirm } = editing;
  return <div className="relative min-w-[1ch] [text-autospace:no-autospace]">
      {/* Let literal text size the bubble, including an empty trailing line. */}
      <div aria-hidden className="invisible">{draft.text + "\u200b"}</div>
      <textarea ref={input} aria-label={t("message.editMessage")} value={draft.text}
        aria-describedby={`edit-feedback-${draft.turnId}`} aria-invalid={busy || sourceMissing || !!draft.error}
        disabled={draft.submitting}
        onChange={(event) => change(event.target.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            cancel();
            return;
          }
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            event.stopPropagation();
            if (!sourceMissing) confirm();
          }
        }}
        className="absolute inset-0 block h-full w-full resize-none overflow-hidden whitespace-pre-wrap border-0 bg-transparent p-0 [font:inherit] text-inherit outline-none [overflow-wrap:anywhere]" />
  </div>;
}

function EditActionsRow({ sourceMissing }: { sourceMissing: boolean }) {
  const editing = useContext(Editor);
  const { t } = useTranslation();
  if (!editing?.draft) return null;
  const { draft, busy, cancel, confirm, retryRead } = editing;
  const error = busy ? t("message.editErrors.edit_session_busy")
    : draft.needsReview ? draft.error : sourceMissing ? t("message.editSourceMissing") : draft.error;
  const pending = draft.submitting || (!sourceMissing && !busy && !draft.revision && !draft.error);
  const resend = t("message.confirmEditResend");
  const hint = t("message.editReplaceHint");
  const feedbackId = `edit-feedback-${draft.turnId}`;
  return <div className="flex max-w-full flex-col items-end gap-1">
    <p id={feedbackId} role={error ? "alert" : undefined} className={error ? "text-xs text-destructive" : "sr-only"}>{error || hint}</p>
    <div className="flex items-center justify-end gap-1">
      {draft.needsReview || (!sourceMissing && !draft.revision && draft.error) ? <Button type="button" size="sm" variant="ghost" className="touch-target"
        disabled={!draft.error || busy} aria-busy={!draft.error || undefined} onClick={retryRead}>
        {t(draft.needsReview ? "message.reviewLatest" : "common.retry")}
      </Button> : <HoverHint content={`${resend}\n${hint}`} align="end">
        <Button type="button" variant="icon" size="icon" className="touch-target h-7 w-7" onClick={confirm}
          aria-label={resend} aria-describedby={feedbackId} aria-busy={pending || undefined} aria-keyshortcuts="Control+Enter Meta+Enter"
          disabled={sourceMissing || busy || draft.submitting || !draft.revision || !draft.text.trim()}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : <Check className="h-4 w-4" aria-hidden />}
        </Button>
      </HoverHint>}
      <HoverHint content={t("common.cancel")} align="end">
        <Button type="button" variant="icon" size="icon" className="touch-target h-7 w-7 text-muted-foreground" aria-label={t("common.cancel")} disabled={draft.submitting} onClick={cancel}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </HoverHint>
    </div>
  </div>;
}
