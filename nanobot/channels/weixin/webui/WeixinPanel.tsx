import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import type { ChannelPluginPanelProps } from "@/channel-plugins/types";
import {
  channelValuesForSave,
  defaultChannelFieldValues,
} from "@/components/settings/channels/CredentialForm";
import { configureChannel } from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

import { WeixinConnectFlow } from "./WeixinConnectFlow";
import { WeixinPanelView } from "./WeixinPanelView";
import {
  WEIXIN_AUTH_EXPIRED_MESSAGE,
  localizeBooleanFields,
  weixinRuntimeError,
  weixinSetupFields,
} from "./presentation";

export function WeixinPanel({
  token,
  feature,
  actionKey,
  showBrandLogos,
  onAction,
  onFeaturesUpdate,
  connectRequestId = 0,
}: ChannelPluginPanelProps) {
  const { client } = useClient();
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const channelTx = channelTranslator(t, "weixin");
  const authExpired = feature.runtime_error === WEIXIN_AUTH_EXPIRED_MESSAGE;
  const [authRecoveryActive, setAuthRecoveryActive] = useState(authExpired);
  const runtimeError = weixinRuntimeError(feature.runtime_error, channelTx)
    ?? (authRecoveryActive ? channelTx("custom.expired", WEIXIN_AUTH_EXPIRED_MESSAGE) : undefined);
  const [touchedFields, setTouchedFields] = useState<Set<string>>(() => new Set());
  const [saving, setSaving] = useState(false);
  const [saveRevision, setSaveRevision] = useState(0);
  const [attemptedRevision, setAttemptedRevision] = useState(0);
  const [saveState, setSaveState] = useState<"idle" | "saved">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const configValuesKey = JSON.stringify(feature.config_values ?? {});
  const setupFieldsKey = JSON.stringify(feature.setup?.fields ?? []);
  const configuredFields = useMemo(
    () => new Set(feature.configured_fields ?? []),
    [feature.configured_fields],
  );
  const onLabel = tx("settings.values.on", "On");
  const offLabel = tx("settings.values.off", "Off");
  const setupFields = weixinSetupFields(
    feature,
    i18n.resolvedLanguage ?? i18n.language,
  );
  const primaryFields = localizeBooleanFields(setupFields.primary, onLabel, offLabel);
  const advancedFields = localizeBooleanFields(setupFields.advanced, onLabel, offLabel);
  const editableFields = [...primaryFields, ...advancedFields];
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() =>
    defaultChannelFieldValues(editableFields, feature.config_values),
  );
  const fieldValuesRef = useRef(fieldValues);
  const touchedFieldsRef = useRef(touchedFields);
  const editableFieldsRef = useRef(editableFields);
  const saveContextRef = useRef({
    token,
    enabled: feature.enabled,
    onFeaturesUpdate,
  });
  editableFieldsRef.current = editableFields;
  saveContextRef.current = {
    token,
    enabled: feature.enabled,
    onFeaturesUpdate,
  };

  useEffect(() => {
    if (authExpired) {
      setAuthRecoveryActive(true);
    } else if (feature.runtime_status === "running") {
      setAuthRecoveryActive(false);
    }
  }, [authExpired, feature.runtime_status]);

  useEffect(() => {
    const nextValues = defaultChannelFieldValues(editableFields, feature.config_values);
    for (const key of touchedFieldsRef.current) {
      nextValues[key] = fieldValuesRef.current[key] ?? "";
    }
    fieldValuesRef.current = nextValues;
    setFieldValues(nextValues);
  }, [configValuesKey, setupFieldsKey]);

  useEffect(() => {
    if (saveState !== "saved") return;
    const timeout = window.setTimeout(() => setSaveState("idle"), 1500);
    return () => window.clearTimeout(timeout);
  }, [saveState]);

  const saveSettings = useCallback(async (
    values: Record<string, string>,
    savedFields: Set<string>,
  ) => {
    const context = saveContextRef.current;
    setSaving(true);
    setSaveError(null);
    setSaveState("idle");
    try {
      const payload = await configureChannel(
        client,
        "weixin",
        channelValuesForSave(editableFieldsRef.current, values),
        { enable: context.enabled },
      );
      const remainingFields = new Set(touchedFieldsRef.current);
      for (const key of savedFields) {
        if (fieldValuesRef.current[key] === values[key]) remainingFields.delete(key);
      }
      touchedFieldsRef.current = remainingFields;
      setTouchedFields(remainingFields);
      setSaveState(remainingFields.size ? "idle" : "saved");
      if (payload.nanobot_features) context.onFeaturesUpdate(payload.nanobot_features);
    } catch (err) {
      setSaveError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }, [client]);

  useEffect(() => {
    if (
      !editableFields.length
      || !touchedFields.size
      || saving
      || saveRevision <= attemptedRevision
    ) return;
    const timeout = window.setTimeout(() => {
      setAttemptedRevision(saveRevision);
      void saveSettings(
        { ...fieldValuesRef.current },
        new Set(touchedFieldsRef.current),
      );
    }, 500);
    return () => window.clearTimeout(timeout);
  }, [
    attemptedRevision,
    editableFields.length,
    saveRevision,
    saveSettings,
    saving,
    touchedFields.size,
  ]);

  const setFieldValue = (key: string, value: string) => {
    if (fieldValuesRef.current[key] === value) return;
    const nextValues = { ...fieldValuesRef.current, [key]: value };
    const nextTouchedFields = new Set(touchedFieldsRef.current).add(key);
    fieldValuesRef.current = nextValues;
    touchedFieldsRef.current = nextTouchedFields;
    setFieldValues(nextValues);
    setTouchedFields(nextTouchedFields);
    setSaveError(null);
    setSaveState("idle");
    setSaveRevision((current) => current + 1);
  };

  return (
    <WeixinPanelView
      feature={feature}
      actionKey={actionKey}
      showBrandLogos={showBrandLogos}
      primaryFields={primaryFields}
      advancedFields={advancedFields}
      fieldValues={fieldValues}
      configuredFields={configuredFields}
      secretVisibilityKey={`${configValuesKey}:${setupFieldsKey}`}
      runtimeError={runtimeError}
      saving={saving}
      saveState={saveState}
      saveError={saveError}
      connectFlow={<WeixinConnectFlow
        token={token}
        feature={feature}
        authRecoveryActive={authRecoveryActive}
        idleLabel={channelTx("setup.primaryAction", "Connect WeChat")}
        connectRequestId={connectRequestId}
        onFeaturesUpdate={onFeaturesUpdate}
      />}
      onInstall={() => onAction("enable", feature.name)}
      onFieldChange={setFieldValue}
    />
  );
}
