import {
  Suspense,
  useEffect,
  useMemo,
  useState,
  type ComponentType,
} from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Loader2,
  Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiContribution } from "@/channel-plugins/registry";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
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
  channelDescription,
  channelRequirements,
  channelSetup,
  channelStatusLabel,
  channelToggleChecked,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import {
  ChannelProviderPresets,
  ChannelSetupActions,
  ChannelSetupLinks,
  ChannelSetupSteps,
  ChannelValidationBadge,
  ChannelValidationChecks,
  ChannelValidationDetails,
} from "@/components/settings/channels/ChannelSetupParts";
import { ChannelInstancesPanel } from "@/components/settings/channels/ChannelInstancesPanel";
import { Button } from "@/components/ui/button";
import {
  configureChannel,
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
  selected,
  showBrandLogos,
  onSelect,
}: {
  feature: NanobotFeatureInfo;
  selected: boolean;
  showBrandLogos: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);

  return (
    <button
      type="button"
      aria-label={t("settings.channels.selectChannel", {
        name: displayName,
        defaultValue: "View {{name}} settings",
      })}
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "group flex w-full min-w-0 items-center gap-3 rounded-[14px] px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border/80",
        selected ? "bg-background" : "hover:bg-muted",
      )}
    >
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
          {displayName}
        </h3>
        <p className="mt-0.5 truncate text-[12.5px] leading-5 text-muted-foreground">
          {channelDescription(feature, t)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ChannelStatusBadge status={feature.runtime_status}>
          {channelStatusLabel(feature, tx)}
        </ChannelStatusBadge>
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            selected && "translate-x-0.5 text-foreground",
          )}
          aria-hidden
        />
      </div>
    </button>
  );
}

