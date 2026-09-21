import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { fetchPromptCommands, savePromptCommand, PROMPT_COMMANDS_CHANGED,
  type PromptCommand, type PromptCommandsPayload } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

const blank = (): PromptCommand => ({ name: "", source: "user", description: "",
  argument_hint: "", body: "", enabled: true, revision: "" });

export function PromptCommandsSettings() {
  const { t } = useTranslation();
  const { client, getToken } = useClient();
  const [payload, setPayload] = useState<PromptCommandsPayload | null>(null);
  const [draft, setDraft] = useState<PromptCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [remove, setRemove] = useState(false);
  const [discard, setDiscard] = useState(false);
  const [original, setOriginal] = useState("");
  useEffect(() => {
    let active = true;
    fetchPromptCommands(getToken()).then((value) => { if (active) { setPayload(value); setError(""); } })
      .catch((reason: unknown) => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [getToken, reload]);
  const edit = (value: PromptCommand) => {
    setDraft({ ...value }); setOriginal(JSON.stringify(value)); setError("");
  };
  const close = () => {
    if (busy) return;
    if (draft && JSON.stringify(draft) !== original) setDiscard(true);
    else setDraft(null);
  };
  const save = async (deleting = false) => {
    if (!draft || busy) return;
    setBusy(true); setError("");
    try {
      const value = await savePromptCommand(client, draft, deleting);
      setPayload(value); setDraft(null);
      window.dispatchEvent(new Event(PROMPT_COMMANDS_CHANGED));
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const label = (key: string) => t(`promptCommands.${key}`);
  return <div className="settings-stack">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <p className="max-w-xl text-sm text-muted-foreground">{label("intro")}</p>
      <div className="flex gap-2">
        <Button variant="ghost" size="icon" aria-label={label("refresh")} onClick={() => setReload((value) => value + 1)}><RefreshCw className="h-4 w-4" /></Button>
        <Button onClick={() => edit(blank())}><Plus className="mr-2 h-4 w-4" />{label("add")}</Button>
      </div>
    </div>
    {error && !draft ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    {payload?.invalid ? <p role="status" className="text-sm text-muted-foreground">{t("promptCommands.invalid", { count: payload.invalid })}</p> : null}
    <section className="overflow-hidden rounded-panel bg-settings-surface">
      {!payload ? (!error && <p className="p-5 text-sm text-muted-foreground">{label("loading")}</p>) : payload.commands.length === 0 ?
        <p className="p-5 text-sm text-muted-foreground">{label("empty")}</p> : payload.commands.map((command) =>
          <button type="button" key={`${command.source}:${command.name}`} onClick={() => edit(command)}
            className="flex min-h-16 w-full items-center gap-3 px-5 py-3 text-left hover:bg-foreground/5">
            <span className="min-w-0 flex-1"><span className="font-medium">/{command.name}</span>
              <span className="ml-2 text-xs text-muted-foreground">{label(command.source)}</span>
              <span className="block truncate text-sm text-muted-foreground">{command.description}</span></span>
            {command.shadowed || !command.enabled ? <span className="text-xs text-muted-foreground">{label(command.shadowed ? "shadowed" : "disabled")}</span> : null}
          </button>)}
    </section>
    <Sheet open={draft !== null} onOpenChange={(open) => { if (!open) close(); }}>
      <SheetContent className="flex w-full flex-col overflow-y-auto sm:max-w-xl">
        <SheetTitle>{label(draft?.revision ? "edit" : "add")}</SheetTitle>
        <SheetDescription>{label("hint")}</SheetDescription>
        {draft ? <form className="flex flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label className="grid gap-2 text-sm">{label("name")}<Input required pattern="[a-z][a-z0-9-]{0,47}" maxLength={48} disabled={busy || !!draft.revision} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <label className="grid gap-2 text-sm">{label("source")}<select className="rounded-control border border-input bg-background p-2" disabled={busy || !!draft.revision} value={draft.source} onChange={(event) => setDraft({ ...draft, source: event.target.value as PromptCommand["source"] })}>
            <option value="user">{label("user")}</option><option value="workspace">{label("workspace")}</option>
          </select></label>
          <label className="grid gap-2 text-sm">{label("description")}<Input maxLength={240} disabled={busy} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
          <label className="grid gap-2 text-sm">{label("argumentHint")}<Input maxLength={120} disabled={busy} value={draft.argument_hint} onChange={(event) => setDraft({ ...draft, argument_hint: event.target.value })} /></label>
          <label className="grid gap-2 text-sm">{label("body")}<Textarea required rows={10} disabled={busy} value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} /></label>
          <div className="flex items-center justify-between text-sm">{label("enabled")}<ToggleButton label={label("enabled")} disabled={busy} checked={draft.enabled} onChange={(enabled) => setDraft({ ...draft, enabled })} /></div>
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          <div className="flex justify-end gap-2">
            {draft.revision ? <Button type="button" variant="ghost" disabled={busy} onClick={() => setRemove(true)}><Trash2 className="mr-2 h-4 w-4" />{label("delete")}</Button> : null}
            <Button type="button" variant="ghost" disabled={busy} onClick={close}>{label("cancel")}</Button>
            <Button type="submit" disabled={busy}>{label(busy ? "saving" : "save")}</Button>
          </div>
        </form> : null}
      </SheetContent>
    </Sheet>
    <AlertDialog open={remove || discard} onOpenChange={(open) => { if (!open) { setRemove(false); setDiscard(false); } }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{label(remove ? "delete" : "discard")}</AlertDialogTitle>
        <AlertDialogDescription>{label(remove ? "deleteHint" : "discardHint")}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>{label("cancel")}</AlertDialogCancel>
          <AlertDialogAction onClick={() => { if (remove) void save(true); else setDraft(null); setRemove(false); setDiscard(false); }}>{label("confirm")}</AlertDialogAction>
        </AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
  </div>;
}
