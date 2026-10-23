import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
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

interface EditingContext {
  draft: EditDraft | null;
  reason: (message: UIMessage) => string | null;
  begin: (message: UIMessage) => void;
  change: (text: string) => void;
  cancel: () => void;
  confirm: () => void;
  busy: boolean;
}

const Context = createContext<EditingContext | null>(null);
export const useMessageEditing = () => useContext(Context);

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
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const submitting = useRef<string | null>(null);
  useLayoutEffect(() => {
    setDraft(null);
    submitting.current = null;
  }, [chatId]);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const errorLabel = (error: unknown) => {
    const code = error instanceof Error ? error.message : "";
    return t(`message.editErrors.${code}`, { defaultValue: t("message.editFailed") });
  };
  const reason = (message: UIMessage): string | null => {
    if (!enabled || !chatId) return t("message.editErrors.edit_plain_text_only");
    if (busy) return t("message.editErrors.edit_session_busy");
    if (draft && draft.message.id !== message.id) return t("message.editFinishCurrent");
    if (message.deliveryStatus === "sending" || message.deliveryStatus === "failed") return t("message.editErrors.edit_plain_text_only");
    if (message.source || message.sessionMessage) return t("message.editErrors.edit_special_message");
    if (message.media?.length || message.images?.length) return t("message.editErrors.edit_attachments_unsupported");
    if (message.cliApps?.length || message.mcpPresets?.length || message.sessionMentions?.length) return t("message.editErrors.edit_mentions_unsupported");
    const restriction = textRestriction(message.content);
    return restriction ? t(`message.editErrors.${restriction}`) : null;
  };
  const begin = (message: UIMessage) => {
    if (!chatId || reason(message) || submitting.current) return;
    const turnId = crypto.randomUUID();
    onBegin?.(message.id);
    setDraft({ message, text: message.content, turnId, revision: null, submitting: false, error: null });
    void fetchLatestWebuiThread(client, getToken(), `websocket:${chatId}`).then((body) => {
      const revision = body?.source_revision;
      if (!revision) throw new Error("edit_source_changed");
      if (mounted.current) setDraft((current) => current?.turnId === turnId ? { ...current, revision } : current);
    }).catch((error: unknown) => {
      if (mounted.current) setDraft((current) => current?.turnId === turnId ? { ...current, error: errorLabel(error) } : current);
    });
  };
  const confirm = () => {
    const current = draftRef.current;
    if (!chatId || !current?.revision || busy || submitting.current || !current.text.trim()) return;
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
      if (mounted.current) setDraft((value) => value?.turnId === current.turnId ? null : value);
    }, (error: unknown) => {
      if (mounted.current) setDraft((value) => value?.turnId === current.turnId ? { ...value, submitting: false, error: errorLabel(error) } : value);
    }).finally(() => { if (submitting.current === current.turnId) submitting.current = null; });
  };
  return <Context.Provider value={{ draft, reason, begin, confirm, busy,
    change: (text) => setDraft((current) => current && !submitting.current ? { ...current, text } : current),
    cancel: () => { if (!submitting.current) setDraft(null); },
  }}>{children}</Context.Provider>;
}

export function InlineMessageEditor({ sourceMissing = false }: { sourceMissing?: boolean }) {
  const editing = useMessageEditing();
  const { t } = useTranslation();
  const input = useRef<HTMLTextAreaElement>(null);
  const errorId = useId();
  const id = editing?.draft?.message.id;
  useLayoutEffect(() => { input.current?.focus({ preventScroll: true }); }, [id]);
  if (!editing?.draft) return null;
  const { draft, busy, change, cancel, confirm } = editing;
  const error = sourceMissing ? t("message.editErrors.edit_source_changed")
    : busy ? t("message.editErrors.edit_session_busy") : draft.error;
  return <form data-message-editor className="min-w-0 max-w-full whitespace-normal"
    onSubmit={(event) => { event.preventDefault(); confirm(); }}>
    <div className="relative min-w-0 [text-autospace:no-autospace]">
      <div aria-hidden className="invisible whitespace-pre-wrap [overflow-wrap:anywhere]">{draft.text + "\u200b"}</div>
      <textarea ref={input} aria-label={t("message.editMessage")} value={draft.text}
        aria-describedby={error ? errorId : undefined} aria-invalid={!!error}
        disabled={draft.submitting}
        onChange={(event) => change(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); cancel(); } }}
        className="absolute inset-0 block h-full w-full min-w-0 resize-none overflow-hidden border-0 bg-transparent p-0 [font:inherit] text-inherit outline-none" />
    </div>
    {error ? <p id={errorId} role="alert" className="mt-2 text-xs leading-5 text-destructive">{error}</p> : null}
    <div className="mt-2 flex flex-wrap justify-end gap-1.5">
      <Button type="button" size="sm" variant="ghost" disabled={draft.submitting} onClick={cancel}
        className="max-md:min-h-11">{t("common.cancel")}</Button>
      <Button type="submit" size="sm"
        disabled={sourceMissing || busy || draft.submitting || !draft.revision || !draft.text.trim()}
        className="max-md:min-h-11">{t("message.confirmEditResend")}</Button>
    </div>
  </form>;
}
