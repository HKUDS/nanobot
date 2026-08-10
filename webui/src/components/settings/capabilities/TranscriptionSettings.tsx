import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import { ProviderPicker } from "@/components/settings/shared/ModelControls";
import {
  NumberInput,
  RestartSettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SettingsPayload, TranscriptionSettingsUpdate } from "@/lib/types";

export const DEFAULT_TRANSCRIPTION_FORM: TranscriptionSettingsUpdate = {
  enabled: true,
  provider: "groq",
  model: "",
  language: "",
  maxDurationSec: 120,
  maxUploadMb: 25,
};

export const DEFAULT_TRANSCRIPTION_SETTINGS: NonNullable<SettingsPayload["transcription"]> = {
  enabled: true,
  provider: "groq",
  provider_configured: false,
  model: "whisper-large-v3",
  language: null,
  max_duration_sec: 120,
  max_upload_mb: 25,
  providers: [],
};

export function transcriptionFormFromPayload(payload: SettingsPayload): TranscriptionSettingsUpdate {
  const transcription = payload.transcription ?? DEFAULT_TRANSCRIPTION_SETTINGS;
  return {
    enabled: transcription.enabled,
    provider: transcription.provider,
    model: transcription.model,
    language: transcription.language ?? "",
    maxDurationSec: transcription.max_duration_sec,
    maxUploadMb: transcription.max_upload_mb,
  };
}

export function TranscriptionSettings({
  settings,
  form,
  dirty,
  saving,
  onChangeForm,
  onSave,
  onOpenProviders,
  showBrandLogos,
  onRestart,
  isRestarting,
  requiresRestartPending,
}: {
  settings: SettingsPayload;
  form: TranscriptionSettingsUpdate;
  dirty: boolean;
  saving: boolean;
  onChangeForm: Dispatch<SetStateAction<TranscriptionSettingsUpdate>>;
  onSave: () => void;
  onOpenProviders: () => void;
  showBrandLogos: boolean;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const transcription = settings.transcription ?? DEFAULT_TRANSCRIPTION_SETTINGS;
  const selectedProvider =
    transcription.providers.find((provider) => provider.name === form.provider) ??
    transcription.providers[0];
  const providerConfigured = !!selectedProvider?.configured;

  return (
    <section>
      <SettingsSectionTitle>{tx("settings.sections.voiceInput", "Voice input")}</SettingsSectionTitle>
      <SettingsGroup>
        <SettingsRow
          title={tx("settings.rows.transcription", "Transcription")}
          description={tx("settings.help.transcription", "Transcribe microphone input before sending it. Chat channel voice messages use the same settings.")}
        >
          <ToggleButton
            checked={form.enabled}
            onChange={(enabled) => onChangeForm((prev) => ({ ...prev, enabled }))}
            ariaLabel={tx("settings.rows.transcription", "Transcription")}
            label={form.enabled ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
          />
        </SettingsRow>
        <SettingsRow title={tx("settings.rows.transcriptionProvider", "Provider")}>
          <ProviderPicker
            providers={transcription.providers}
            value={form.provider}
            emptyLabel={tx("settings.voice.selectProvider", "Select provider")}
            showProviderLogos={showBrandLogos}
            onChange={(provider) => onChangeForm((prev) => ({ ...prev, provider }))}
          />
        </SettingsRow>
        <SettingsRow
          title={tx("settings.rows.transcriptionProviderStatus", "Provider status")}
          description={tx("settings.help.transcriptionProviderStatus", "API keys stay under providers, not in transcription settings.")}
        >
          <div className="flex flex-wrap items-center justify-end gap-2">
            <StatusPill tone={providerConfigured ? "success" : "neutral"}>
              {providerConfigured
                ? tx("settings.values.configured", "Configured")
                : tx("settings.values.notConfigured", "Not configured")}
            </StatusPill>
            {!providerConfigured ? (
              <Button size="sm" variant="outline" onClick={onOpenProviders} className="rounded-full">
                {tx("settings.voice.configureProvider", "Configure provider")}
              </Button>
            ) : null}
          </div>
        </SettingsRow>
        <SettingsRow
          title={tx("settings.rows.transcriptionModel", "Model")}
          description={tx("settings.help.transcriptionModel", "Leave as the resolved default unless your provider needs a custom model id.")}
        >
          <Input
            value={form.model}
            onChange={(event) => onChangeForm((prev) => ({ ...prev, model: event.target.value }))}
            className="h-8 w-[min(300px,70vw)] rounded-full text-[13px]"
          />
        </SettingsRow>
        <SettingsRow
          title={tx("settings.rows.transcriptionLanguage", "Language")}
          description={tx("settings.help.transcriptionLanguage", "Optional ISO-639 hint such as en, zh, ja, or ko.")}
        >
          <Input
            value={form.language}
            onChange={(event) => onChangeForm((prev) => ({ ...prev, language: event.target.value }))}
            placeholder={tx("settings.voice.languageAuto", "Auto")}
            className="h-8 w-[min(180px,60vw)] rounded-full text-[13px]"
          />
        </SettingsRow>
        <SettingsRow title={tx("settings.rows.voiceLimits", "Limits")}>
          <div className="flex flex-wrap justify-end gap-2">
            <NumberInput
              value={form.maxDurationSec}
              min={1}
              max={600}
              suffix="s"
              onChange={(maxDurationSec) => onChangeForm((prev) => ({ ...prev, maxDurationSec }))}
            />
            <NumberInput
              value={form.maxUploadMb}
              min={1}
              max={100}
              suffix="MB"
              onChange={(maxUploadMb) => onChangeForm((prev) => ({ ...prev, maxUploadMb }))}
            />
          </div>
        </SettingsRow>
        <RestartSettingsFooter
          dirty={dirty}
          saving={saving}
          pendingRestart={requiresRestartPending}
          dirtyMessage={tx("settings.status.restartAfterSaving", "Save changes, then restart when ready.")}
          pendingMessage={tx("settings.status.savedRestartApply", "Saved. Restart when ready.")}
          onSave={onSave}
          onRestart={onRestart}
          isRestarting={isRestarting}
        />
      </SettingsGroup>
    </section>
  );
}
