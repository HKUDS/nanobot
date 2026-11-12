import { channelValidationMessage } from "./validationMessages";
import {
  Suspense,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import {
  Check,
  ChevronDown,
  Clipboard,
  Loader2,
  Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiContribution } from "@/channel-plugins/registry";
import type {
  ChannelFeatureAction,
  ChannelPluginConnectFlowProps,
} from "@/channel-plugins/types";
import { ToggleButton } from "@/components/settings/ToggleButton";
import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import {
  type ChannelProviderPreset,
  type ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import {
  ChannelFieldGroups,
  channelRequirementErrors,
  channelServerValidationErrors,
  focusFirstChannelFieldError,
} from "@/components/settings/channels/ChannelCredentialFields";
import {
  CredentialForm,
  channelValuesForSubmit,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  ChannelLogo,
  ChannelRuntimeError,
  CHANNEL_SETUP_PANEL_CLASS_NAME,
  channelSetup,
  channelToggleChecked,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import {
  ChannelProviderPresets,
  ChannelSetupActions,
} from "@/components/settings/channels/ChannelSetupParts";
import { ChannelValidationProgress } from "@/components/settings/channels/ChannelValidationProgress";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import { Button } from "@/components/ui/button";
import {
  configureChannel,
  disableNanobotFeature,
  validateChannel,
} from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import type {
  ChannelValidationPayload,
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

export function ChannelSetupPanel({
  token,
  feature,
  actionKey,
  showBrandLogos,
  onAction,
  onFeaturesUpdate,
  connectRequestId = 0,
  onBeforeCloseChange,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  actionKey: string | null;
  showBrandLogos: boolean;
  onAction: ChannelFeatureAction;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  connectRequestId?: number;
  onBeforeCloseChange?: (handler: (() => Promise<boolean>) | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const uiContribution = channelUiContribution(feature.name, feature.webui);
  const PluginPanel = uiContribution?.Panel;
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const missingSupport = !feature.installed;
  if (PluginPanel && !missingSupport) {
    return (
      <Suspense fallback={<ChannelPluginLoading />}>
        <PluginPanel
          connectRequestId={connectRequestId}
          token={token}
          feature={feature}
          actionKey={actionKey}
          showBrandLogos={showBrandLogos}
          onAction={onAction}
          onFeaturesUpdate={onFeaturesUpdate}
        />
      </Suspense>
    );
  }
  if (feature.instances !== undefined && !missingSupport) {
    return (
      <ChannelInstancesPanel
        feature={feature}
        showBrandLogos={showBrandLogos}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    );
  }
  const enableBusy = actionKey === `enable:${feature.name}` || actionKey === `install:${feature.name}`;
  const anyActionBusy = Boolean(actionKey);
  const installSupportLabel = tx("settings.channels.install", "Install");

  const header = (
    <div className="flex min-w-0 items-center gap-3">
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <h3 className="sr-only">{displayName}</h3>
      {missingSupport && feature.install_supported ? (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={anyActionBusy}
          onClick={() => onAction("enable", feature.name, { installOnly: true, confirmed: true })}
          className="h-8 rounded-full px-3 text-[12px] font-semibold"
        >
          {enableBusy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {installSupportLabel}
        </Button>
      ) : null}
    </div>
  );

  return (
    <aside className={CHANNEL_SETUP_PANEL_CLASS_NAME}>
      {missingSupport ? <>
        <div className="pe-20">{header}</div>
        <ChannelRuntimeError message={feature.runtime_error} className="mt-4" />
      </> : <ChannelSetupSurface
        key={feature.name}
        header={header}
        token={token}
        feature={feature}
        setup={setup}
        connectRequestId={connectRequestId}
        ConnectFlow={uiContribution?.ConnectFlow}
        onFeaturesUpdate={onFeaturesUpdate}
        onBeforeCloseChange={onBeforeCloseChange}
      />}
    </aside>
  );
}

function ChannelSetupSurface({
  header,
  token,
  feature,
  setup,
  connectRequestId,
  ConnectFlow,
  onFeaturesUpdate,
  onBeforeCloseChange,
}: {
  header: ReactNode;
  token: string;
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  connectRequestId: number;
  ConnectFlow?: ComponentType<ChannelPluginConnectFlowProps>;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  onBeforeCloseChange?: (handler: (() => Promise<boolean>) | null) => void;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [autoSaving, setAutoSaving] = useState(false);
  const [autoSaveState, setAutoSaveState] = useState<"idle" | "saved">("idle");
  const autoSavePromiseRef = useRef<Promise<boolean> | null>(null);
  const [validating, setValidating] = useState(false);
  const [pendingEnabled, setPendingEnabled] = useState<boolean | null>(null);
  const actionPending = saving || autoSaving || validating || pendingEnabled !== null;
  const [validation, setValidation] = useState<ChannelValidationPayload | null>(null);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [touchedFields, setTouchedFields] = useState<Set<string>>(() => new Set());
  const [clearedSecrets, setClearedSecrets] = useState<Set<string>>(() => new Set());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const advancedPanelId = useId();
  const configValuesKey = JSON.stringify(feature.config_values ?? {});
  const configuredFields = useMemo(
    () => new Set(feature.configured_fields ?? []),
    [feature.configured_fields],
  );
  const mode = setup.mode ?? "credentials";
  const fields = setup.fields ?? [];
  const secretFieldKeys = useMemo(
    () => new Set(fields.filter((field) => field.secret).map((field) => field.key)),
    [fields],
  );
  const requirementKeys = new Set(
    (setup.requirements ?? []).flatMap((requirement) => requirement.alternatives.flat()),
  );
  const primaryFields = fields.filter(
    (field) => !field.optional || requirementKeys.has(field.key),
  );
  const manualFields = setup.manualFields ?? [];
  const advancedFields = mode === "connect"
    ? manualFields
    : fields.filter((field) => !primaryFields.includes(field));
  const editableFields = mode === "credentials" ? fields : mode === "connect" ? manualFields : [];
  const savedSecretFields = editableFields.filter(
    (field) => field.secret && configuredFields.has(field.key),
  );
  const availablePresets = feature.configured ? [] : setup.presets ?? [];
  const hasAdvanced = advancedFields.length > 0
    || savedSecretFields.length > 0
    || availablePresets.length > 0;
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    defaultChannelFieldValues(editableFields, feature.config_values),
  );

  useEffect(() => {
    setNotice(null);
    setVisibleSecrets({});
    setSaving(false);
    setValidating(false);
    setValidation(null);
    setTouchedFields(new Set());
    setClearedSecrets(new Set());
    setFieldErrors({});
    setFieldValues(defaultChannelFieldValues(editableFields, feature.config_values));
  }, [configValuesKey, feature.name]);

  const toggleSecret = (key: string) => {
    setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
  };

  const setFieldValue = (key: string, value: string) => {
    setFieldValues((current) => ({ ...current, [key]: value }));
    setTouchedFields((current) => new Set(current).add(key));
    setClearedSecrets((current) => {
      if (!current.has(key)) return current;
      const next = new Set(current);
      next.delete(key);
      return next;
    });
    setFieldErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    setAutoSaveState("idle");
  };

  const saveConnectionSettings = async () => {
    if (mode !== "connect" || saving || !touchedFields.size) return;
    setSaving(true);
    try {
      const payload = await configureChannel(client, feature.name,
        channelValuesForSubmit(editableFields, fieldValues, touchedFields, clearedSecrets));
      setTouchedFields(new Set());
      if (payload.nanobot_features) onFeaturesUpdate(payload.nanobot_features);
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const setSecretCleared = (key: string, clear: boolean) => {
    setClearedSecrets((current) => {
      const next = new Set(current);
      if (clear) next.add(key);
      else next.delete(key);
      return next;
    });
    setAutoSaveState("idle");
  };

  const applyPreset = (preset: ChannelProviderPreset) => {
    const values = Object.fromEntries(
      Object.entries(preset.values).filter(([key]) => !(fieldValues[key] ?? "").trim()),
    );
    if (!Object.keys(values).length) return;
    setFieldValues((current) => ({ ...current, ...values }));
    setTouchedFields((current) => {
      const next = new Set(current);
      for (const key of Object.keys(values)) next.add(key);
      return next;
    });
    setAutoSaveState("idle");
  };

  const credentialDirty = touchedFields.size > 0 || clearedSecrets.size > 0;
  const touchedSecret = fields.some(
    (field) => field.secret && touchedFields.has(field.key),
  );
  const saveCredentialDraft = useCallback(async (): Promise<boolean> => {
    const activeSave = autoSavePromiseRef.current;
    if (activeSave) return activeSave;
    if (mode !== "credentials" || !credentialDirty) return true;
    if (saving || validating || pendingEnabled !== null) return false;

    const values = channelValuesForSubmit(fields, fieldValues, touchedFields, clearedSecrets);
    const save = (async () => {
      setAutoSaving(true);
      setAutoSaveState("idle");
      setNotice(null);
      try {
        const payload = await configureChannel(client, feature.name, values);
        setTouchedFields(new Set());
        setClearedSecrets(new Set());
        setAutoSaveState("saved");
        if (payload.nanobot_features) onFeaturesUpdate(payload.nanobot_features);
        return true;
      } catch (err) {
        setNotice((err as Error).message);
        return false;
      } finally {
        setAutoSaving(false);
      }
    })();
    autoSavePromiseRef.current = save;
    const saved = await save;
    if (autoSavePromiseRef.current === save) autoSavePromiseRef.current = null;
    return saved;
  }, [
    clearedSecrets,
    client,
    credentialDirty,
    feature.name,
    fieldValues,
    fields,
    mode,
    onFeaturesUpdate,
    pendingEnabled,
    saving,
    touchedFields,
    validating,
  ]);
  const saveSecretOnBlur = (key: string) => {
    if (secretFieldKeys.has(key)) void saveCredentialDraft();
  };

  useAutoSave(
    { fieldValues, touchedFields: [...touchedFields], clearedSecrets: [...clearedSecrets] },
    mode === "credentials" && credentialDirty,
    actionPending,
    () => void saveCredentialDraft(),
    !touchedSecret,
  );

  useEffect(() => {
    if (autoSaveState !== "saved") return;
    const timeout = window.setTimeout(() => setAutoSaveState("idle"), 1500);
    return () => window.clearTimeout(timeout);
  }, [autoSaveState]);

  useEffect(() => {
    if (!onBeforeCloseChange) return;
    onBeforeCloseChange(credentialDirty ? saveCredentialDraft : null);
    return () => onBeforeCloseChange(null);
  }, [credentialDirty, onBeforeCloseChange, saveCredentialDraft]);

  const copyCommand = () => {
    if (!setup.command) return;
    void copyTextToClipboard(setup.command).then((ok) => {
      setNotice(
        ok
          ? tx("settings.channels.commandCopied", "Command copied.")
          : tx("settings.channels.commandCopyFailed", "Could not copy command."),
      );
    });
  };

  const saveCredentialSettings = async () => {
    if (actionPending) return;
    const errors = channelRequirementErrors(
      fields,
      setup.requirements ?? [],
      fieldValues,
      configuredFields,
      clearedSecrets,
      tx("settings.channels.fieldRequired", "Required to complete setup."),
    );
    if (Object.keys(errors).length) {
      setFieldErrors(errors);
      setNotice(tx("settings.channels.validationFailed", "Check the required setup before enabling."));
      focusFirstChannelFieldError(errors);
      return;
    }
    setPendingEnabled(true);
    setSaving(true);
    setValidating(true);
    setNotice(null);
    const values = channelValuesForSubmit(fields, fieldValues, touchedFields, clearedSecrets);
    try {
      const validationPayload = await validateChannel(client, feature.name, values);
      setValidation(validationPayload);
      if (!validationPayload.can_enable) {
        const errors = channelServerValidationErrors(
          fields,
          validationPayload.missing_fields,
          tx("settings.channels.fieldRequired", "Required to complete setup."),
        );
        setFieldErrors(errors);
        if (advancedFields.some((field) => errors[field.key])) setAdvancedOpen(true);
        focusFirstChannelFieldError(errors);
        setNotice(
          (validationPayload.message ? channelValidationMessage(validationPayload.message, t) : undefined)
            ?? tx("settings.channels.validationFailed", "Check the required setup before enabling."),
        );
        return;
      }
      const payload = await configureChannel(
        client,
        feature.name,
        values,
        { enable: true },
      );
      if (payload.nanobot_features) {
        onFeaturesUpdate(payload.nanobot_features);
      }
      setNotice(tx("settings.channels.checkedAndEnabled", "Checked and enabled."));
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSaving(false);
      setValidating(false);
      setPendingEnabled(null);
    }
  };

  const checkCurrentSettings = async () => {
    if (actionPending) return;
    setValidating(true);
    setValidation(null);
    setNotice(null);
    try {
      const payload = await validateChannel(
        client,
        feature.name,
        channelValuesForSubmit(fields, fieldValues, touchedFields, clearedSecrets),
      );
      setValidation(payload);
      const failedCheck = payload.checks.find((check) => check.status === "fail");
      const resultMessage = failedCheck?.message ?? payload.message;
      const localizedResult = resultMessage ? channelValidationMessage(resultMessage, t) : null;
      const localizedRuntimeError = feature.runtime_error
        ? channelValidationMessage(feature.runtime_error, t)
        : null;
      setNotice(
        payload.status !== "connected"
          && localizedResult
          && localizedResult !== localizedRuntimeError
          ? localizedResult
          : null,
      );
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setValidating(false);
    }
  };

  const enabled = pendingEnabled ?? channelToggleChecked(feature);
  const toggleEnabled = async (next: boolean) => {
    if (actionPending) return;
    if (next) {
      await saveCredentialSettings();
      return;
    }
    setPendingEnabled(false);
    setSaving(true);
    setNotice(null);
    try {
      onFeaturesUpdate(await disableNanobotFeature(client, feature.name));
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSaving(false);
      setPendingEnabled(null);
    }
  };

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
            onClick={() => setAdvancedOpen((current) => !current)}
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

          {mode === "connect" && ConnectFlow ? (
            <Suspense fallback={<ChannelPluginLoading compact />}>
              <ConnectFlow
                token={token}
                feature={feature}
                idleLabel={setup.primaryActionLabel ?? tx("settings.channels.connect", "Connect")}
                connectRequestId={connectRequestId}
                onFeaturesUpdate={onFeaturesUpdate}
              />
            </Suspense>
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

function ChannelPluginLoading({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className={cn(
        "flex items-center justify-center gap-2 text-sm text-muted-foreground",
        compact
          ? "min-h-12"
          : `${CHANNEL_SETUP_PANEL_CLASS_NAME} min-h-48`,
      )}
    >
      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {t("settings.status.loading")}
    </div>
  );
}
