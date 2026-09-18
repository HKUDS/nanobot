import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ExternalLink, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import {
  CredentialForm,
  channelValuesForSubmit,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import {
  CHANNEL_SETUP_PANEL_CLASS_NAME,
  ChannelLogo,
  ChannelRuntimeError,
  channelSetup,
  localizedChannelDisplayName,
} from "@/components/settings/channels/ChannelIdentity";
import { Button } from "@/components/ui/button";
import { channelValidationStatusClass } from "@/components/settings/channels/ChannelValidationProgress";
import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import { configureChannel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { LinearConnectFlow } from "./LinearConnectFlow";
import { linearManifestUrl } from "./manifest";

const PUBLIC_BASE_URL_KEY = "channels.linear.publicBaseUrl";
const WEBHOOK_PATH_KEY = "channels.linear.webhookPath";
const CALLBACK_PATH_KEY = "channels.linear.oauthCallbackPath";

export function LinearPanel({
  token,
  feature,
  actionKey,
  showBrandLogos,
  onFeaturesUpdate,
  onBeforeCloseChange,
}: ChannelPluginPanelProps) {
  const { client } = useClient();
  const { t, i18n } = useTranslation();
  const tx = channelTranslator(t, "linear");
  const displayName = localizedChannelDisplayName(feature, t);
  const setup = channelSetup(feature, i18n.resolvedLanguage ?? i18n.language);
  const fields = setup.fields ?? [];
  const advancedFields = setup.manualFields ?? [];
  const editableFields = [...fields, ...advancedFields];
  const configuredFields = useMemo(
    () => new Set(feature.configured_fields ?? []),
    [feature.configured_fields],
  );
  const savedValuesKey = JSON.stringify([feature.config_values, feature.configured_fields]);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    defaultChannelFieldValues(editableFields, feature.config_values),
  );
  const [touchedFields, setTouchedFields] = useState<Set<string>>(() => new Set());
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [clearedSecrets, setClearedSecrets] = useState<Set<string>>(() => new Set());
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);
  const advancedPanelId = useId();

  useEffect(() => {
    setFieldValues(defaultChannelFieldValues(editableFields, feature.config_values));
    setTouchedFields(new Set());
    setVisibleSecrets({});
    setClearedSecrets(new Set());
  }, [savedValuesKey, feature.name]);

  const busy = saving || Boolean(actionKey);
  const savedValues = defaultChannelFieldValues(editableFields, feature.config_values);
  const dirty = clearedSecrets.size > 0 || editableFields.some(
    (field) => fieldValues[field.key] !== savedValues[field.key],
  );
  const secretFields = editableFields.filter((field) => field.secret);
  const touchedSecret = secretFields.some((field) =>
    touchedFields.has(field.key) && Boolean(fieldValues[field.key]?.trim()),
  );
  const hasSavedSecrets = secretFields.some((field) => configuredFields.has(field.key));
  const manifestDirty = [PUBLIC_BASE_URL_KEY, WEBHOOK_PATH_KEY, CALLBACK_PATH_KEY].some(
    (key) => fieldValues[key] !== savedValues[key],
  );
  const credentialsSaved = fields.filter((field) => !field.optional).every((field) =>
    configuredFields.has(field.key) || Boolean(feature.config_values?.[field.key]?.trim()),
  );
  const savedBaseUrl = feature.config_values?.[PUBLIC_BASE_URL_KEY]?.replace(/\/$/, "");
  const manifestUrl = savedBaseUrl
    ? linearManifestUrl(
      savedBaseUrl,
      feature.config_values?.[WEBHOOK_PATH_KEY] || "/linear/webhook",
      feature.config_values?.[CALLBACK_PATH_KEY] || "/linear/oauth/callback",
    )
    : null;

  const setFieldValue = (key: string, value: string) => {
    setFieldValues((current) => ({ ...current, [key]: value }));
    setTouchedFields((current) => new Set(current).add(key));
    setClearedSecrets((current) => {
      if (!current.has(key)) return current;
      const next = new Set(current);
      next.delete(key);
      return next;
    });
    setNotice(null);
    setSaved(false);
  };

  const saveSettings = useCallback(async (): Promise<boolean> => {
    if (savePromiseRef.current) return savePromiseRef.current;
    if (!dirty) return true;
    if (busy || connecting) return false;
    const save = (async () => {
      setSaving(true);
      setSaved(false);
      setNotice(null);
      try {
        const payload = await configureChannel(
          client,
          feature.name,
          channelValuesForSubmit(editableFields, fieldValues, touchedFields, clearedSecrets),
        );
        setTouchedFields(new Set());
        setClearedSecrets(new Set());
        setVisibleSecrets({});
        setFieldValues((current) => Object.fromEntries(
          editableFields.map((field) => [field.key, field.secret ? "" : current[field.key] ?? ""]),
        ));
        if (payload.nanobot_features) onFeaturesUpdate(payload.nanobot_features);
        setSaved(true);
        return true;
      } catch (err) {
        setNotice((err as Error).message);
        return false;
      } finally {
        setSaving(false);
      }
    })();
    savePromiseRef.current = save;
    const result = await save;
    if (savePromiseRef.current === save) savePromiseRef.current = null;
    return result;
  }, [busy, connecting, dirty, client, feature.name, editableFields, fieldValues,
    touchedFields, clearedSecrets, onFeaturesUpdate]);

  useAutoSave(
    { fieldValues, clearedSecrets: [...clearedSecrets] },
    dirty,
    busy || connecting,
    () => void saveSettings(),
    !touchedSecret && !notice,
  );

  useEffect(() => {
    onBeforeCloseChange?.(dirty ? saveSettings : null);
    return () => onBeforeCloseChange?.(null);
  }, [dirty, saveSettings, onBeforeCloseChange]);

  const removeSavedCredentials = () => {
    setClearedSecrets(new Set(secretFields.map((field) => field.key)));
    setFieldValues((current) => ({
      ...current,
      ...Object.fromEntries(secretFields.map((field) => [field.key, ""])),
    }));
    setNotice(null);
    setSaved(false);
  };

  const formProps = {
    values: fieldValues,
    configuredFields,
    visibleSecrets,
    clearedSecrets,
    onChange: setFieldValue,
    onFieldBlur: () => { void saveSettings(); },
    onToggleSecret: (key: string) => {
      setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
    },
    disabled: busy || connecting,
    compact: true,
  };

  return (
    <aside className={CHANNEL_SETUP_PANEL_CLASS_NAME}>
      <form className="flex min-w-0 flex-col gap-4" onSubmit={(event) => {
        event.preventDefault();
        void saveSettings();
      }}>
        <div className="flex flex-wrap items-center justify-between gap-3 pe-20">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <h3 className="sr-only">{displayName}</h3>
          {feature.runtime_status === "running" ? (
            <span role="status" className={cn(
              "ms-auto inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium",
              channelValidationStatusClass("connected"),
            )}>
              <Check className="h-3.5 w-3.5" aria-hidden />
              {t("settings.channels.validation.connected", { defaultValue: "Connected" })}
            </span>
          ) : null}
          <span role="status" aria-live="polite" aria-atomic="true" className={cn(
            "ms-auto inline-flex items-center gap-1.5 text-[11px] text-muted-foreground",
            !saving && !saved && "sr-only",
          )}>
            {saving ? <><Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
              {t("settings.actions.saving", { defaultValue: "Saving" })}</> : saved ? <>
              <Check className="h-3 w-3" aria-hidden />
              {t("settings.channels.savedSettings", { defaultValue: "Settings saved." })}</> : null}
          </span>
          <button type="button"
            className="inline-flex min-h-8 items-center gap-1.5 rounded px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-offset-2"
            aria-expanded={advancedOpen} aria-controls={advancedPanelId}
            onClick={() => setAdvancedOpen((current) => !current)}>
            {t("settings.channels.advanced", { defaultValue: "Advanced" })}
            <ChevronDown className={cn(
              "h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
              advancedOpen && "rotate-180",
            )} aria-hidden />
          </button>
        </div>
        <ChannelRuntimeError message={feature.runtime_error} />
        <CredentialForm {...formProps} fields={fields.filter((field) => field.key === PUBLIC_BASE_URL_KEY)} />
        {!manifestUrl || manifestDirty ? (
          <p className="text-[12px] leading-5 text-muted-foreground">
            {tx("custom.savePublicUrl", "Enter a public HTTPS URL to create a prefilled Linear app.")}
          </p>
        ) : null}
        <CredentialForm {...formProps} fields={fields.filter((field) => field.key !== PUBLIC_BASE_URL_KEY)} />
        <div id={advancedPanelId} hidden={!advancedOpen}>
          <CredentialForm {...formProps} fields={advancedFields} />
        </div>
        {notice ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-muted/55 px-3 py-2.5 text-[12px] leading-5">
            <p role="alert">{notice}</p>
            <Button type="submit" variant="secondary" size="sm" disabled={busy || connecting}
              className="min-h-10 rounded-full text-[12px]">
              {tx("custom.retrySave", "Retry")}
            </Button>
          </div>
        ) : null}
      </form>
      <LinearConnectFlow token={token} feature={feature}
        idleLabel={tx("custom.connect", "Connect Linear")} onFeaturesUpdate={onFeaturesUpdate}
        onActiveChange={setConnecting}
        renderActions={(connectButton) => (
          <div className="flex flex-wrap items-center justify-end gap-2 sm:grid sm:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div className="me-auto min-w-0 max-w-full">
              {manifestUrl && !manifestDirty ? (
                <Button asChild variant="secondary" size="sm"
                  className="h-auto min-h-10 max-w-full gap-2 whitespace-normal rounded-full px-4 py-2 text-[12px]">
                  <a href={manifestUrl} target="_blank" rel="noreferrer">
                    {tx("custom.createApp", "Create prefilled Linear app")}
                    <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  </a>
                </Button>
              ) : (
                <Button variant="secondary" size="sm" disabled
                  className="h-auto min-h-10 max-w-full whitespace-normal rounded-full px-4 py-2 text-[12px]">
                  {tx("custom.createApp", "Create prefilled Linear app")}
                </Button>
              )}
            </div>
            {hasSavedSecrets ? (
              <Button type="button" variant="ghost" size="sm" disabled={busy || connecting}
                className="h-auto min-h-10 whitespace-normal rounded-full text-[12px] text-muted-foreground"
                onClick={removeSavedCredentials}>
                {tx("custom.removeCredentials", "Remove saved credentials")}
              </Button>
            ) : null}
            <fieldset disabled={busy || dirty || !credentialsSaved} className="min-w-0 sm:col-start-3">
              <legend className="sr-only">{tx("custom.authorizeTitle", "Authorize in Linear")}</legend>
              {connectButton}
            </fieldset>
          </div>
        )} />
      {dirty || !credentialsSaved ? (
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
          {tx("custom.saveBeforeConnect", "Enter the app credentials and wait for them to save before connecting.")}
        </p>
      ) : null}
    </aside>
  );
}
