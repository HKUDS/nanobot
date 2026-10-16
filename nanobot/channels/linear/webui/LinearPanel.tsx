import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import { channelValuesForSubmit, defaultChannelFieldValues } from "@/components/settings/channels/CredentialForm";
import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
import { useAutoSave } from "@/components/settings/shared/useAutoSave";
import { configureChannel, disableNanobotFeature, fetchNanobotFeatures } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

import { manageLinearWorkspace } from "./api";
import type { LinearInstallationSummary } from "./types";
import { LinearConnectFlow } from "./LinearConnectFlow";
import { LinearMemberAccess } from "./LinearMemberAccess";
import { linearWorkspaceStore } from "./workspace-store";
import { linearMemberAccessStore } from "./member-access-store";
import { LinearResetConnection } from "./LinearResetConnection";
import { LinearPanelView } from "./LinearPanelView";

const PUBLIC_BASE_URL_KEY = "channels.linear.publicBaseUrl";
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
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectRequestId, setConnectRequestId] = useState(0);
  const [connectionGeneration, setConnectionGeneration] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const workspaceStore = linearWorkspaceStore(client, token, JSON.stringify([
    feature.config_values?.["channels.linear.clientId"],
    feature.config_values?.[PUBLIC_BASE_URL_KEY],
  ]));
  const { installations: cachedInstallations, logos, loading: loadingInstallations,
    error: inspectionError } = useSyncExternalStore(workspaceStore.subscribe, workspaceStore.getSnapshot);
  const installations = cachedInstallations ?? [];
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<string | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const savePromiseRef = useRef<Promise<boolean> | null>(null);
  const secretSavePromiseRef = useRef<Promise<void> | null>(null);

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
  const memberConfigScope = JSON.stringify([
    feature.config_values?.["channels.linear.clientId"],
    feature.config_values?.["channels.linear.allowFrom"],
  ]);
  const forgetWorkspaceMembers = (organizationId: string) => {
    linearMemberAccessStore(client, token, memberConfigScope, organizationId).invalidate();
  };
  const credentialsSaved = fields.filter((field) => !field.optional).every((field) =>
    configuredFields.has(field.key) || Boolean(feature.config_values?.[field.key]?.trim()),
  );
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

  const disconnectWorkspace = async (installation: LinearInstallationSummary, onRemoved: () => void) => {
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
      onRemoved();
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

  return <LinearPanelView feature={feature} showBrandLogos={showBrandLogos} fields={fields}
    advancedFields={advancedFields} formProps={formProps}
    state={{ busy, dirty, saving, saved, connecting, credentialsSaved, connectionGeneration, notice }}
    workspaces={{ installations: cachedInstallations, logos, loading: loadingInstallations, inspectionError,
      disconnectingId, notice: workspaceNotice, error: workspaceError }}
    onSave={saveSettings} onSaveSecret={saveSecret} onRefreshWorkspaces={loadInstallations}
    onDisconnectWorkspace={disconnectWorkspace} onClearWorkspaceError={() => setWorkspaceError(null)}
    onRequestConnection={() => setConnectRequestId(id => id + 1)} onConfigureMcp={onConfigureMcp}
    renderMemberAccess={(organizationId, disabled) => <LinearMemberAccess organizationId={organizationId}
      configScope={memberConfigScope} disabled={disabled} />}
    renderResetConnection={({ disabled, onComplete }) => <LinearResetConnection fields={editableFields}
      disabled={disabled} onBusyChange={setResetting} onWorkspacesChange={workspaceStore.replace}
      onWorkspaceRemoved={forgetWorkspaceMembers} onFeaturesUpdate={onFeaturesUpdate}
      onComplete={() => {
        setConnectRequestId(0);
        setConnectionGeneration(value => value + 1);
        setWorkspaceNotice(null);
        setWorkspaceError(null);
        onComplete();
      }} />}
    renderConnectFlow={(renderActions) => <LinearConnectFlow key={connectionGeneration} token={token} feature={feature}
      connectRequestId={connectRequestId} connected={feature.runtime_status === "running" && installations.length > 0}
      idleLabel={tx("custom.connect", "Connect Linear")} onFeaturesUpdate={(payload) => {
        onFeaturesUpdate(payload);
        void workspaceStore.load(true);
      }} onActiveChange={setConnecting} renderActions={renderActions} />} />;
}
