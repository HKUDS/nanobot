import { channelValidationMessage } from "./validationMessages";
import {
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";
import {
  Check,
  ChevronDown,
  Clipboard,
  Download,
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
import {
  type ChannelConfigField,
  type ChannelFieldSection,
  type ChannelProviderPreset,
  type ChannelSetupPresentation,
  type ChannelSetupRequirement,
} from "@/components/settings/channels/catalog";
import {
  CredentialForm,
  channelValuesForSubmit,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  ChannelLogo,
  ChannelRuntimeError,
  ChannelStatusBadge,
  channelSetup,
  channelStatusLabel,
  channelToggleChecked,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import {
  ChannelProviderPresets,
  ChannelSetupActions,
  ChannelValidationBadge,
  ChannelValidationChecks,
  ChannelValidationDetails,
} from "@/components/settings/channels/ChannelSetupParts";
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

export function ChannelCatalogRow({
  feature,
  showBrandLogos,
  onSelect,
  actionKey,
  onAction,
}: {
  feature: NanobotFeatureInfo;
  showBrandLogos: boolean;
  onSelect: (connect?: boolean) => void;
  actionKey: string | null;
  onAction: ChannelFeatureAction;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const alwaysEnabled = feature.capabilities?.includes("always_enabled") ?? false;
  const pendingChecked = actionKey === `enable:${feature.name}` ? true
    : actionKey === `disable:${feature.name}` ? false : null;
  const ownActionBusy = pendingChecked !== null || actionKey === `install:${feature.name}`;
  const checked = alwaysEnabled || (pendingChecked ?? channelToggleChecked(feature));
  const anyActionBusy = Boolean(actionKey);
  const installButtonRef = useRef<HTMLButtonElement | null>(null);
  const [installHint, setInstallHint] = useState(false);

  useEffect(() => {
    if (!installHint) return;
    const timeout = window.setTimeout(() => setInstallHint(false), 1400);
    return () => window.clearTimeout(timeout);
  }, [installHint]);

  const pointToInstall = () => {
    setInstallHint(true);
    installButtonRef.current?.focus();
  };
  const channelIdentity = (
    <>
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
          {displayName}
        </h3>
      </div>
    </>
  );

  return (
    <div className={cn(
      "settings-list-row flex min-w-0 items-center gap-3 py-2.5 transition-colors",
      !alwaysEnabled && "settings-hover",
    )}>
      {alwaysEnabled ? (
        <div className="flex min-w-0 flex-1 select-none items-center gap-3">
          {channelIdentity}
        </div>
      ) : (
        <button
          type="button"
          aria-label={t("settings.channels.selectChannel", {
            name: displayName,
            defaultValue: "View {{name}} settings",
          })}
          aria-haspopup="dialog"
          onClick={() => feature.installed ? onSelect() : pointToInstall()}
          className="group flex min-w-0 flex-1 select-none items-center gap-3 rounded-control text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border/80"
        >
          {channelIdentity}
        </button>
      )}
      {feature.runtime_status === "failed" ? (
        <div className="min-w-0 shrink truncate">
        <ChannelStatusBadge status={feature.runtime_status}>
          {channelStatusLabel(feature, tx)}
        </ChannelStatusBadge>
        </div>
      ) : null}
      <div className="flex w-16 shrink-0 items-center justify-center">
        {!feature.installed ? (
          <Button ref={installButtonRef} type="button" variant="outline" size="icon"
            className={cn(
              "h-[22px] w-[38px] min-w-0 shrink-0 rounded-full border-border/70 bg-background p-0 shadow-sm settings-hover active:scale-[0.96]",
              installHint && "border-[#2997FF]/60 bg-[#2997FF]/10 text-[#087FE7] ring-2 ring-[#2997FF]/25 ring-offset-2",
            )}
            disabled={anyActionBusy || !feature.install_supported}
            aria-label={t("settings.channels.installChannel", { name: displayName })}
            onClick={() => {
              setInstallHint(false);
              onAction("enable", feature.name, { installOnly: true, confirmed: true });
            }}>
            {ownActionBusy
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              : <Download className="h-3.5 w-3.5" aria-hidden />}
            <span className="sr-only">{tx("settings.channels.install", "Install")}</span>
          </Button>
        ) : (
          <ToggleButton checked={checked}
            label={checked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            disabled={alwaysEnabled || anyActionBusy}
            ariaLabel={t("settings.channels.toggleChannel", { name: displayName, defaultValue: "{{name}} channel" })}
            onChange={(enabled) => {
              if (enabled && feature.configured === false) onSelect(true);
              else onAction(enabled ? "enable" : "disable", feature.name);
            }} />
        )}
      </div>
    </div>
  );
}

export function ChannelSetupPanel({
  token,
  feature,
  actionKey,
  showBrandLogos,
  onAction,
  onFeaturesUpdate,
  connectRequestId = 0,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  actionKey: string | null;
  showBrandLogos: boolean;
  onAction: ChannelFeatureAction;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
  connectRequestId?: number;
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

  return (
    <aside className="rounded-panel bg-background p-6">
      <div className="flex items-start justify-between gap-4 pr-16">
        <div className="flex min-w-0 max-w-full items-center gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="sr-only">
              {displayName}
            </h3>
            {missingSupport && feature.install_supported ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={anyActionBusy}
                onClick={() => onAction("enable", feature.name, { installOnly: true, confirmed: true })}
                className="mt-2 h-8 rounded-full px-3 text-[12px] font-semibold"
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
        </div>
      </div>

      <ChannelRuntimeError message={feature.runtime_error} className="mt-4" />

      {!missingSupport ? <ChannelSetupSurface
        key={feature.name}
        token={token}
        feature={feature}
        setup={setup}
        connectRequestId={connectRequestId}
        ConnectFlow={feature.installed ? uiContribution?.ConnectFlow : undefined}
        onFeaturesUpdate={onFeaturesUpdate}
      /> : null}
    </aside>
  );
}

function ChannelSetupSurface({
  token,
  feature,
  setup,
  connectRequestId,
  ConnectFlow,
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  connectRequestId: number;
  ConnectFlow?: ComponentType<ChannelPluginConnectFlowProps>;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [pendingEnabled, setPendingEnabled] = useState<boolean | null>(null);
  const actionPending = saving || validating || pendingEnabled !== null;
  const [validation, setValidation] = useState<ChannelValidationPayload | null>(null);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [touchedFields, setTouchedFields] = useState<Set<string>>(() => new Set());
  const [clearedSecrets, setClearedSecrets] = useState<Set<string>>(() => new Set());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const configValuesKey = JSON.stringify(feature.config_values ?? {});
  const configuredFields = useMemo(
    () => new Set(feature.configured_fields ?? []),
    [feature.configured_fields],
  );
  const mode = setup.mode ?? "credentials";
  const fields = setup.fields ?? [];
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
  const hasAdvanced = advancedFields.length > 0 || savedSecretFields.length > 0;
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
  };

  const applyPreset = (preset: ChannelProviderPreset) => {
    setFieldValues((current) => ({ ...current, ...preset.values }));
    setTouchedFields((current) => {
      const next = new Set(current);
      for (const key of Object.keys(preset.values)) next.add(key);
      return next;
    });
  };

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
      setNotice(localizedResult && localizedResult !== localizedRuntimeError ? localizedResult : null);
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

  return (
    <form
      className="mt-5 space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (mode === "credentials") void saveCredentialSettings();
      }}
    >
      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex max-w-full flex-wrap justify-end gap-2">
            {mode !== "webui" && (validation || validating) ? (
              <ChannelValidationBadge
                validation={validation}
                validating={validating}
                feature={feature}
              />
            ) : null}
            {mode === "webui" ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11.5px] font-medium text-emerald-700 dark:text-emerald-200">
                <Check className="h-3.5 w-3.5" aria-hidden />
                {tx("settings.channels.managedByWebui", "Managed by WebUI")}
              </span>
            ) : null}
          </div>
        </div>
        {validation?.identity?.name ? <ChannelValidationDetails validation={validation} /> : null}
        <ChannelSetupActions feature={feature} setup={setup} onNotice={setNotice} />

        {mode === "connect" && !feature.installed ? null : mode === "connect" && ConnectFlow ? (
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
            {setup.presets?.length ? (
              <ChannelProviderPresets
                presets={setup.presets}
                onApply={applyPreset}
              />
            ) : null}
            {primaryFields.length ? (
              <ChannelFieldGroups
                fields={primaryFields}
                values={fieldValues}
                configuredFields={configuredFields}
                visibleSecrets={visibleSecrets}
                onChange={setFieldValue}
                onToggleSecret={toggleSecret}
                errors={fieldErrors}
                clearedSecrets={clearedSecrets}
                onClearSecret={setSecretCleared}
                requirements={setup.requirements ?? []}
                sectionLabels={setup.sectionLabels}
              />
            ) : null}
          </>
        ) : null}
      </section>

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

      {validation?.checks.length ? <ChannelValidationChecks validation={validation} /> : null}

      <div className="relative min-h-8">
        {mode === "credentials" ? (
            <div className="absolute end-0 top-0 flex h-8 items-center justify-end gap-3">
              {enabled && (touchedFields.size > 0 || clearedSecrets.size > 0) ? (
                <Button type="submit" size="sm" variant="secondary" disabled={actionPending}>
                  {tx("settings.actions.save", "Save")}
                </Button>
              ) : null}
              {feature.setup?.verifies_connection ? (
                <Button type="button" size="sm" variant="ghost"
                  className="h-8 rounded-full px-3 text-[12px] font-semibold"
                  onClick={() => void checkCurrentSettings()} disabled={actionPending}>
                  {validating ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                  {tx("settings.channels.checkOnly", "Check")}
                </Button>
              ) : null}
              <ToggleButton checked={enabled} disabled={actionPending}
                label={tx("settings.channels.enable", "Enable")}
                onChange={(next) => void toggleEnabled(next)} />
            </div>
        ) : null}
      {hasAdvanced ? (
        <details className="group text-[12px] leading-5 text-muted-foreground">
          <summary className="flex h-8 w-fit cursor-pointer list-none items-center text-[12px] text-muted-foreground transition-colors hover:text-foreground">
            <span className="inline-flex items-center gap-1.5">
              {tx("settings.channels.advanced", "Advanced")}
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden />
            </span>
          </summary>
          <div className="mt-3 space-y-2">
            {savedSecretFields.filter((field) => !(fieldValues[field.key] ?? "").trim()).map((field) => (
              <div key={field.key} className="flex min-h-9 items-center justify-between gap-4">
                <span>{field.label}</span>
                <button type="button" className="text-[12px] hover:text-foreground"
                  onClick={() => setSecretCleared(field.key, !clearedSecrets.has(field.key))}>
                  {clearedSecrets.has(field.key)
                    ? tx("settings.channels.keepSavedSecret", "Keep saved credential")
                    : tx("settings.channels.removeSavedSecret", "Remove saved credential")}
                </button>
              </div>
            ))}
          </div>
          {advancedFields.length ? (
            <div className="mt-3" onBlur={() => void saveConnectionSettings()}>
              <CredentialForm
                fields={advancedFields}
                values={fieldValues}
                configuredFields={configuredFields}
                visibleSecrets={visibleSecrets}
                onChange={setFieldValue}
                onToggleSecret={toggleSecret}
                errors={fieldErrors}
                clearedSecrets={clearedSecrets}
                onClearSecret={setSecretCleared}
                compact
              />
            </div>
          ) : null}
        </details>
      ) : null}
      </div>
    </form>
  );
}

const CHANNEL_FIELD_SECTION_ORDER: ChannelFieldSection[] = [
  "account",
  "credentials",
  "connection",
  "access",
  "behavior",
  "security",
];

function ChannelFieldGroups({
  fields,
  requirements,
  sectionLabels,
  ...formProps
}: {
  fields: ChannelConfigField[];
  requirements: ChannelSetupRequirement[];
  sectionLabels?: Record<string, string>;
  values: Record<string, string>;
  configuredFields: Set<string>;
  visibleSecrets: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onToggleSecret: (key: string) => void;
  errors: Record<string, string>;
  clearedSecrets: Set<string>;
  onClearSecret: (key: string, clear: boolean) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const labels = new Map(fields.map((field) => [field.key, field.label]));
  const compositeRequirements = requirements.filter(
    (requirement) => requirement.alternatives.length > 1,
  );
  const groups = new Map<string, ChannelConfigField[]>();
  for (const field of fields) {
    const section = field.section ?? "credentials";
    const current = groups.get(section) ?? [];
    current.push(field);
    groups.set(section, current);
  }
  const orderedSections = [
    ...CHANNEL_FIELD_SECTION_ORDER,
    ...[...groups.keys()].filter(
      (section) => !CHANNEL_FIELD_SECTION_ORDER.includes(section as ChannelFieldSection),
    ),
  ];

  return (
    <div className="space-y-5">
      {compositeRequirements.map((requirement, index) => (
        <div
          key={index}
          className="rounded-control border border-border/60 bg-background/55 px-3 py-2.5"
        >
          <div className="text-[11px] font-semibold text-foreground">
            {tx("settings.channels.chooseCredentialMethod", "Choose one credential method")}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            {requirement.alternatives.map((alternative, alternativeIndex) => (
              <span key={alternative.join("|")} className="contents">
                {alternativeIndex ? <span aria-hidden>{tx("settings.channels.or", "or")}</span> : null}
                <span className="rounded-full bg-muted px-2 py-0.5 text-foreground/85">
                  {alternative.map((key) => labels.get(key) ?? key.split(".").at(-1)).join(" + ")}
                </span>
              </span>
            ))}
          </div>
        </div>
      ))}
      {orderedSections.map((section) => {
        const sectionFields = groups.get(section);
        if (!sectionFields?.length) return null;
        return (
          <fieldset key={section} className="min-w-0 space-y-2">
            <legend className={groups.size === 1 ? "sr-only" : "mb-2 text-[12px] font-medium text-muted-foreground"}>
              {channelFieldSectionLabel(section, tx, sectionLabels)}
            </legend>
            <div className="rounded-control bg-settings-surface px-4 py-2">
              <CredentialForm fields={sectionFields} {...formProps} compact />
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}

function channelFieldSectionLabel(
  section: string,
  tx: (key: string, fallback: string) => string,
  sectionLabels?: Record<string, string>,
): string {
  const customLabel = sectionLabels?.[section];
  if (customLabel) return customLabel;

  const fallbacks: Record<ChannelFieldSection, string> = {
    account: "Account",
    credentials: "Credentials",
    connection: "Connection",
    access: "Access",
    behavior: "Behavior",
    security: "Security",
    advanced: "Advanced",
  };
  const fallback = fallbacks[section as ChannelFieldSection];
  if (fallback) return tx(`settings.channels.sections.${section}`, fallback);
  return section
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function channelRequirementErrors(
  fields: ChannelConfigField[],
  requirements: ChannelSetupRequirement[],
  values: Record<string, string>,
  configuredFields: Set<string>,
  clearedSecrets: Set<string>,
  message: string,
): Record<string, string> {
  const fieldByKey = new Map(fields.map((field) => [field.key, field]));
  const present = (key: string) => {
    const field = fieldByKey.get(key);
    if (!field || clearedSecrets.has(key)) return false;
    const value = (values[key] ?? "").trim();
    if (field.kind === "bool") return value === "true";
    if (value) return true;
    return Boolean(field.secret && configuredFields.has(key));
  };
  const errors: Record<string, string> = {};
  for (const requirement of requirements) {
    if (requirement.alternatives.some((alternative) => alternative.every(present))) continue;
    const closest = [...requirement.alternatives].sort(
      (left, right) => left.filter((key) => !present(key)).length - right.filter((key) => !present(key)).length,
    )[0] ?? [];
    for (const key of closest) {
      if (!present(key) && fieldByKey.has(key)) errors[key] = message;
    }
  }
  return errors;
}

function channelServerValidationErrors(
  fields: ChannelConfigField[],
  missingFields: string[],
  message: string,
): Record<string, string> {
  const missing = new Set(missingFields);
  return Object.fromEntries(
    fields
      .filter((field) => missing.has(field.key) || missing.has(field.key.split(".").at(-1) ?? ""))
      .map((field) => [field.key, message]),
  );
}

function focusFirstChannelFieldError(errors: Record<string, string>) {
  const key = Object.keys(errors)[0];
  if (!key) return;
  window.requestAnimationFrame(() => {
    document.getElementById(`channel-field-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`)?.focus();
  });
}

function ChannelPluginLoading({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className={cn(
        "flex items-center justify-center gap-2 text-sm text-muted-foreground",
        compact ? "min-h-12" : "min-h-48",
      )}
    >
      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {t("settings.status.loading")}
    </div>
  );
}
