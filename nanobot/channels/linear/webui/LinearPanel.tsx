import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { AlertCircle, Check, ChevronDown, ExternalLink, Info, Loader2, MoreHorizontal, Plus, RefreshCw, Unplug } from "lucide-react";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { SettingsHint } from "@/components/settings/shared/SettingsHint";
import { configureChannel, disableNanobotFeature, fetchNanobotFeatures } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

import { manageLinearWorkspace } from "./api";
import type { LinearInstallationSummary } from "./types";
import { LinearConnectFlow } from "./LinearConnectFlow";
import { LinearMemberAccess } from "./LinearMemberAccess";
import { LinearAvatar } from "./LinearAvatar";
import { linearManifestUrl } from "./manifest";
import { linearWorkspaceStore } from "./workspace-store";
import { linearMemberAccessStore } from "./member-access-store";
import { LinearResetConnection } from "./LinearResetConnection";
import { LinearSecretField } from "./LinearSecretField";

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
  const [resetting, setResetting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectRequestId, setConnectRequestId] = useState(0);
  const [connectionGeneration, setConnectionGeneration] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [publicUrlPromptOpen, setPublicUrlPromptOpen] = useState(false);
  const workspaceStore = linearWorkspaceStore(client, token, JSON.stringify([
    feature.config_values?.["channels.linear.clientId"],
    feature.config_values?.[PUBLIC_BASE_URL_KEY],
  ]));
  const { installations: cachedInstallations, logos, loading: loadingInstallations,
    error: inspectionError } = useSyncExternalStore(workspaceStore.subscribe, workspaceStore.getSnapshot);
  const installations = cachedInstallations ?? [];
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [disconnectConfirmId, setDisconnectConfirmId] = useState<string | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<string | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const workspaceActionRef = useRef<HTMLButtonElement | null>(null);
  const skipMenuRestoreFocus = useRef(false);
  const disconnectTarget = installations.find(item => item.organization_id === disconnectConfirmId);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);
  const secretSavePromiseRef = useRef<Promise<void> | null>(null);
  const advancedPanelId = useId();

  useEffect(() => {
    setFieldValues(defaultChannelFieldValues(editableFields, feature.config_values));
    setTouchedFields(new Set());
    setVisibleSecrets({});
    setClearedSecrets(new Set());
  }, [savedValuesKey, feature.name]);

  const busy = saving || resetting || Boolean(actionKey);
  const savedValues = defaultChannelFieldValues(editableFields, feature.config_values);
  const dirty = clearedSecrets.size > 0 || editableFields.some(
    (field) => fieldValues[field.key] !== savedValues[field.key],
  );
  const secretFields = editableFields.filter((field) => field.secret);
  const touchedSecret = secretFields.some((field) =>
    touchedFields.has(field.key) && Boolean(fieldValues[field.key]?.trim()),
  );
  const hasSavedSecrets = secretFields.some((field) => configuredFields.has(field.key));
  const memberConfigScope = JSON.stringify([
    feature.config_values?.["channels.linear.clientId"],
    feature.config_values?.["channels.linear.allowFrom"],
  ]);
  const forgetWorkspaceMembers = (organizationId: string) => {
    linearMemberAccessStore(client, token, memberConfigScope, organizationId).invalidate();
  };
  const manifestDirty = [PUBLIC_BASE_URL_KEY, WEBHOOK_PATH_KEY, CALLBACK_PATH_KEY].some(
    (key) => fieldValues[key] !== savedValues[key],
  );
  const credentialsSaved = fields.filter((field) => !field.optional).every((field) =>
    configuredFields.has(field.key) || Boolean(feature.config_values?.[field.key]?.trim()),
  );
  const workspaceActionsDisabled = busy || dirty || connecting || loadingInstallations
    || disconnectingId !== null;
  const savedBaseUrl = feature.config_values?.[PUBLIC_BASE_URL_KEY]?.replace(/\/$/, "");
  const manifestUrl = savedBaseUrl
    ? linearManifestUrl(
      savedBaseUrl,
      feature.config_values?.[WEBHOOK_PATH_KEY] || "/linear/webhook",
      feature.config_values?.[CALLBACK_PATH_KEY] || "/linear/oauth/callback",
    )
    : null;

  const loadInstallations = useCallback(async (force = false) => {
    if (!credentialsSaved || dirty) return;
    setWorkspaceNotice(null);
    setWorkspaceError(null);
    await workspaceStore.load(force);
  }, [workspaceStore, credentialsSaved, dirty]);

  useEffect(() => {
    // Stopping message delivery does not revoke workspace authorizations.
    void loadInstallations();
    let wasOpen = client.status === "open";
    return client.onStatus((status) => {
      // A gateway restart can interrupt the initial inspection. Recover without
      // making the user refresh or begin a second OAuth authorization.
      if (status === "open" && !wasOpen) void loadInstallations(true);
      wasOpen = status === "open";
    });
  }, [client, feature.runtime_status, loadInstallations]);

  const disconnectWorkspace = async (installation: LinearInstallationSummary) => {
    setDisconnectingId(installation.organization_id);
    setWorkspaceNotice(null);
    setWorkspaceError(null);
    try {
      const payload = await manageLinearWorkspace(client, {
        operation: "disconnect",
        organization_id: installation.organization_id,
      });
      const remaining = payload.installations;
      if (!remaining || remaining.some(item => item.organization_id === installation.organization_id)) {
        throw new Error(tx("custom.resetInspectFailed", "Could not verify connected workspaces. App settings were kept."));
      }
      forgetWorkspaceMembers(installation.organization_id);
      workspaceStore.replace(remaining);
      setWorkspaceNotice(payload.message ?? null);
      setDisconnectConfirmId(null);
      setConnectRequestId(0);
      setConnectionGeneration(value => value + 1);
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
    onBeforeCloseChange?.(dirty || saving ? async () => {
      if (secretSavePromiseRef.current) {
        try { await secretSavePromiseRef.current; } catch { return false; }
      }
      return saveSettings();
    } : null);
    return () => onBeforeCloseChange?.(null);
  }, [dirty, saving, saveSettings, onBeforeCloseChange]);

  const saveSecret = async (key: string, value: string) => {
    if (busy || dirty || connecting || savePromiseRef.current || secretSavePromiseRef.current) {
      throw new Error("Settings are busy");
    }
    const save = (async () => {
      setSaving(true);
      setSaved(false);
      try {
        // Explicit, single-field commit: blur, visibility toggles and cancellation never save.
        const payload = await configureChannel(client, feature.name, { [key]: value });
        if (!payload.saved) throw new Error("Secret was not saved");
        onFeaturesUpdate(payload.nanobot_features ?? await fetchNanobotFeatures(token));
        setSaved(true);
      } finally {
        setSaving(false);
      }
    })();
    secretSavePromiseRef.current = save;
    try { await save; } finally { secretSavePromiseRef.current = null; }
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
        <div className="flex min-h-10 flex-wrap items-center justify-between gap-3 pe-20">
          <ChannelLogo feature={feature} showBrandLogos={showBrandLogos} />
          <h3 className="sr-only">{displayName}</h3>
          <span role="status" aria-live="polite" aria-atomic="true"
            className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
            {saving ? t("settings.actions.saving", { defaultValue: "Saving" })
              : saved ? t("settings.channels.savedSettings", { defaultValue: "Settings saved." }) : ""}
          </span>
          {feature.runtime_status === "running" ? (
            <span role="status" className={cn(
              "ms-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-medium leading-none",
              channelValidationStatusClass("connected"),
            )}>
              <Check className="h-3.5 w-3.5" aria-hidden />
              {tx("custom.channelRunning", "Channel running")}
            </span>
          ) : null}
          <button type="button"
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded px-1 text-[12px] leading-none text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-offset-2"
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
        <div className="grid gap-y-4">
          {fields.filter(field => field.key !== PUBLIC_BASE_URL_KEY).map(field => field.secret ? (
            <LinearSecretField key={`${field.key}:${connectionGeneration}`} field={field} configured={configuredFields.has(field.key)}
              disabled={busy || dirty || connecting} onSave={saveSecret} />
          ) : <CredentialForm key={field.key} {...formProps} fields={[field]} />)}
        </div>
        <div id={advancedPanelId} hidden={!advancedOpen}>
          <CredentialForm {...formProps} fields={advancedFields} />
          {installations.some(installation => installation.scopes?.length) ? (
            <div className="mt-3 space-y-2 rounded-control bg-muted/45 p-3 text-[12px] text-muted-foreground">
              <p className="font-medium">{tx("custom.workspacesTitle", "Authorized workspaces")}</p>
              {installations.filter(installation => installation.scopes?.length).map(installation => (
                <p key={installation.organization_id} className="break-words">
                  {installation.organization_name || installation.organization_id}: {installation.scopes?.join(", ")}
                </p>
              ))}
            </div>
          ) : null}
          <LinearResetConnection fields={editableFields}
            disabled={busy || dirty || connecting || loadingInstallations || disconnectingId !== null
              || !(hasSavedSecrets || feature.config_values?.["channels.linear.clientId"] || savedBaseUrl)}
            onBusyChange={setResetting} onWorkspacesChange={workspaceStore.replace}
            onWorkspaceRemoved={forgetWorkspaceMembers} onFeaturesUpdate={onFeaturesUpdate}
            onComplete={() => {
              setConnectRequestId(0);
              setConnectionGeneration(value => value + 1);
              setAdvancedOpen(false);
              setWorkspaceNotice(null);
              setWorkspaceError(null);
            }} />
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
      {credentialsSaved || installations.length > 0 ? (
        <section className="mt-5 space-y-3" aria-labelledby="linear-workspaces-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 id="linear-workspaces-heading" className="text-[13px] font-semibold text-foreground">
              {tx("custom.workspacesTitle", "Authorized workspaces")}
            </h4>
            <Button type="button" variant="ghost" size="sm"
              disabled={busy || dirty || connecting || loadingInstallations || disconnectingId !== null}
              className="h-8 gap-2 rounded-full text-[12px] text-muted-foreground"
              onClick={() => void loadInstallations(true)}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {tx("custom.refreshWorkspaces", "Refresh workspaces")}
            </Button>
          </div>
          <div role="status" aria-live="polite" className="sr-only">
            {loadingInstallations ? tx("custom.loadingWorkspaces", "Loading workspaces") : ""}
          </div>
          {loadingInstallations && !cachedInstallations ? (
            <p className="px-3 py-2.5 text-[12px] text-muted-foreground">
              {tx("custom.loadingWorkspaces", "Loading workspaces")}
            </p>
          ) : null}
          {!loadingInstallations && !workspaceError && !inspectionError && cachedInstallations?.length === 0 ? (
            <p className="rounded-control bg-muted/45 px-3 py-2.5 text-[12px] leading-5 text-muted-foreground">
              {tx("custom.noWorkspaces", "No workspaces are authorized. Connect a workspace to receive Linear agent requests.")}
            </p>
          ) : null}
          <div className="space-y-2">
            {installations.map((installation) => {
              const name = installation.organization_name || installation.organization_id;
              const needsAuthorization = installation.authorization_status === "missing_scopes"
                || installation.authorization_status === "refresh_required";
              const authorizationWarning = needsAuthorization ? (
                <span className="inline-flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
                  <AlertCircle className="h-3 w-3 shrink-0" aria-hidden />
                  {installation.authorization_status === "missing_scopes"
                    ? tx("custom.missingScopes", "Reconnect to grant: {{scopes}}", {
                      scopes: installation.missing_scopes?.join(", ") || "required scopes",
                    })
                    : installation.authorization_status === "refresh_required"
                      ? tx("custom.refreshRequired", "Authorization refresh required")
                      : tx("custom.authorized", "Authorized")}
                </span>
              ) : null;
              return (
                <article key={installation.organization_id} aria-label={name}
                  className="overflow-hidden rounded-panel border border-border/70 bg-background">
                  <header className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div className="flex min-w-0 flex-1 items-center gap-2.5">
                      <LinearAvatar name={name} url={logos[installation.organization_id]} workspace />
                      <div className="min-w-0">
                        <h5 className="truncate text-[14px] font-semibold text-foreground" title={name}>{name}</h5>
                        {authorizationWarning ? <div className="mt-1">{authorizationWarning}</div> : null}
                      </div>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button type="button" variant="ghost" size="icon"
                          disabled={workspaceActionsDisabled}
                          onPointerDown={event => { workspaceActionRef.current = event.currentTarget; }}
                          onFocus={event => { workspaceActionRef.current = event.currentTarget; }}
                          aria-label={tx("custom.workspaceActions", "Manage {{name}}", { name })}
                          title={tx("custom.workspaceActions", "Manage {{name}}", { name })}
                          className="h-8 w-8 shrink-0 rounded-full text-muted-foreground">
                          <MoreHorizontal className="h-4 w-4" aria-hidden />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" onCloseAutoFocus={event => {
                        if (skipMenuRestoreFocus.current) event.preventDefault();
                        skipMenuRestoreFocus.current = false;
                      }}>
                        <DropdownMenuItem disabled={workspaceActionsDisabled || !credentialsSaved}
                          onSelect={() => {
                            skipMenuRestoreFocus.current = true;
                            setConnectRequestId(id => id + 1);
                          }}>
                          <RefreshCw className="h-4 w-4" aria-hidden />
                          {tx("custom.reauthorize", "Reauthorize")}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem tone="destructive" disabled={workspaceActionsDisabled}
                          onSelect={() => {
                            skipMenuRestoreFocus.current = true;
                            setWorkspaceError(null);
                            setDisconnectConfirmId(installation.organization_id);
                          }}>
                          <Unplug className="h-4 w-4" aria-hidden />
                          {tx("custom.disconnect", "Remove workspace")}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </header>
                  <LinearMemberAccess organizationId={installation.organization_id}
                    configScope={memberConfigScope}
                    disabled={busy || dirty || connecting || disconnectingId !== null} />
                </article>
              );
            })}
          </div>
          {installations.length > 0 ? (
            <div className="flex items-center gap-1">
              <Button type="button" variant="ghost" size="sm"
                disabled={workspaceActionsDisabled || !credentialsSaved}
                className="h-9 gap-2 rounded-full text-[12px] text-muted-foreground"
                onClick={() => setConnectRequestId(id => id + 1)}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {tx("custom.addWorkspace", "Connect workspace")}
              </Button>
              <SettingsHint description={tx("custom.addWorkspaceHelp", "Uses the current Linear app. To connect another workspace, the app must allow installation in other workspaces; private apps only work in their own workspace. Authorizing an existing workspace updates its connection without creating a duplicate.")}>
                <span className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground">
                  <Info className="h-3.5 w-3.5" aria-hidden />
                  <span className="sr-only">{tx("custom.addWorkspaceDetails", "About connecting workspaces")}</span>
                </span>
              </SettingsHint>
            </div>
          ) : null}
          {(workspaceError && !disconnectTarget) || inspectionError ? (
            <p role="alert" className="text-[12px] leading-5 text-destructive">{workspaceError || inspectionError}</p>
          ) : null}
          {workspaceNotice ? (
            <p role="status" className="text-[12px] leading-5 text-muted-foreground">
              {workspaceNotice}
            </p>
          ) : null}
        </section>
      ) : null}
      <LinearConnectFlow key={connectionGeneration} token={token} feature={feature}
        connectRequestId={connectRequestId}
        connected={feature.runtime_status === "running" && installations.length > 0}
        idleLabel={tx("custom.connect", "Connect Linear")} onFeaturesUpdate={(payload) => {
          onFeaturesUpdate(payload);
          void workspaceStore.load(true);
        }}
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
            {installations.length === 0 || feature.runtime_status !== "running" || connecting ? (
              <fieldset disabled={busy || dirty || !credentialsSaved || loadingInstallations || disconnectingId !== null}
                className="min-w-0 sm:col-start-3">
                <legend className="sr-only">{tx("custom.authorizeTitle", "Authorize in Linear")}</legend>
                {connectButton}
              </fieldset>
            ) : null}
          </div>
        )} />
      <AlertDialog open={Boolean(disconnectTarget)} onOpenChange={open => {
        if (!open && !disconnectingId) {
          setDisconnectConfirmId(null);
          setWorkspaceError(null);
        }
      }}>
        <AlertDialogContent onEscapeKeyDown={event => {
          if (disconnectingId) event.preventDefault();
        }} onCloseAutoFocus={event => {
          event.preventDefault();
          if (workspaceActionRef.current?.isConnected) workspaceActionRef.current.focus();
          else document.getElementById(channelFieldInputId(PUBLIC_BASE_URL_KEY))?.focus();
        }}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {tx("custom.disconnectTitle", "Remove {{name}}?", {
                name: disconnectTarget?.organization_name || disconnectTarget?.organization_id || "",
              })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {tx("custom.disconnectDescription", "Revoke this workspace's authorization and clear its member access settings in nanobot. Linear issues, comments, and nanobot conversation history will be kept. Other workspaces are not affected. You can authorize this workspace again later.")}
              {installations.length === 1 ? <> {tx("custom.disconnectLast", "This is the last connected workspace, so the Linear channel will also be turned off.")}</> : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {workspaceError ? <p role="alert" className="text-[12px] leading-5 text-destructive">{workspaceError}</p> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={disconnectingId !== null}>
              {t("settings.actions.cancel", { defaultValue: "Cancel" })}
            </AlertDialogCancel>
            <Button type="button" variant="destructive"
              disabled={workspaceActionsDisabled || !disconnectTarget}
              onClick={() => { if (disconnectTarget) void disconnectWorkspace(disconnectTarget); }}>
              {disconnectingId ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              {disconnectingId
                ? tx("custom.disconnecting", "Removing…")
                : tx("custom.confirmDisconnect", "Remove workspace")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
