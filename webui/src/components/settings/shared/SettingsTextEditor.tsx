import { useEffect, useRef, useState, type ReactElement } from "react";
import { SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { HoverHint } from "@/components/ui/tooltip";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

export function SettingsTextEditor({ id, title, description, value, placeholder, disabled, trigger, onSave, saveLabel }: {
  id?: string;
  title: string;
  description?: string;
  value: string;
  placeholder?: string;
  disabled?: boolean;
  trigger?: ReactElement;
  onSave: (value: string) => void | Promise<void>;
  saveLabel?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const editor = useRef<HTMLTextAreaElement>(null);
  const help = description?.trim();
  const hasDescription = !!help && help !== title.trim();
  useEffect(() => {
    if (error && !saving) editor.current?.focus();
  }, [error, saving]);
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await onSave(draft);
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  };
  return <Dialog open={open} onOpenChange={(next) => {
    if (saving) return;
    if (next) { setDraft(value); setError(""); }
    setOpen(next);
  }}>
    {trigger ? <DialogTrigger asChild id={id} disabled={disabled}>{trigger}</DialogTrigger> : <HoverHint content={t("settings.actions.edit")}>
      <DialogTrigger asChild>
        <Button size="icon" id={id} type="button" variant="ghost" disabled={disabled} aria-label={title}
          className="ml-auto flex h-9 w-9 shrink-0 rounded-full p-0 text-muted-foreground">
          <SquarePen className="h-4 w-4" aria-hidden />
        </Button>
      </DialogTrigger>
    </HoverHint>}
    <DialogContent className="max-w-xl" showCloseButton={!saving}
      {...(hasDescription ? {} : { "aria-describedby": undefined })}
      onOpenAutoFocus={(event) => { event.preventDefault(); editor.current?.focus(); }}
      onEscapeKeyDown={(event) => { if (saving) event.preventDefault(); }}
      onPointerDownOutside={(event) => { if (saving) event.preventDefault(); }}>
      <DialogHeader>
        <DialogTitle className="pr-6 text-base">{title}</DialogTitle>
        {hasDescription && <DialogDescription>{help}</DialogDescription>}
      </DialogHeader>
      <Textarea ref={editor} aria-label={title} value={draft} placeholder={placeholder} disabled={saving}
        aria-invalid={Boolean(error)} spellCheck={false}
        onChange={(event) => { setDraft(event.target.value); setError(""); }}
        className="h-[min(40vh,280px)] min-h-24 resize-none rounded-control font-mono text-[13px] leading-6" />
      {error && <p role="alert" className="break-words text-[13px] text-destructive">{error}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={saving} onClick={() => setOpen(false)}>{t("settings.actions.cancel")}</Button>
        <Button type="button" disabled={saving} onClick={() => void save()}>{saving ? t("settings.actions.saving") : saveLabel ?? t("settings.actions.save")}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
