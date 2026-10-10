import { useRef, useState } from "react";

import {
  DEFAULT_AGENT_SETTINGS_DRAFT,
  agentDraftFromPayload,
  type AgentSettingsDraft,
} from "@/components/settings/models/ModelsSettings";
import type { ProviderForm } from "@/components/settings/models/providerForm";
import type { ProviderOAuthAuthorizationRequired, SettingsPayload } from "@/lib/types";

export interface ProviderOperation {
  provider: string;
  action: "save" | "create" | "login" | "logout";
}

export function useModelSettingsState(initialSettings: SettingsPayload | null) {
  const initialForm = initialSettings
    ? agentDraftFromPayload(initialSettings)
    : DEFAULT_AGENT_SETTINGS_DRAFT;
  const [saving, setSaving] = useState(false);
  const [modelPresetCreating, setModelPresetCreating] = useState(false);
  const [modelPresetNameError, setModelPresetNameError] = useState<string | null>(null);
  const [modelConfigurationSaving, setModelConfigurationSaving] = useState(false);
  const [modelCallOrderSaving, setModelCallOrderSaving] = useState(false);
  const [modelMigrationSaving, setModelMigrationSaving] = useState(false);
  const [modelPresetPendingDelete, setModelPresetPendingDelete] =
    useState<SettingsPayload["model_presets"][number] | null>(null);
  const modelPresetBeforeCreateRef = useRef<string | null>(null);
  const [providerOperation, setProviderOperation] = useState<ProviderOperation | null>(null);
  const providerSaving = providerOperation?.provider ?? null;
  const [providerOAuthFlow, setProviderOAuthFlow] =
    useState<ProviderOAuthAuthorizationRequired | null>(null);
  const providerOAuthFlowRef = useRef<ProviderOAuthAuthorizationRequired | null>(null);
  const [providerOAuthResponse, setProviderOAuthResponse] = useState("");
  const [providerOAuthCompleting, setProviderOAuthCompleting] = useState(false);
  const [providerOAuthDialogError, setProviderOAuthDialogError] = useState<string | null>(null);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [providerForms, setProviderForms] = useState<Record<string, ProviderForm>>({});
  const [visibleProviderKeys, setVisibleProviderKeys] = useState<Record<string, boolean>>({});
  const [editingProviderKeys, setEditingProviderKeys] = useState<Record<string, boolean>>({});
  const [form, setForm] = useState<AgentSettingsDraft>(initialForm);
  const [modelPresetEditingName, setModelPresetEditingName] = useState(
    initialForm.modelPreset,
  );
  const [modelCallOrder, setModelCallOrder] = useState<string[]>(
    () => initialSettings?.model_call_order ?? [],
  );

  return {
    editingProviderKeys,
    expandedProvider,
    form,
    modelCallOrder,
    modelCallOrderSaving,
    modelConfigurationSaving,
    modelMigrationSaving,
    modelPresetBeforeCreateRef,
    modelPresetCreating,
    modelPresetEditingName,
    modelPresetNameError,
    modelPresetPendingDelete,
    providerForms,
    providerOAuthCompleting,
    providerOAuthDialogError,
    providerOAuthFlow,
    providerOAuthFlowRef,
    providerOAuthResponse,
    providerSaving,
    providerOperation,
    saving,
    setEditingProviderKeys,
    setExpandedProvider,
    setForm,
    setModelCallOrder,
    setModelCallOrderSaving,
    setModelConfigurationSaving,
    setModelMigrationSaving,
    setModelPresetCreating,
    setModelPresetEditingName,
    setModelPresetNameError,
    setModelPresetPendingDelete,
    setProviderForms,
    setProviderOAuthCompleting,
    setProviderOAuthDialogError,
    setProviderOAuthFlow,
    setProviderOAuthResponse,
    setProviderOperation,
    setSaving,
    setVisibleProviderKeys,
    visibleProviderKeys,
  };
}

export type ModelSettingsState = ReturnType<typeof useModelSettingsState>;
