import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SettingsGroup, SettingsSectionTitle, RestartSettingsFooter } from "@/components/settings/shared/SettingsControls";
import type { DreamPromptSettings as DreamPromptPayload, SettingsPayload } from "@/lib/types";
import type { NanobotClient } from "@/lib/nanobot-client";
import { updateDreamPrompt } from "@/lib/api";

export function useDreamPromptSettings(settings: SettingsPayload | null, client: NanobotClient, apply: (payload: DreamPromptPayload) => void) {
  const [draft, setDraft] = useState<string | null | undefined>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const data = settings?.dream_prompt;
  const content = draft === null ? data?.default_content ?? "" : draft ?? data?.content ?? "";
  const dirty = draft === null ? !!data?.custom : draft !== undefined && draft !== data?.content;
  const change = (next: string | null | undefined) => { setDraft(next); setError(""); setSaved(false); };
  const save = async () => {
    if (!settings || !data || !dirty || saving) return;
    setSaving(true); setError("");
    try {
      const payload = await updateDreamPrompt(client, draft === null ? null : content);
      apply(payload);
      setDraft(undefined); setSaved(true);
    } catch (err) { setError((err as Error).message); }
    finally { setSaving(false); }
  };
  const saveLatest = useRef(save);
  saveLatest.current = save;
  useEffect(() => {
    if (!dirty || saving || error || !content.trim() || content.length > 32000) return;
    const timer = window.setTimeout(() => void saveLatest.current(), 800);
    return () => window.clearTimeout(timer);
  }, [content, dirty, saving, error]);
  return { data, content, dirty, saving, error, saved, change, save };
}

export function DreamPromptSettings({ state }: { state: ReturnType<typeof useDreamPromptSettings> }) {
  const { t } = useTranslation();
  const tr = (key: string) => t(`settings.dreamPrompt.${key}`);
  if (!state.data) return null;
  const invalid = !state.content.trim() || state.content.length > 32000;
  return <section aria-label={tr("title")}>
    <SettingsSectionTitle>{tr("title")}</SettingsSectionTitle>
    <SettingsGroup>
      <div className="settings-editor space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label htmlFor="dream-prompt" className="text-[14px] font-medium">{tr("label")}</label>
          <Button type="button" size="sm" variant="ghost" className="rounded-full"
            disabled={state.saving || !state.data.editable || (!state.data.custom && !state.dirty)}
            onClick={() => state.change(null)}>{tr("restore")}</Button>
        </div>
        <p id="dream-prompt-help" className="text-[12px] leading-5 text-muted-foreground">{tr("help")}</p>
        <p className="break-all text-[12px] text-muted-foreground">{tr("workspace")}: {state.data.workspace}</p>
        <Textarea id="dream-prompt" value={state.content} rows={14}
          aria-describedby="dream-prompt-help dream-prompt-status" aria-invalid={invalid || !!state.error || undefined}
          disabled={state.saving || !state.data.editable} spellCheck={false}
          className="resize-y rounded-xl text-[13px] leading-6"
          onChange={(event) => state.change(event.target.value)} />
        <p id="dream-prompt-status" role={state.error || invalid ? "alert" : "status"}
          className={state.error || invalid ? "text-[12px] text-destructive" : "text-[12px] text-muted-foreground"}>
          {state.error || (!state.data.editable ? tr("unreadable") : invalid ? tr("invalid") : `${state.content.length} / 32000`)}
        </p>
      </div>
      <RestartSettingsFooter autoSave={!state.error} dirty={state.dirty} saving={state.saving} pendingRestart={false}
        disabled={invalid || !state.data.editable} message={state.saved ? tr("saved") : undefined}
        onSave={() => void state.save()} onReset={() => state.change(undefined)} />
    </SettingsGroup>
  </section>;
}
