import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { Input } from "@/components/ui/input";
import { ToggleButton } from "@/components/ui/toggle-button";

export function IdleCompactionControl({
  id, value, savedMinutes, disabled, errorId, onChange, onCommit,
}: {
  id: string;
  value: string;
  savedMinutes: number;
  disabled: boolean;
  errorId?: string;
  onChange: (next: string) => void;
  onCommit: (next: string) => void;
}) {
  const { t } = useTranslation();
  const tr = (key: string) => t(`settings.runtimeConfig.idleCompaction.${key}`);
  const [editing, setEditing] = useState(false);
  const enabled = editing || value !== "0";
  const lastMinutes = useRef(savedMinutes > 0 ? String(savedMinutes) : "15");
  useEffect(() => {
    if (savedMinutes > 0) lastMinutes.current = String(savedMinutes);
  }, [savedMinutes]);
  const toggleId = `${id}-enabled`;
  return <>
    <SettingsRow title={tr("label")} description={tr("help")}>
      <ToggleButton id={toggleId} checked={enabled} disabled={disabled} label={tr("label")}
        onChange={(next) => {
          if (/^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0) {
            lastMinutes.current = value;
          }
          setEditing(false);
          onCommit(next ? lastMinutes.current : "0");
        }} />
    </SettingsRow>
    {enabled ? <SettingsRow title={tr("wait")}>
      <div className="flex items-center gap-2">
        <Input id={id} type="text" inputMode="numeric" value={value} disabled={disabled}
          aria-label={tr("wait")} aria-describedby={`${id}-unit${errorId ? ` ${errorId}` : ""}`}
          aria-invalid={Boolean(errorId) || undefined}
          className="h-9 w-28 rounded-full text-[13px]" autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => setEditing(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              setEditing(false);
              onCommit(value);
            }
          }}
          onBlur={(event) => {
            if (event.relatedTarget?.id === toggleId
              || (event.relatedTarget instanceof Element && event.relatedTarget.closest("[data-settings-reset]"))) return;
            setEditing(false);
          }} />
        <span id={`${id}-unit`} className="text-[13px] text-muted-foreground">{tr("minutes")}</span>
      </div>
    </SettingsRow> : null}
  </>;
}
