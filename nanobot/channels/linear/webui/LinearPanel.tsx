import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ExternalLink, Loader2, RefreshCw, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import {
  CredentialForm,
  channelFieldInputId,
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
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { channelValidationStatusClass } from "@/components/settings/channels/ChannelValidationProgress";
import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import { configureChannel, disableNanobotFeature } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { manageLinearWorkspace } from "./api";
import type { LinearInstallationSummary } from "./types";
import { LinearConnectFlow } from "./LinearConnectFlow";
import { LinearMemberAccess } from "./LinearMemberAccess";
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
  onConfigureMcp,
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
  const [publicUrlPromptOpen, setPublicUrlPromptOpen] = useState(false);
  const [installations, setInstallations] = useState<LinearInstallationSummary[]>([]);
  const [loadingInstallations, setLoadingInstallations] = useState(false);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [disconnectConfirmId, setDisconnectConfirmId] = useState<string | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<string | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
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

  const loadInstallations = useCallback(async () => {
    if (!credentialsSaved || dirty) return;
    setLoadingInstallations(true);
    setWorkspaceNotice(null);
    setWorkspaceError(null);
    try {
      const payload = await manageLinearWorkspace(client, { operation: "inspect" });
      setInstallations(payload.installations ?? []);
    } catch (err) {
      setWorkspaceError((err as Error).message);
    } finally {
      setLoadingInstallations(false);
    }
  }, [client, credentialsSaved, dirty]);

  useEffect(() => {
    if (feature.runtime_status === "running") void loadInstallations();
  }, [feature.runtime_status, loadInstallations]);

  const disconnectWorkspace = async (installation: LinearInstallationSummary) => {
    setDisconnectingId(installation.organization_id);
    setWorkspaceNotice(null);
    setWorkspaceError(null);
    try {
      const payload = await manageLinearWorkspace(client, {
        operation: "disconnect",
        organization_id: installation.organization_id,
      });
      const remaining = payload.installations ?? [];
      setInstallations(remaining);
      setWorkspaceNotice(payload.message ?? null);
      setDisconnectConfirmId(null);
      if (remaining.length === 0) {
        onFeaturesUpdate(await disableNanobotFeature(client, "linear"));
      }
    } catch (err) {
      setWorkspaceError((err as Error).message);
    } finally {
      setDisconnectingId(null);
    }
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
              {tx("custom.channelRunning", "Channel running")}
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
      {feature.runtime_status === "running" ? (
        <section className="mt-5 space-y-3" aria-labelledby="linear-workspaces-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 id="linear-workspaces-heading" className="text-[13px] font-semibold text-foreground">
              {tx("custom.workspacesTitle", "Authorized workspaces")}
            </h4>
            <Button type="button" variant="ghost" size="sm"
              disabled={loadingInstallations || disconnectingId !== null}
              className="min-h-10 gap-2 rounded-full text-[12px]"
              onClick={() => void loadInstallations()}>
              <RefreshCw className={cn("h-3.5 w-3.5", loadingInstallations && "animate-spin motion-reduce:animate-none")} aria-hidden />
              {tx("custom.refreshWorkspaces", "Refresh workspaces")}
            </Button>
          </div>
          <div role="status" aria-live="polite" className="sr-only">
            {loadingInstallations ? tx("custom.loadingWorkspaces", "Loading workspaces") : ""}
          </div>
          {!loadingInstallations && !workspaceError && installations.length === 0 ? (
            <p className="rounded-control bg-muted/45 px-3 py-2.5 text-[12px] leading-5 text-muted-foreground">
              {tx("custom.noWorkspaces", "No workspaces are authorized. Connect a workspace to receive Linear agent requests.")}
            </p>
          ) : null}
          <div className="space-y-2">
            {installations.map((installation) => {
              const confirming = disconnectConfirmId === installation.organization_id;
              const disconnecting = disconnectingId === installation.organization_id;
              const name = installation.organization_name || installation.organization_id;
              return (
                <article key={installation.organization_id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-control bg-muted/45 px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-[12.5px] font-medium text-foreground">{name}</p>
                    <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                      {installation.authorization_status === "missing_scopes"
                        ? tx(
                          "custom.missingScopes",
                          "Reconnect to grant: {{scopes}}",
                          { scopes: installation.missing_scopes?.join(", ") || "required scopes" },
                        )
                        : installation.authorization_status === "refresh_required"
                          ? tx("custom.refreshRequired", "Authorization refresh required")
                          : tx("custom.authorized", "Authorized")}
                      {installation.scopes?.length ? ` · ${installation.scopes.join(", ")}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {confirming ? (
                      <Button type="button" variant="ghost" size="sm"
                        disabled={loadingInstallations || disconnecting}
                        className="min-h-10 rounded-full text-[12px]"
                        onClick={() => setDisconnectConfirmId(null)}>
                        {t("settings.actions.cancel", { defaultValue: "Cancel" })}
                      </Button>
                    ) : null}
                    <Button type="button" variant={confirming ? "destructive" : "outline"} size="sm"
                      disabled={loadingInstallations || disconnectingId !== null}
                      className="min-h-10 gap-2 rounded-full text-[12px]"
                      onClick={() => confirming
                        ? void disconnectWorkspace(installation)
                        : setDisconnectConfirmId(installation.organization_id)}>
                      {disconnecting ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                        : <Unplug className="h-3.5 w-3.5" aria-hidden />}
                      {confirming
                        ? tx("custom.confirmDisconnect", "Disconnect workspace")
                        : tx("custom.disconnect", "Disconnect")}
                    </Button>
                  </div>
                  <LinearMemberAccess organizationId={installation.organization_id}
                    disabled={busy || dirty || connecting || loadingInstallations || disconnectingId !== null} />
                </article>
              );
            })}
          </div>
          {workspaceError ? (
            <p role="alert" className="text-[12px] leading-5 text-destructive">{workspaceError}</p>
          ) : null}
          {workspaceNotice ? (
            <p role="status" className="text-[12px] leading-5 text-muted-foreground">
              {workspaceNotice}
            </p>
          ) : null}
        </section>
      ) : null}
      <LinearConnectFlow token={token} feature={feature}
        idleLabel={tx("custom.connect", "Connect Linear")} onFeaturesUpdate={onFeaturesUpdate}
        onActiveChange={setConnecting}
        renderActions={(connectButton) => (
          <div className="flex flex-wrap items-center justify-end gap-2 sm:grid sm:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div className="me-auto flex min-w-0 max-w-full flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm"
                className="h-auto min-h-10 whitespace-normal rounded-full px-4 py-2 text-[12px]"
                disabled={busy || connecting || !onConfigureMcp}
                onClick={async () => {
                  if (await saveSettings()) onConfigureMcp?.("linear");
                }}>
                {tx("custom.configureTools", "Configure Linear MCP")}
              </Button>
              {manifestUrl && !manifestDirty ? (
                <Button asChild variant="outline" size="sm"
                  className="h-auto min-h-10 max-w-full gap-2 whitespace-normal rounded-full px-4 py-2 text-[12px]">
                  <a href={manifestUrl} target="_blank" rel="noreferrer">
                    {tx("custom.createApp", "Create Linear app")}
                    <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  </a>
                </Button>
              ) : (
                <Button type="button" variant="outline" size="sm"
                  disabled={Boolean(fieldValues[PUBLIC_BASE_URL_KEY]?.trim())}
                  onClick={() => setPublicUrlPromptOpen(true)}
                  className="h-auto min-h-10 max-w-full whitespace-normal rounded-full px-4 py-2 text-[12px]">
                  {tx("custom.createApp", "Create Linear app")}
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
      <AlertDialog open={publicUrlPromptOpen} onOpenChange={setPublicUrlPromptOpen}>
        <AlertDialogContent onCloseAutoFocus={(event) => {
          event.preventDefault();
          document.getElementById(channelFieldInputId(PUBLIC_BASE_URL_KEY))?.focus();
        }}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {tx("setup.fields.publicBaseUrl.label", "Public HTTPS URL")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {tx("custom.savePublicUrl", "Enter a public HTTPS URL to create a Linear app.")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("common.close", { defaultValue: "Close" })}
            </AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}