export function ChannelSetupPanel({
  token,
  feature,
  actionKey,
  chatAppsDocsUrl,
  showBrandLogos,
  onAction,
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  actionKey: string | null;
  chatAppsDocsUrl?: string;
  showBrandLogos: boolean;
  onAction: (action: "enable" | "disable", name: string) => void;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const displayName = localizedChannelDisplayName(feature, t);
  const [connectRequestId, setConnectRequestId] = useState(0);
  const uiContribution = channelUiContribution(feature.name, feature.webui);
  const PluginPanel = uiContribution?.Panel;
  if (PluginPanel) {
    return (
      <Suspense fallback={<ChannelPluginLoading />}>
        <PluginPanel
          token={token}
          feature={feature}
          actionKey={actionKey}
          showBrandLogos={showBrandLogos}
          chatAppsDocsUrl={chatAppsDocsUrl}
          onAction={onAction}
          onFeaturesUpdate={onFeaturesUpdate}
        />
      </Suspense>
    );
  }
  if (feature.instances !== undefined) {
    return (
      <ChannelInstancesPanel
        feature={feature}
        showBrandLogos={showBrandLogos}
        chatAppsDocsUrl={chatAppsDocsUrl}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    );
  }
  const enableBusy = actionKey === `enable:${feature.name}`;
  const disableBusy = actionKey === `disable:${feature.name}`;
  const missingSupport = feature.enabled && !feature.installed;
  const alwaysEnabled = feature.capabilities?.includes("always_enabled") ?? false;
  const channelChecked = alwaysEnabled || channelToggleChecked(feature);
  const channelBusy = enableBusy || disableBusy;
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const needsSetupBeforeEnable =
    !channelChecked
    && feature.configured === false
    && !(uiContribution?.canConnectBeforeConfigured && setup.mode === "connect");
  const channelToggleDisabled =
    alwaysEnabled
    || channelBusy
    || (!feature.install_supported && !feature.installed && !feature.enabled);
  const installSupportLabel = tx("settings.nanobotFeatures.installSupport", "Install support");
  const toggleAriaLabel = t("settings.channels.toggleChannel", {
    name: displayName,
    defaultValue: "{{name}} channel",
  });

  return (
    <aside className="min-h-full rounded-[20px] bg-settings-surface p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[18px] font-semibold leading-6 text-foreground">
              {displayName}
            </h3>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {channelDescription(feature, t)}
            </p>
            {missingSupport && feature.install_supported ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={enableBusy}
                onClick={() => onAction("enable", feature.name)}
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
        <div className="flex shrink-0 items-center gap-2 pt-1">
          <ChannelStatusBadge status={feature.runtime_status}>
            {channelStatusLabel(feature, tx)}
          </ChannelStatusBadge>
          {channelBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden />
          ) : null}
          <ToggleButton
            checked={channelChecked}
            disabled={channelToggleDisabled}
            ariaLabel={toggleAriaLabel}
            label={channelChecked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            onChange={(checked) => {
              if (checked && !channelChecked && feature.configured === false) {
                if (uiContribution?.canConnectBeforeConfigured && setup.mode === "connect") {
                  setConnectRequestId((current) => current + 1);
                } else {
                  window.requestAnimationFrame(() => {
                    document.querySelector<HTMLElement>("[id^='channel-field-']")?.focus();
                  });
                }
                return;
              }
              onAction(checked ? "enable" : "disable", feature.name);
            }}
          />
        </div>
      </div>

      <ChannelRuntimeError message={feature.runtime_error} className="mt-4" />

      {needsSetupBeforeEnable ? (
        <p className="mt-3 text-[12px] leading-5 text-muted-foreground">
          {tx(
            "settings.channels.completeSetupToEnable",
            "Complete the required setup below, then nanobot can enable this channel.",
          )}
        </p>
      ) : null}

      <ChannelSetupSurface
        token={token}
        feature={feature}
        setup={setup}
        chatAppsDocsUrl={chatAppsDocsUrl}
        connectRequestId={connectRequestId}
        ConnectFlow={uiContribution?.ConnectFlow}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    </aside>
  );
}

function ChannelSetupSurface({
  token,
  feature,
  setup,
  chatAppsDocsUrl,
  connectRequestId,
  ConnectFlow,
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  chatAppsDocsUrl?: string;
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
    (field) => field.section !== "advanced"
      && (!field.optional || Boolean(field.section) || requirementKeys.has(field.key)),
  );
  const manualFields = setup.manualFields ?? [];
  const advancedFields = mode === "connect"
    ? manualFields
    : fields.filter((field) => !primaryFields.includes(field));
  const editableFields = mode === "credentials" ? fields : mode === "connect" ? manualFields : [];
  const hasAdvanced = advancedFields.length > 0;
  const requirements = channelRequirements(feature, t);
  const summary = setup.summary ?? tx(
    "settings.channels.setupSummary",
    "Enable only turns on nanobot support. Add the platform credentials, then restart nanobot.",
  );
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
          validationPayload.message
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
    }
  };

  const checkCurrentSettings = async () => {
    setValidating(true);
    setNotice(null);
    try {
      const payload = await validateChannel(
        client,
        feature.name,
        channelValuesForSubmit(fields, fieldValues, touchedFields, clearedSecrets),
      );
      setValidation(payload);
      if (payload.message) setNotice(payload.message);
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setValidating(false);
    }
  };

  const primaryActionLabel = channelToggleChecked(feature)
    ? tx("settings.channels.checkConnection", "Check connection")
    : tx("settings.channels.checkAndEnable", "Check and enable");

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
          <div className="text-[13px] font-semibold text-foreground">
            {tx("settings.channels.requiredSetup", "Required setup")}
          </div>
          <div className="flex max-w-full flex-wrap justify-end gap-2">
            {mode !== "webui" ? (
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
        <p className="mt-1 text-[12.5px] leading-5 text-muted-foreground">{requirements}</p>

        <p className="mt-3 text-[12.5px] leading-5 text-muted-foreground">{summary}</p>
        <ChannelValidationDetails validation={validation} />
        <ChannelSetupLinks feature={feature} setup={setup} chatAppsDocsUrl={chatAppsDocsUrl} />
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
                className="h-8 rounded-full bg-background/80 px-3 text-[12px] font-semibold hover:bg-background"
                onClick={() =>
                  setNotice(
                    tx(
                      "settings.channels.connectPreview",
                      "The in-browser connect flow is next. For now, run the command below.",
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
              <code className="mt-3 block rounded-[10px] border border-border/50 bg-muted/45 px-2.5 py-2 font-mono text-[11px] leading-5 text-foreground">
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
              />
            ) : null}
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button
                type="submit"
                size="sm"
                variant="secondary"
                className="h-8 rounded-full bg-background/80 px-3 text-[12px] font-semibold hover:bg-background"
                disabled={saving}
              >
                {saving || validating ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : null}
                {primaryActionLabel}
              </Button>
              {feature.configured || validation ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-8 rounded-full px-3 text-[12px] font-semibold"
                  onClick={() => void checkCurrentSettings()}
                  disabled={saving || validating}
                >
                  {tx("settings.channels.checkOnly", "Check only")}
                </Button>
              ) : null}
            </div>
          </>
        ) : null}
      </section>

      <div
        role="status"
        aria-live="polite"
        className={cn(
          "rounded-[12px] bg-muted/55 px-3 py-2.5 text-[12px] leading-5 text-muted-foreground",
          !notice && "sr-only",
        )}
      >
        {notice ?? ""}
      </div>

      {setup.steps.length ? (
        <ChannelSetupSteps steps={setup.steps} tryIt={setup.tryIt} />
      ) : null}

      {validation?.checks.length ? <ChannelValidationChecks validation={validation} /> : null}

      {hasAdvanced ? (
        <details className="group text-[12px] leading-5 text-muted-foreground">
          <summary className="cursor-pointer list-none text-[12px] font-semibold text-foreground">
            <span className="inline-flex items-center gap-1.5">
              {tx("settings.channels.advanced", "Advanced")}
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden />
            </span>
          </summary>
          {advancedFields.length ? (
            <div className="mt-3">
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
    </form>
  );
}

const CHANNEL_FIELD_SECTION_ORDER: ChannelFieldSection[] = [
  "account",
  "credentials",
  "connection",
  "receiving",
  "sending",
  "access",
  "behavior",
  "security",
];

function ChannelFieldGroups({
  fields,
  requirements,
  ...formProps
}: {
  fields: ChannelConfigField[];
  requirements: ChannelSetupRequirement[];
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
  const groups = new Map<ChannelFieldSection, ChannelConfigField[]>();
  for (const field of fields) {
    const section = field.section ?? "credentials";
    const current = groups.get(section) ?? [];
    current.push(field);
    groups.set(section, current);
  }

  return (
    <div className="mt-4 space-y-5">
      {compositeRequirements.map((requirement, index) => (
        <div
          key={index}
          className="rounded-[12px] border border-border/60 bg-background/55 px-3 py-2.5"
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
      {CHANNEL_FIELD_SECTION_ORDER.map((section) => {
        const sectionFields = groups.get(section);
        if (!sectionFields?.length) return null;
        return (
          <fieldset key={section} className="space-y-3">
            <legend className="text-[12px] font-semibold text-foreground">
              {channelFieldSectionLabel(section, tx)}
            </legend>
            <CredentialForm fields={sectionFields} {...formProps} compact />
          </fieldset>
        );
      })}
    </div>
  );
}

function channelFieldSectionLabel(
  section: ChannelFieldSection,
  tx: (key: string, fallback: string) => string,
): string {
  const fallbacks: Record<ChannelFieldSection, string> = {
    account: "Account",
    credentials: "Credentials",
    connection: "Connection",
    receiving: "Receiving mail",
    sending: "Sending mail",
    access: "Access",
    behavior: "Behavior",
    security: "Security",
    advanced: "Advanced",
  };
  return tx(`settings.channels.sections.${section}`, fallbacks[section]);
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
    if ((values[key] ?? "").trim()) return true;
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
