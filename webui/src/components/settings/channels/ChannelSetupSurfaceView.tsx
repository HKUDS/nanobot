import type { ReactNode } from "react";
import { Check, ChevronDown, Clipboard, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/ui/toggle-button";
import type { ChannelConfigField, ChannelProviderPreset, ChannelSetupPresentation } from "@/channel-plugins/catalog";
import { ChannelFieldGroups } from "./ChannelCredentialFields";
import { CredentialForm } from "./CredentialForm";
import { ChannelRuntimeError } from "./ChannelIdentity";
import { ChannelProviderPresets, ChannelSetupActions } from "./ChannelSetupParts";
import { ChannelValidationProgress } from "./ChannelValidationProgress";
import { Button } from "@/components/ui/button";
import type { ChannelValidationPayload, NanobotFeatureInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ChannelSetupSurfaceViewProps {
  header: ReactNode;
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  primaryFields: ChannelConfigField[];
  advancedFields: ChannelConfigField[];
  savedSecretFields: ChannelConfigField[];
  availablePresets: ChannelProviderPreset[];
  configuredFields: Set<string>;
  fieldValues: Record<string, string>;
  visibleSecrets: Record<string, boolean>;
  clearedSecrets: Set<string>;
  fieldErrors: Record<string, string>;
  actionPending: boolean;
  enabled: boolean;
  autoSaving: boolean;
  autoSaveState: "idle" | "saved";
  advancedOpen: boolean;
  advancedPanelId: string;
  validation: ChannelValidationPayload | null;
  validating: boolean;
  notice: string | null;
  connectFlow?: ReactNode;
  onAdvancedOpenChange: (open: boolean) => void;
  onChangeField: (key: string, value: string) => void;
  onFieldBlur: (key: string) => void;
  onToggleSecret: (key: string) => void;
  onClearSecret: (key: string, clear: boolean) => void;
  onApplyPreset: (preset: ChannelProviderPreset) => void;
  onSubmit: () => void;
  onCheckConnection: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onSaveConnectionSettings: () => void;
  onCopyCommand: () => void;
  onNotice: (notice: string | null) => void;
}

export function ChannelSetupSurfaceView({
  header, feature, setup, primaryFields, advancedFields, savedSecretFields, availablePresets,
  configuredFields, fieldValues, visibleSecrets, clearedSecrets, fieldErrors, actionPending,
  enabled, autoSaving, autoSaveState, advancedOpen, advancedPanelId, validation, validating,
  notice, connectFlow, onAdvancedOpenChange,
  onChangeField: setFieldValue, onFieldBlur: saveSecretOnBlur, onToggleSecret: toggleSecret,
  onClearSecret: setSecretCleared, onApplyPreset: applyPreset, onSubmit: saveCredentialSettings,
  onCheckConnection: checkCurrentSettings, onToggleEnabled: toggleEnabled,
  onSaveConnectionSettings: saveConnectionSettings, onCopyCommand: copyCommand, onNotice: setNotice,
}: ChannelSetupSurfaceViewProps) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const mode = setup.mode ?? "credentials";
  const hasAdvanced = advancedFields.length > 0 || savedSecretFields.length > 0 || availablePresets.length > 0;
  const inlineActions = mode === "credentials" && primaryFields.length === 1
    && !advancedOpen && !setup.presets?.length && !setup.actions?.length;
  const credentialActions = mode === "credentials" ? (
    <div className="ms-auto flex min-h-10 flex-wrap items-center justify-end gap-x-3 gap-y-2 sm:min-h-9">
      {feature.setup?.verifies_connection ? (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="h-10 rounded-full px-3 text-[12px] font-semibold sm:h-9"
          onClick={() => void checkCurrentSettings()}
          disabled={actionPending}
        >
          {tx("settings.channels.checkConnection", "Check connection")}
        </Button>
      ) : null}
      <ToggleButton checked={enabled} disabled={actionPending}
        label={tx("settings.channels.enable", "Enable")}
        onChange={(next) => void toggleEnabled(next)} />
    </div>
  ) : null;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (mode === "credentials") void saveCredentialSettings();
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pe-20">
        {header}
        <div className="ms-auto flex min-h-8 items-center gap-2">
          <span
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className={cn(
              "inline-flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground",
              !autoSaving && autoSaveState !== "saved" && "sr-only",
            )}
          >
            {autoSaving ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                {tx("settings.actions.saving", "Saving")}
              </>
            ) : autoSaveState === "saved" ? (
              <>
                <Check className="h-3 w-3" aria-hidden />
                {tx("settings.channels.savedSettings", "Settings saved.")}
              </>
            ) : null}
          </span>
        {hasAdvanced ? (
          <button
            type="button"
            className="inline-flex min-h-8 items-center gap-1.5 rounded px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-offset-2"
            aria-expanded={advancedOpen}
            aria-controls={advancedPanelId}
            onClick={() => onAdvancedOpenChange(!advancedOpen)}
          >
            {tx("settings.channels.advanced", "Advanced")}
            <ChevronDown className={cn(
              "h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
              advancedOpen && "rotate-180",
            )} aria-hidden />
          </button>
        ) : null}
        </div>
      </div>
      <ChannelRuntimeError message={feature.runtime_error} />
      <div className="flex flex-wrap items-center gap-4">
        <section className={cn("min-w-0", inlineActions ? "flex-[1_1_20rem]" : "w-full")}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex max-w-full flex-wrap justify-end gap-2">
              {mode === "webui" ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11.5px] font-medium text-emerald-700 dark:text-emerald-200">
                  <Check className="h-3.5 w-3.5" aria-hidden />
                  {tx("settings.channels.managedByWebui", "Managed by WebUI")}
                </span>
              ) : null}
            </div>
          </div>
          <ChannelSetupActions feature={feature} setup={setup} onNotice={setNotice} />

          {mode === "connect" && connectFlow ? (
            connectFlow
          ) : mode === "connect" ? (
            <>
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-8 rounded-full bg-background/80 px-3 text-[12px] font-semibold settings-hover"
                  onClick={() =>
                    setNotice(
                      tx(
                        "settings.channels.connectPreview",
                        "Run the command below in your terminal to connect.",
                      ),
                    )
                  }
                >
                  {setup.primaryActionLabel ?? tx("settings.channels.connect", "Connect")}
                </Button>
                {setup.command ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-8 rounded-full px-3 text-[12px] font-semibold"
                    onClick={copyCommand}
                  >
                    <Clipboard className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                    {tx("settings.channels.copyCommand", "Copy command")}
                  </Button>
                ) : null}
              </div>
              {setup.command ? (
                <code className="mt-3 block rounded-control border border-border/50 bg-muted/45 px-2.5 py-2 font-mono text-[11px] leading-5 text-foreground">
                  {setup.command}
                </code>
              ) : null}
            </>
          ) : mode === "credentials" ? (
            <>
              {primaryFields.length ? (
                <ChannelFieldGroups
                  fields={primaryFields}
                  values={fieldValues}
                  configuredFields={configuredFields}
                  visibleSecrets={visibleSecrets}
                  onChange={setFieldValue}
                  onFieldBlur={saveSecretOnBlur}
                  onToggleSecret={toggleSecret}
                  errors={fieldErrors}
                  clearedSecrets={clearedSecrets}
                  onClearSecret={setSecretCleared}
                  requirements={setup.requirements ?? []}
                  sectionLabels={setup.sectionLabels}
                  disabled={actionPending}
                />
              ) : null}
            </>
          ) : null}
        </section>

        {hasAdvanced ? (
          <div id={advancedPanelId} hidden={!advancedOpen} className="min-w-0 w-full space-y-3 text-[12px] leading-5 text-muted-foreground">
            {availablePresets.length ? (
              <ChannelProviderPresets
                presets={availablePresets}
                onApply={applyPreset}
                label={setup.presetLabel}
                disabled={actionPending}
              />
            ) : null}
            <div className="space-y-2">
              {savedSecretFields.filter((field) => !(fieldValues[field.key] ?? "").trim()).map((field) => (
                <div key={field.key} className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span>{field.label}</span>
                  <button type="button" className="min-h-8 text-[12px] hover:text-foreground"
                    onClick={() => setSecretCleared(field.key, !clearedSecrets.has(field.key))}>
                    {clearedSecrets.has(field.key)
                      ? tx("settings.channels.keepSavedSecret", "Keep saved credential")
                      : tx("settings.channels.removeSavedSecret", "Remove saved credential")}
                  </button>
                </div>
              ))}
            </div>
            {advancedFields.length ? (
              <div onBlur={() => void saveConnectionSettings()}>
                <CredentialForm
                  fields={advancedFields}
                  values={fieldValues}
                  configuredFields={configuredFields}
                  visibleSecrets={visibleSecrets}
                  onChange={setFieldValue}
                  onFieldBlur={saveSecretOnBlur}
                  onToggleSecret={toggleSecret}
                  errors={fieldErrors}
                  clearedSecrets={clearedSecrets}
                  onClearSecret={setSecretCleared}
                  compact
                  disabled={actionPending}
                />
              </div>
            ) : null}
          </div>
        ) : null}
        {credentialActions}
      </div>
      {mode === "credentials" && feature.setup?.verifies_connection
        && (validation || validating) ? (
        <div>
          <ChannelValidationProgress
            validation={validation}
            validating={validating}
            feature={feature}
          />
        </div>
      ) : null}
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "rounded-control bg-muted/55 px-3 py-2.5 text-[12px] leading-5 text-muted-foreground",
          !notice && "sr-only",
        )}
      >
        {notice ?? ""}
      </div>
    </form>
  );
}
