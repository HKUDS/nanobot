import { useEffect, useId, useMemo, useState } from "react";
import { ChevronDown, ExternalLink, Loader2 } from "lucide-react";
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
    setNotice(null);
  };

  const saveSettings = async () => {
    if (busy || connecting) return;
    setSaving(true);
    setNotice(null);
    try {
      const payload = await configureChannel(
        client,
        feature.name,
        channelValuesForSubmit(editableFields, fieldValues, touchedFields, clearedSecrets),
      );
      if (payload.nanobot_features) onFeaturesUpdate(payload.nanobot_features);
      setTouchedFields(new Set());
      setClearedSecrets(new Set());
      setVisibleSecrets({});
      setFieldValues((current) => Object.fromEntries(
        editableFields.map((field) => [field.key, field.secret ? "" : current[field.key] ?? ""]),
      ));
      setNotice(t("settings.channels.savedSettings", { defaultValue: "Settings saved." }));
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const formProps = {
    values: fieldValues,
    configuredFields,
    visibleSecrets,
    clearedSecrets,
    onChange: setFieldValue,
    onToggleSecret: (key: string) => {
      setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }));
    },
    onClearSecret: (key: string, clear: boolean) => {
      setClearedSecrets((current) => {
        const next = new Set(current);
        if (clear) next.add(key);
        else next.delete(key);
        return next;
      });
    },
    showSecretActions: true,
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
        <div className="text-[12px] leading-5 text-muted-foreground">
          {manifestUrl && !manifestDirty ? (
            <a href={manifestUrl} target="_blank" rel="noreferrer"
              className="inline-flex min-h-8 items-center gap-1.5 rounded text-foreground underline decoration-border underline-offset-4">
              {tx("custom.createApp", "Create prefilled Linear app")}
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : tx("custom.savePublicUrl", "Save the public URL to create a prefilled Linear app.")}
        </div>
        <CredentialForm {...formProps} fields={fields.filter((field) => field.key !== PUBLIC_BASE_URL_KEY)} />
        <div id={advancedPanelId} hidden={!advancedOpen}>
          <CredentialForm {...formProps} fields={advancedFields} />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <Button type="submit" size="sm" variant="secondary" disabled={busy || connecting}
            className="h-10 rounded-full px-3 text-[12px] font-semibold sm:h-9">
            {saving ? <Loader2 className="me-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
            {t("settings.actions.save", { defaultValue: "Save settings" })}
          </Button>
        </div>
        <div role="status" aria-live="polite" className={cn(
          "rounded-control bg-muted/55 px-3 py-2.5 text-[12px] leading-5 text-muted-foreground",
          !notice && "sr-only",
        )}>{notice ?? ""}</div>
      </form>
      <fieldset disabled={busy || dirty || !credentialsSaved} className="min-w-0">
        <legend className="sr-only">{tx("custom.authorizeTitle", "Authorize in Linear")}</legend>
        <LinearConnectFlow token={token} feature={feature}
          idleLabel={tx("custom.connect", "Connect Linear")} onFeaturesUpdate={onFeaturesUpdate}
          onActiveChange={setConnecting} />
      </fieldset>
      {dirty || !credentialsSaved ? (
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
          {tx("custom.saveBeforeConnect", "Save the app credentials before authorizing a workspace.")}
        </p>
      ) : null}
    </aside>
  );
}
