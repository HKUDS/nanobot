import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Loader2,
  Plus,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ToggleButton } from "@/components/settings/ToggleButton";
import {
  type ChannelProviderPreset,
  type ChannelSetupPresentation,
} from "@/components/settings/channels/catalog";
import {
  CredentialForm,
  channelValuesForSubmit,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  ChannelLogo,
  ChannelStatusBadge,
  channelDescription,
  channelDisplayName,
  channelRequirements,
  channelSetup,
  channelStatusLabel,
} from "@/components/settings/channels/ChannelIdentity";
import {
  FeishuConnectFlow,
  WeixinConnectFlow,
} from "@/components/settings/channels/ChannelQrConnectFlow";
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
import { FeishuAssistantsPanel } from "@/components/settings/channels/FeishuAssistantsPanel";
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

  return (
    <button
      type="button"
      aria-label={t("settings.channels.selectChannel", {
        name: channelDisplayName(feature),
        defaultValue: "View {{name}} settings",
      })}
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "group flex w-full min-w-0 items-center gap-3 rounded-[14px] border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border/80",
        selected
          ? "border-border/55 bg-muted/35"
          : "border-transparent hover:border-border/45 hover:bg-muted/25",
      )}
    >
      <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-[14px] font-semibold leading-5 text-foreground">
          {channelDisplayName(feature)}
        </h3>
        <p className="mt-0.5 truncate text-[12.5px] leading-5 text-muted-foreground">
          {channelDescription(feature, t)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ChannelStatusBadge>{channelStatusLabel(feature, tx)}</ChannelStatusBadge>
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
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [connectRequestId, setConnectRequestId] = useState(0);
  if (feature.name === "feishu") {
    return (
      <FeishuAssistantsPanel
        token={token}
        feature={feature}
        showBrandLogos={showBrandLogos}
        chatAppsDocsUrl={chatAppsDocsUrl}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    );
  }
  if (feature.instances !== undefined) {
    return (
      <ChannelInstancesPanel
        token={token}
        feature={feature}
        showBrandLogos={showBrandLogos}
        chatAppsDocsUrl={chatAppsDocsUrl}
        actionKey={actionKey}
        onAction={onAction}
        onFeaturesUpdate={onFeaturesUpdate}
      />
    );
  }
  const enableBusy = actionKey === `enable:${feature.name}`;
  const disableBusy = actionKey === `disable:${feature.name}`;
  const missingSupport = feature.enabled && !feature.installed;
  const requiredWebui = feature.name === "websocket";
  const channelChecked = requiredWebui || feature.enabled;
  const channelBusy = enableBusy || disableBusy;
  const setup = channelSetup(feature);
  const needsSetupBeforeEnable =
    !channelChecked
    && feature.configured === false
    && !(feature.name === "weixin" && setup.mode === "connect");
  const channelToggleDisabled =
    requiredWebui
    || channelBusy
    || needsSetupBeforeEnable
    || (!feature.install_supported && !feature.installed && !feature.enabled);
  const installSupportLabel = tx("settings.nanobotFeatures.installSupport", "Install support");
  const toggleAriaLabel = t("settings.channels.toggleChannel", {
    name: channelDisplayName(feature),
    defaultValue: "{{name}} channel",
  });

  return (
    <aside className="min-h-full rounded-[20px] border border-border/80 bg-background p-5 shadow-none">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[18px] font-semibold leading-6 text-foreground">
              {channelDisplayName(feature)}
            </h3>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
              {channelDescription(feature, t)}
            </p>
            {missingSupport && feature.install_supported ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
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
          <ChannelStatusBadge>{channelStatusLabel(feature, tx)}</ChannelStatusBadge>
          {channelBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden />
          ) : null}
          <ToggleButton
            checked={channelChecked}
            disabled={channelToggleDisabled}
            ariaLabel={toggleAriaLabel}
            label={channelChecked ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            onChange={(checked) => {
              if (
                feature.name === "weixin"
                && checked
                && !channelChecked
                && feature.configured === false
              ) {
                setConnectRequestId((current) => current + 1);
                return;
              }
              onAction(checked ? "enable" : "disable", feature.name);
            }}
          />
        </div>
      </div>

      <ChannelSetupSurface
        token={token}
        feature={feature}
        setup={setup}
        chatAppsDocsUrl={chatAppsDocsUrl}
        connectRequestId={connectRequestId}
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
  onFeaturesUpdate,
}: {
  token: string;
  feature: NanobotFeatureInfo;
  setup: ChannelSetupPresentation;
  chatAppsDocsUrl?: string;
  connectRequestId: number;
  onFeaturesUpdate: (payload: NanobotFeaturesPayload) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<ChannelValidationPayload | null>(null);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [touchedFields, setTouchedFields] = useState<Set<string>>(() => new Set());
  const configValuesKey = JSON.stringify(feature.config_values ?? {});
  const configuredFields = useMemo(
    () => new Set(feature.configured_fields ?? []),
    [feature.configured_fields],
  );
  const mode = setup.mode ?? "credentials";
  const fields = setup.fields ?? [];
  const requiredFields = fields.filter((field) => !field.optional);
  const primaryFields = requiredFields.length ? requiredFields : fields.slice(0, 1);
  const optionalFields = fields.filter((field) => field.optional);
  const manualFields = setup.manualFields ?? [];
  const advancedFields = mode === "connect" ? manualFields : optionalFields;
  const editableFields = mode === "credentials" ? fields : mode === "connect" ? manualFields : [];
  const hasAdvanced = advancedFields.length > 0;
  const requirements = channelRequirements(feature, t);
  const summary = t(`settings.channels.items.${feature.name}.setup.summary`, {
    defaultValue:
      setup.summary ??
      tx(
        "settings.channels.setupSummary",
        "Enable only turns on nanobot support. Add the platform credentials, then restart nanobot.",
      ),
  });
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
    setFieldValues(defaultChannelFieldValues(editableFields, feature.config_values));
  }, [configValuesKey, feature.name]);

  const toggleSecret = (key: string) => {
    setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
  };

  const setFieldValue = (key: string, value: string) => {
    setFieldValues((current) => ({ ...current, [key]: value }));
    setTouchedFields((current) => new Set(current).add(key));
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
    setSaving(true);
    setValidating(true);
    setNotice(null);
    const values = channelValuesForSubmit(fields, fieldValues, touchedFields);
    try {
      const validationPayload = await validateChannel(token, feature.name, values);
      setValidation(validationPayload);
      if (!validationPayload.can_enable) {
        setNotice(
          validationPayload.message
            ?? tx("settings.channels.validationFailed", "Check the required setup before enabling."),
        );
        return;
      }
      const payload = await configureChannel(
        token,
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
        token,
        feature.name,
        channelValuesForSubmit(fields, fieldValues, touchedFields),
      );
      setValidation(payload);
      if (payload.message) setNotice(payload.message);
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setValidating(false);
    }
  };

  const primaryActionLabel = feature.enabled
    ? tx("settings.channels.checkConnection", "Check connection")
    : tx("settings.channels.checkAndEnable", "Check and enable");

  return (
    <form
      className="mt-5 overflow-hidden rounded-[16px] border border-border/70 bg-background shadow-none"
      onSubmit={(event) => {
        event.preventDefault();
        if (mode === "credentials") void saveCredentialSettings();
      }}
    >
      <section className="px-4 py-4">
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

        {mode === "connect" && feature.name === "feishu" ? (
          <FeishuConnectFlow
            token={token}
            connectRequestId={connectRequestId}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ) : mode === "connect" && feature.name === "weixin" ? (
          <WeixinConnectFlow
            token={token}
            idleLabel={t(`settings.channels.items.${feature.name}.setup.primaryAction`, {
              defaultValue: setup.primaryActionLabel ?? tx("settings.channels.connect", "Connect"),
            })}
            connectRequestId={connectRequestId}
            onFeaturesUpdate={onFeaturesUpdate}
          />
        ) : mode === "connect" ? (
          <>
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
                onClick={() =>
                  setNotice(
                    tx(
                      "settings.channels.connectPreview",
                      "The in-browser connect flow is next. For now, run the command below.",
                    ),
                  )
                }
              >
                {t(`settings.channels.items.${feature.name}.setup.primaryAction`, {
                  defaultValue: setup.primaryActionLabel ?? tx("settings.channels.connect", "Connect"),
                })}
              </Button>
              {setup.command ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
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
                featureName={feature.name}
                presets={setup.presets}
                onApply={applyPreset}
              />
            ) : null}
            {primaryFields.length ? (
              <CredentialForm
                fields={primaryFields}
                values={fieldValues}
                configuredFields={configuredFields}
                visibleSecrets={visibleSecrets}
                onChange={setFieldValue}
                onToggleSecret={toggleSecret}
              />
            ) : null}
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button
                type="submit"
                size="sm"
                variant="outline"
                className="h-8 rounded-full border-border/65 bg-background/80 px-3 text-[12px] font-semibold hover:bg-muted/70"
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

      {notice ? (
        <div
          role="status"
          className="border-t border-border/60 px-4 py-3 text-[12px] leading-5 text-muted-foreground"
        >
          {notice}
        </div>
      ) : null}

      {setup.steps.length ? (
        <ChannelSetupSteps featureName={feature.name} steps={setup.steps} tryIt={setup.tryIt} />
      ) : null}

      {validation?.checks.length ? <ChannelValidationChecks validation={validation} /> : null}

      {hasAdvanced ? (
        <details className="group border-t border-border/60 px-4 py-3 text-[12px] leading-5 text-muted-foreground">
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
                compact
              />
            </div>
          ) : null}
        </details>
      ) : null}
    </form>
  );
}
