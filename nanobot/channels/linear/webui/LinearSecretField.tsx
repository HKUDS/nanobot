import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelConfigField } from "@/components/settings/channels/catalog";
import { channelFieldInputId } from "@/components/settings/channels/CredentialForm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** A saved secret is a status, never a placeholder or a value sent back to the browser. */
export function LinearSecretField({ field, configured, disabled, onSave }: {
  field: ChannelConfigField;
  configured: boolean;
  disabled: boolean;
  onSave: (key: string, value: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const inFlight = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const inputId = channelFieldInputId(field.key);
  const displaySaved = configured && !editing;
  const locked = disabled || saving;

  useEffect(() => {
    if (editing && !disabled && !saving) inputRef.current?.focus();
    else if (!editing && restoreFocus.current && !disabled && !saving) {
      replaceRef.current?.focus();
      restoreFocus.current = false;
    }
  }, [editing, disabled, saving, configured]);

  const cancel = () => {
    if (inFlight.current) return;
    setValue("");
    setVisible(false);
    setError(false);
    restoreFocus.current = configured;
    setEditing(false);
  };

  const save = async () => {
    if (locked || inFlight.current || !value.trim()) return;
    inFlight.current = true;
    setSaving(true);
    setError(false);
    try {
      await onSave(field.key, value);
      setValue("");
      setVisible(false);
      restoreFocus.current = true;
      setEditing(false);
    } catch {
      // Keep the draft and existing configured state; never echo credentials from an error.
      setError(true);
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  };

  return <div className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-x-4">
    <label id={`${inputId}-label`} htmlFor={displaySaved ? undefined : inputId}
      className="flex min-h-10 min-w-0 items-center self-start text-[11px] font-medium text-foreground/85 sm:min-h-9">
      {field.label}
    </label>
    <div className="min-w-0" role="group" aria-labelledby={`${inputId}-label`} aria-busy={saving}>
      {displaySaved ? (
        <div className="flex min-h-10 items-center justify-between gap-2 rounded-full border border-border/40 bg-background ps-3 pe-1 sm:min-h-9">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2.5">
            <span aria-hidden className="text-[13px] tracking-[0.12em] text-foreground/70">••••••••</span>
            <span role="status" className="text-[11px] text-muted-foreground">
              {tx("custom.secretSaved", "Saved")}
            </span>
          </div>
          <Button ref={replaceRef} type="button" variant="ghost" size="sm" disabled={disabled}
            aria-label={tx("custom.replaceSecretLabel", "Replace {{name}}", { name: field.label })}
            className="h-8 shrink-0 rounded-full px-2.5 text-[12px] text-muted-foreground hover:text-foreground"
            onClick={() => { setVisible(false); setError(false); setEditing(true); }}>
            {tx("custom.replaceSecret", "Replace")}
          </Button>
        </div>
      ) : <>
        <div className="relative">
          <Input ref={inputRef} id={inputId} type={visible ? "text" : "password"}
            value={value} autoComplete="off" spellCheck={false} disabled={locked}
            placeholder={tx("custom.enterSecret", "Enter secret")}
            aria-invalid={error} aria-describedby={error ? `${inputId}-error` : undefined}
            onChange={event => { setValue(event.target.value); setError(false); }}
            onKeyDown={event => {
              if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); void save(); }
              if (event.key === "Escape" && (editing || value)) {
                event.preventDefault(); event.stopPropagation(); cancel();
              }
            }}
            className="h-10 rounded-full border-border/40 bg-background pe-10 text-base sm:h-9 sm:text-[13px]" />
          {value ? <Button type="button" variant="ghost" size="icon" disabled={locked}
            aria-label={visible ? t("settings.channels.hideSecret", { defaultValue: "Hide secret" })
              : t("settings.channels.showSecret", { defaultValue: "Show secret" })}
            onClick={() => setVisible(current => !current)}
            className="absolute end-1 top-1/2 h-8 w-8 -translate-y-1/2 rounded-full text-muted-foreground">
            {visible ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
          </Button> : null}
        </div>
        {editing || value ? <div className="mt-1.5 flex min-h-8 flex-wrap items-center justify-end gap-1.5">
          <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={cancel}
            className="h-8 rounded-full px-3 text-[12px] text-muted-foreground">
            {t("settings.actions.cancel", { defaultValue: "Cancel" })}
          </Button>
          <Button type="button" variant="secondary" size="sm" disabled={locked || !value.trim()}
            onClick={() => void save()} className="h-8 min-w-16 rounded-full px-3 text-[12px]">
            {saving ? t("settings.actions.saving", { defaultValue: "Saving" })
              : t("settings.actions.save", { defaultValue: "Save" })}
          </Button>
        </div> : null}
        {error ? <p id={`${inputId}-error`} role="alert" className="mt-1.5 text-[12px] leading-5 text-destructive">
          {tx("custom.secretSaveFailed", "Could not confirm the save. Try again or cancel.")}
        </p> : null}
      </>}
    </div>
  </div>;
}
