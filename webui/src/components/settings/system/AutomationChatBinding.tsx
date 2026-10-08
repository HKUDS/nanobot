import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChannelLogo } from "@/components/settings/channels/ChannelIdentity";
import { channelUiOwner, channelUiPresentation } from "@/channel-plugins/registry";
import { channelTranslator } from "@/channel-plugins/i18n";
import { Button } from "@/components/ui/button";
import { DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { fetchAutomationChats } from "@/lib/api";
import { readLocalPreferences } from "@/lib/local-preferences";
import type { AutomationChat, AutomationChatsPayload, AutomationChatUpdate, NanobotFeatureInfo, SessionAutomationJob } from "@/lib/types";

export type ChangeAutomationChat = (job: SessionAutomationJob, values: AutomationChatUpdate) => Promise<void>;
export type AutomationChatNames = ReadonlyMap<string, { title: string; handle: string }>;

function ChatIdentity({ chat, title }: { chat: AutomationChat; title: string }) {
  const { t } = useTranslation();
  const owner = channelUiOwner(chat.channel);
  const presentation = channelUiPresentation(chat.channel);
  const platform = chat.channel === "websocket" ? t("settings.automations.chat.web")
    : channelTranslator(t, owner)("displayName", presentation?.displayName ?? chat.channel);
  const feature: NanobotFeatureInfo = {
    name: chat.channel, display_name: platform, type: "channel", enabled: true,
    installed: true, ready: true, status: "ready", install_supported: false, requires_restart: false,
  };
  return <span className="flex min-w-0 items-center gap-2.5 text-start">
    <span aria-hidden className="relative h-6 w-6 shrink-0">
      {chat.channel === "websocket" ? <img src="/brand/nanobot_mark.svg" alt="" className="h-6 w-6" />
        : <span className="absolute left-0 top-0 origin-top-left scale-75"><ChannelLogo feature={feature} showBrandLogos={readLocalPreferences().brandLogos} /></span>}
    </span>
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="break-words text-sm leading-5 [overflow-wrap:anywhere]">{title}</span>
      <span className="text-xs leading-4 text-muted-foreground">{platform}</span>
    </span>
  </span>;
}

export function AutomationChatBinding({ job, token, chatNames, onSave, children }: {
  job: SessionAutomationJob; token: string; onSave: ChangeAutomationChat;
  chatNames?: AutomationChatNames;
  children: (picker: ReactNode) => ReactNode;
}) {
  const { t } = useTranslation();
  const tx = (key: string, values?: Record<string, string>) => t(`settings.automations.chat.${key}`, values);
  const [data, setData] = useState<AutomationChatsPayload | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState<{ target: AutomationChat; previous: AutomationChat; revision: string; message: string; editingMessage?: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<{ target: AutomationChat; previous: AutomationChat } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const returning = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoadError(false);
    void fetchAutomationChats(token, job.id, controller.signal).then(value => {
      if (!controller.signal.aborted) {
        setData(value);
        setSaved(previous => previous?.target.id === value.current?.id ? previous : null);
      }
    }).catch(() => { if (!controller.signal.aborted) setLoadError(true); });
    return () => controller.abort();
  }, [token, job.id, job.chat_binding_revision, reload]);
  const reviewing = draft !== null;
  const locked = saving || Boolean(job.state.pending);
  const pickerDisabled = locked || !data?.chats.length || loadError || (!reviewing && data.revision !== job.chat_binding_revision);
  useEffect(() => {
    if (reviewing) heading.current?.focus();
  }, [reviewing]);
  useEffect(() => {
    if (!reviewing && !pickerDisabled && returning.current) {
      trigger.current?.focus(); returning.current = false;
    }
  }, [reviewing, pickerDisabled]);
  const back = () => { returning.current = true; setDraft(null); };
  const current = data?.current;
  const fallback: AutomationChat = { id: "current", title: job.origin?.title || tx("current"), channel: job.origin?.channel || "websocket" };
  const baseTitle = (chat: AutomationChat) => chatNames?.get(chat.id)?.title ?? chat.title;
  const counts = new Map<string, number>();
  for (const chat of data?.chats ?? []) {
    const title = baseTitle(chat);
    counts.set(title, (counts.get(title) ?? 0) + 1);
  }
  const chatTitle = (chat: AutomationChat) => {
    const title = baseTitle(chat);
    const name = chatNames?.get(chat.id);
    return name && (counts.get(title) ?? 0) > 1 ? `${title} · @${name.handle}` : title;
  };
  const identity = (chat: AutomationChat) => <ChatIdentity chat={chat} title={chatTitle(chat)} />;
  const targetUnavailable = Boolean(draft && data && !data.chats.some(chat => chat.id === draft.target.id && !chat.unavailable));
  const picker = (review: boolean) => <Select value={review ? draft?.target.id : current?.id ?? "current"}
    disabled={pickerDisabled} onValueChange={id => {
      const target = data?.chats.find(chat => chat.id === id);
      if (!target || target.unavailable || id === current?.id) return;
      setError("");
      setDraft(previous => previous ? { ...previous, target } : {
        target, previous: current ?? fallback,
        revision: job.chat_binding_revision!, message: job.payload.message,
      });
    }}>
    <SelectTrigger ref={review ? undefined : trigger} aria-label={tx(review ? "new" : "label")}
      aria-busy={!loadError && (!data || data.revision !== job.chat_binding_revision)}
      className="h-auto min-h-14 w-full py-2 disabled:opacity-100 disabled:[&>svg]:opacity-40 [&>span:first-child]:min-w-0 [&>span:first-child]:flex-1 [&>span:first-child]:text-start">
      <SelectValue>{identity((review ? draft?.target : current) ?? fallback)}</SelectValue>
    </SelectTrigger>
    <SelectContent>
      {!current ? <SelectItem value="current" disabled>{identity(fallback)}</SelectItem> : null}
      {data?.chats.map(chat => <SelectItem key={chat.id} value={chat.id} textValue={`${chatTitle(chat)} ${chat.channel}`}
        disabled={chat.unavailable || (review && chat.id === current?.id)}
        className="h-auto min-h-11 py-2 [&>span:first-child]:min-w-0 [&>span:first-child]:max-w-[calc(100vw-5rem)] [&>span:first-child]:w-full">{identity(chat)}</SelectItem>)}
    </SelectContent>
  </Select>;
  const save = async () => {
    if (!draft || locked || targetUnavailable || !draft.message.trim()) return;
    setSaving(true); setError("");
    try {
      await onSave(job, { target_id: draft.target.id, revision: draft.revision, message: draft.message });
      setData(previous => previous ? { ...previous, current: draft.target } : previous);
      setSaved({ target: draft.target, previous: draft.previous }); back(); setReload(value => value + 1);
    } catch (cause) {
      const reasons: Record<string, string> = {
        automation_chat_conflict: "conflict", automation_chat_busy: "schedulerBusy",
        automation_chat_unavailable: "unavailable",
      };
      setError(tx(cause instanceof Error ? reasons[cause.message] ?? "failed" : "failed"));
    } finally { setSaving(false); }
  };
  if (!draft) return children(<div className="space-y-2">
    <p className="text-[13px] font-medium">{tx("label")}</p>
    {picker(false)}
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <p role={saved ? "status" : undefined} className="text-[12px] leading-5 text-muted-foreground">
        {job.state.pending ? tx("busy") : saved ? tx("saved", { chat: chatTitle(saved.target) }) : tx("hint")}
      </p>
      {saved && current?.id === saved.target.id && data?.chats.some(chat => chat.id === saved.previous.id && !chat.unavailable) ? (
        <Button variant="link" size="sm" className="h-11 justify-start whitespace-normal p-0 text-start text-[12px] sm:h-auto" disabled={pickerDisabled}
          onClick={() => {
            setError("");
            setDraft({ target: saved.previous, previous: current, revision: data.revision, message: job.payload.message });
          }}>{tx("changeBack", { chat: chatTitle(saved.previous) })}</Button>
      ) : null}
    </div>
    {loadError ? <Button variant="link" size="sm" onClick={() => setReload(value => value + 1)}>{tx("retry")}</Button> : null}
    {data && data.chats.length <= (current ? 1 : 0) ? <p className="text-[12px] leading-5 text-muted-foreground">{tx("available")}</p> : null}
  </div>);
  return <>
    <DialogHeader className="shrink-0 px-6 pb-4 pr-12 pt-5 text-left">
      <DialogTitle ref={heading} tabIndex={-1} className="break-words text-lg font-medium leading-snug tracking-normal outline-none">{tx("change")}</DialogTitle>
    </DialogHeader>
    <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-6 [text-wrap:pretty]">
      <div className="space-y-3">
        <div role="group" aria-label={tx("previous")} className="flex min-w-0 items-center gap-3 pb-1 text-muted-foreground">
          <span className="shrink-0 text-[12px]">{tx("previous")}</span>
          {identity(draft.previous)}
        </div>
        <div className="space-y-2">
          <p className="text-[13px] font-medium">{tx("new")}</p>
          {picker(true)}
        </div>
      </div>
      <div className="space-y-1">
        <p className="text-[13px] leading-5">{tx("effect")}</p>
        <p className="text-[12px] leading-5 text-muted-foreground">{tx("history")}</p>
      </div>
      <div className="space-y-2 rounded-2xl bg-muted/50 px-4 pb-4 pt-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[12px] text-muted-foreground">{tx("message")}</p>
          {!draft.editingMessage ? <Button variant="link" size="sm" disabled={saving}
            className="h-11 shrink-0 p-0 text-[12px] sm:h-9"
            onClick={() => setDraft({ ...draft, editingMessage: true })}>{tx("editInstructions")}</Button> : null}
        </div>
        {draft.editingMessage ? <>
          <Textarea autoFocus aria-label={tx("message")} rows={3} value={draft.message} disabled={saving}
            onChange={event => setDraft({ ...draft, message: event.target.value })}
            className="min-h-20 resize-y text-base leading-6 sm:text-[13px] sm:leading-5" />
          <p className="text-[12px] leading-5 text-muted-foreground">{tx("editInstructionsHint")}</p>
        </> : <p className="whitespace-pre-wrap break-words text-[13px] leading-5 [overflow-wrap:anywhere]">{draft.message}</p>}
      </div>
      <p className="text-[12px] leading-5 text-muted-foreground">{tx("review")}</p>
      {error || targetUnavailable ? <p role="alert" className="text-[12px] leading-5 text-destructive">{error || tx("unavailable")}</p> : null}
    </div>
    <DialogFooter className="mt-4 shrink-0 flex-row justify-end gap-2 border-t border-border/45 px-6 py-3">
      <Button variant="ghost" size="sm" disabled={saving} className="h-auto min-h-11 min-w-0 whitespace-normal font-normal text-muted-foreground sm:min-h-9" onClick={back}>{t("settings.automations.cancel")}</Button>
      <Button size="sm" className="grid h-auto min-h-11 min-w-0 whitespace-normal sm:min-h-9" disabled={locked || targetUnavailable || !draft.message.trim()} aria-busy={saving} onClick={() => void save()}>
        <span className="col-start-1 row-start-1" aria-hidden={saving || undefined} style={saving ? { visibility: "hidden" } : undefined}>{tx(draft.editingMessage ? "saveAndChange" : "confirm")}</span>
        <span className="col-start-1 row-start-1" aria-hidden={!saving || undefined} style={!saving ? { visibility: "hidden" } : undefined}>{tx("saving")}</span>
      </Button>
    </DialogFooter>
  </>;
}
