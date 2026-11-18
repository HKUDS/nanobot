import { useId, useRef, useState, type CSSProperties } from "react";
import { ImagePlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { useBackground } from "@/providers/BackgroundProvider";
import { useObjectUrl } from "@/hooks/useObjectUrl";

export function BackgroundSettings() {
  const { t } = useTranslation();
  const background = useBackground();
  const input = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const blurId = useId();
  const veilId = useId();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [removed, setRemoved] = useState(false);
  const [fileError, setFileError] = useState(false);
  const [imageSaved, setImageSaved] = useState(false);
  const [selectedBlur, setSelectedBlur] = useState(5);
  const [selectedVeil, setSelectedVeil] = useState(88);
  const image = removed ? null : file ?? background?.image ?? null;
  const preview = useObjectUrl(image);

  if (!background) return null;
  const hasPreview = !!file || (background.hasBackground && !removed);
  const styleDirty = selectedBlur !== background.blur || selectedVeil !== background.veil;
  const dirty = !!file || (removed && background.hasBackground) || styleDirty;
  const setDialogOpen = (next: boolean) => {
    if (background.busy) return;
    setOpen(next);
    setFile(null);
    setRemoved(false);
    setFileError(false);
    setImageSaved(false);
    setSelectedBlur(background.blur);
    setSelectedVeil(background.veil);
    background.clearError();
  };
  const save = async () => {
    const imageChanged = !!file || removed;
    const saved = file ? await background.upload(file) : removed ? await background.remove() : true;
    if (!saved) return;
    if (imageChanged) {
      setFile(null);
      setRemoved(false);
      setImageSaved(true);
    }
    const styleSaved = styleDirty ? await background.setStyle(selectedBlur, selectedVeil) : true;
    if (styleSaved) setDialogOpen(false);
  };

  return <>
    <button ref={trigger} type="button" className="settings-disclosure-row background-settings-row w-full text-left transition-colors settings-hover"
      aria-label={t("settings.appearance.background")} disabled={!background.ready && !background.loadError}
      onClick={() => background.loadError ? background.retry() : setDialogOpen(true)}>
      <span className="text-control-label text-foreground">{t("settings.appearance.background")}</span>
      <span className="background-settings-trigger">
        {background.loadError ? <span className="text-destructive">{t("common.retry")}</span>
          : background.hasBackground ? <span className="background-settings-thumbnail" aria-hidden />
            : <span className="text-muted-foreground">{t("settings.appearance.backgroundChoose")}</span>}
      </span>
    </button>
    <Dialog open={open} onOpenChange={setDialogOpen}>
      <DialogContent className="background-settings-dialog" aria-describedby={undefined} showCloseButton={false}
        onCloseAutoFocus={event => {
          if (trigger.current?.isConnected) { event.preventDefault(); trigger.current.focus(); }
        }}>
        <DialogTitle className="sr-only">{t("settings.appearance.background")}</DialogTitle>
        <button type="button" className="background-settings-preview" data-has-image={hasPreview || undefined}
          disabled={background.busy} onClick={() => input.current?.click()}
          aria-label={t(hasPreview ? "settings.appearance.backgroundReplace" : "settings.appearance.backgroundChoose")}
          style={{
            ...(preview ? { backgroundImage: `url("${preview}")` } : {}),
            "--custom-background-blur": `${selectedBlur}px`,
            "--custom-background-tint": `${selectedVeil / 100}`,
          } as CSSProperties}>
          {hasPreview ? <span className="background-settings-preview-action">
            <ImagePlus className="h-3.5 w-3.5" aria-hidden />
            {t("settings.appearance.backgroundReplace")}
          </span> : <span className="background-settings-empty">
            <ImagePlus className="h-6 w-6" aria-hidden />
            <span>{t("settings.appearance.backgroundChoose")}</span>
          </span>}
        </button>
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => {
          const next = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (next) {
            if (next.size > 6 * 1024 * 1024) { setFileError(true); return; }
            setFile(next); setRemoved(false); setFileError(false); setImageSaved(false); background.clearError();
          }
        }} />
        {hasPreview && <div className="background-blur-control">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor={blurId} className="text-control-label">{t("settings.appearance.backgroundBlur")}</label>
            <output htmlFor={blurId} className="text-xs tabular-nums text-muted-foreground">{selectedBlur} px</output>
          </div>
          <input id={blurId} type="range" min={0} max={20} step={1} value={selectedBlur} disabled={background.busy}
            style={{ "--slider-progress": `${selectedBlur * 5}%` } as CSSProperties}
            onChange={event => setSelectedBlur(Number(event.currentTarget.value))} />
        </div>}
        {hasPreview && <div className="background-blur-control">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor={veilId} className="text-control-label">{t("settings.appearance.backgroundFade")}</label>
            <output htmlFor={veilId} className="text-xs tabular-nums text-muted-foreground">{selectedVeil}%</output>
          </div>
          <input id={veilId} type="range" min={0} max={100} step={1} value={selectedVeil} disabled={background.busy}
            style={{ "--slider-progress": `${selectedVeil}%` } as CSSProperties}
            onChange={event => setSelectedVeil(Number(event.currentTarget.value))} />
        </div>}
        {background.loadError && <div role="alert" className="flex items-center gap-2 text-xs text-destructive">
          <span>{t("settings.status.loadError")}</span>
          <Button type="button" variant="ghost" size="sm" onClick={background.retry}>{t("common.retry")}</Button>
        </div>}
        {fileError && <p role="alert" className="text-xs text-destructive">{t("settings.appearance.backgroundTooLarge")}</p>}
        {background.error && <p role="alert" className="text-xs text-destructive">{t(imageSaved ? "settings.appearance.backgroundPartialError" : "settings.appearance.backgroundError")}</p>}
        <DialogFooter className="background-settings-footer">
          {hasPreview && <Button type="button" variant="ghost" size="sm" className="background-settings-remove" disabled={background.busy}
            onClick={() => { setFile(null); setRemoved(true); setFileError(false); setImageSaved(false); background.clearError(); }}>
            {t("settings.appearance.backgroundRemove")}
          </Button>}
          <Button type="button" variant="ghost" size="sm" disabled={background.busy} onClick={() => setDialogOpen(false)}>{t("settings.actions.cancel")}</Button>
          <Button type="button" size="sm" disabled={!dirty || background.busy || !background.ready || (hasPreview && !preview)} onClick={() => void save()}>{t(background.busy ? "settings.actions.saving" : "settings.actions.save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
