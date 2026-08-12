import { useRef, useState } from "react";

import {
  DEFAULT_AGENT_SETTINGS_DRAFT,
  agentDraftFromPayload,
  type AgentSettingsDraft,
} from "@/components/settings/models/ModelsSettings";
import type { ProviderForm } from "@/components/settings/models/ProviderSettings";
import type { ProviderOAuthAuthorizationRequired, SettingsPayload } from "@/lib/types";

export function useModelSettingsState(initialSettings: SettingsPayload | null) {
  const [saving, setSaving] = useState(false);
  const [modelPresetCreating, setModelPresetCreating] = useState(false);
  const [modelConfigurationSaving, setModelConfigurationSaving] = useState(false);
  const [modelCallOrderSaving, setModelCallOrderSaving] = useState(false);
  const [modelMigrationSaving, setModelMigrationSaving] = useState(false);
  const [modelPresetPendingDelete, setModelPresetPendingDelete] =
    useState<SettingsPayload["model_presets"][number] | null>(null);
  const modelPresetBeforeCreateRef = useRef<string | null>(null);
  const [providerSaving, setProviderSaving] = useState<string | null>(null);
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
  const [form, setForm] = useState<AgentSettingsDraft>(() =>
    initialSettings ? agentDraftFromPayload(initialSettings) : DEFAULT_AGENT_SETTINGS_DRAFT,
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
    modelPresetPendingDelete,
    providerForms,
    providerOAuthCompleting,
    providerOAuthDialogError,
    providerOAuthFlow,
    providerOAuthFlowRef,
    providerOAuthResponse,
    providerSaving,
    saving,
    setEditingProviderKeys,
    setExpandedProvider,
    setForm,
    setModelCallOrder,
    setModelCallOrderSaving,
    setModelConfigurationSaving,
    setModelMigrationSaving,
    setModelPresetCreating,
    setModelPresetPendingDelete,
    setProviderForms,
    setProviderOAuthCompleting,
    setProviderOAuthDialogError,
    setProviderOAuthFlow,
    setProviderOAuthResponse,
    setProviderSaving,
    setSaving,
    setVisibleProviderKeys,
    visibleProviderKeys,
  };
}

export type ModelSettingsState = ReturnType<typeof useModelSettingsState>;
