import { createContext, useCallback, useContext, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useClient } from "@/providers/ClientProvider";
import { parseQuotedUserMessage } from "@/lib/user-message-quote";
import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";
import type { UIMessage } from "@/lib/types";

interface EditDraft {
  message: UIMessage;
  text: string;
  turnId: string;
  revision: string | null;
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
export function MessageEditingProvider({ chatId, busy, enabled, onBegin, children }: {
  chatId: string | null;
  busy: boolean;
  enabled: boolean;
  onBegin?: (messageId: string) => void;
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
  const readRevision = useCallback((turnId: string) => {
    if (!chatId || read.current) return;
    const controller = new AbortController();
    read.current = controller;
    setDraft((value) => value?.turnId === turnId ? { ...value, error: null } : value);
    void fetchLatestWebuiThread(client, getToken(), `websocket:${chatId}`, controller.signal).then((body) => {
      if (controller.signal.aborted) return;
      const revision = body?.source_revision;
      if (!revision) throw new Error("edit_source_changed");
      setDraft((value) => value?.turnId === turnId ? { ...value, revision } : value);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setDraft((value) => value?.turnId === turnId ? { ...value, error: errorLabel(error, "message.editLoadFailed") } : value);
      }
    }).finally(() => { if (read.current === controller) read.current = null; });
  }, [chatId, client, errorLabel, getToken]);
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
      setDraft({ message, text: message.content, turnId, revision: null, submitting: false, error: null });
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
      if (submitting.current === current.turnId) setDraft((value) => value?.turnId === current.turnId ? { ...value, submitting: false, error: errorLabel(error) } : value);
    }).finally(() => { if (submitting.current === current.turnId) submitting.current = null; });
  };
  return <Actions.Provider value={actions}><Editor.Provider value={{ draft, busy, confirm, cancel,
    retryRead: () => { if (draft && !draft.revision) readRevision(draft.turnId); },
    change: (text) => setDraft((current) => current && !submitting.current
      ? { ...current, text, error: current.revision ? null : current.error }
      : current),
  }}>{children}</Editor.Provider></Actions.Provider>;
}

export function InlineMessageEditor({ sourceMissing = false }: { sourceMissing?: boolean }) {
  const editing = useContext(Editor);
  const { t } = useTranslation();
  const input = useRef<HTMLTextAreaElement>(null);
  const errorId = useId();
  const hintId = useId();
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
  const error = sourceMissing ? t("message.editErrors.edit_source_changed")
    : busy ? t("message.editErrors.edit_session_busy") : draft.error;
  const loadingRevision = !sourceMissing && !busy && !draft.revision && !draft.error;
  const pendingAction = draft.submitting || loadingRevision;
  const showHint = !error && !sourceMissing;
  return <form data-message-editor className="min-w-0 max-w-full whitespace-normal"
    onSubmit={(event) => { event.preventDefault(); if (!sourceMissing) confirm(); }}>
    <div className="grid min-w-0 [text-autospace:no-autospace]">
      <div aria-hidden
        className="invisible touch-text-input col-start-1 row-start-1 max-h-[min(45vh,22rem)] overflow-hidden whitespace-pre-wrap [overflow-wrap:anywhere]">
        {draft.text + "\u200b"}
      </div>
      <textarea ref={input} aria-label={t("message.editMessage")} value={draft.text}
        aria-describedby={error ? errorId : showHint ? hintId : undefined} aria-invalid={!!error}
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
        className="touch-text-input scrollbar-thin col-start-1 row-start-1 block max-h-[min(45vh,22rem)] min-h-[1.6em] w-full min-w-0 resize-none overflow-y-auto border-0 bg-transparent p-0 [font:inherit] text-inherit outline-none" />
    </div>
    {error ? <p id={errorId} role="alert" className="mt-2 text-xs leading-5 text-destructive">{error}</p> : null}
    <div className="mt-2.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-border/50 pt-2">
      {showHint ? <p id={hintId} className="min-w-0 text-xs leading-5 text-muted-foreground">{t("message.editReplaceHint")}</p> : null}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
        <Button type="button" size="sm" variant="ghost" disabled={draft.submitting} onClick={cancel}
          className="max-md:min-h-11">{t("common.cancel")}</Button>
        {!sourceMissing && !draft.revision && draft.error ? <Button type="button" size="sm" className="max-md:min-h-11"
          onClick={editing.retryRead}>{t("common.retry")}</Button> : <Button type="submit" size="sm"
          aria-busy={pendingAction || undefined}
          aria-keyshortcuts="Control+Enter Meta+Enter"
          disabled={sourceMissing || busy || draft.submitting || !draft.revision || !draft.text.trim()}
          className="max-md:min-h-11">
          {pendingAction ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          {t("message.confirmEditResend")}
        </Button>}
      </div>
    </div>
  </form>;
}
