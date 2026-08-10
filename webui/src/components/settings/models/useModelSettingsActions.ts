import { useCallback, type Dispatch, type SetStateAction } from "react";
import type { TFunction } from "i18next";

import type {
  ApplySettingsPayload,
  MaybeRestartHostEngine,
  PendingRestartSections,
} from "@/components/settings/contracts";
import { agentDraftFromPayload } from "@/components/settings/models/ModelsSettings";
import {
  CUSTOM_PROVIDER_CREATION_KEY,
  providerFormFromRow,
  type CustomProviderDraft,
} from "@/components/settings/models/ProviderSettings";
import type { ModelSettingsState } from "@/components/settings/models/useModelSettingsState";
import { normalizeContextWindowTokens } from "@/components/settings/shared/ModelControls";
import {
  completeProviderOAuth,
  createModelConfiguration,
  createProviderSettings,
  deleteModelConfiguration,
  loginProviderOAuth,
  logoutProviderOAuth,
  migrateModelConfigurations,
  updateModelCallOrder,
  updateModelConfiguration,
  updateProviderSettings,
} from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import type {
  ProviderOAuthAuthorizationRequired,
  ProviderOAuthCompletionResult,
  ProviderOAuthLoginResult,
  ProviderOAuthPending,
  ProviderSettingsUpdate,
  SettingsPayload,
} from "@/lib/types";

function isProviderOAuthAuthorizationRequired(
  payload: ProviderOAuthLoginResult,
): payload is ProviderOAuthAuthorizationRequired {
  return (payload as ProviderOAuthAuthorizationRequired).status === "authorization_required";
}

function isProviderOAuthPending(
  payload: ProviderOAuthCompletionResult,
): payload is ProviderOAuthPending {
  return (payload as ProviderOAuthPending).status === "pending";
}

interface ModelSettingsActionsOptions {
  state: ModelSettingsState;
  settings: SettingsPayload | null;
  client: NanobotClient;
  t: TFunction;
  applyPayload: ApplySettingsPayload;
  maybeRestartHostEngine: MaybeRestartHostEngine;
  setPendingRestartSections: Dispatch<SetStateAction<PendingRestartSections>>;
  setError: Dispatch<SetStateAction<string | null>>;
  onModelNameChange: (modelName: string | null) => void;
  remoteBrowserAccess: boolean;
  closeProviderOAuthFlow: () => void;
  installCapabilities: (names: string[]) => Promise<boolean>;
  modelDirty: boolean;
  configuredModelProviderOptions: Array<{ name: string; label: string }>;
}

export function useModelSettingsActions({
  state,
  settings,
  client,
  t,
  applyPayload,
  maybeRestartHostEngine,
  setPendingRestartSections,
  setError,
  onModelNameChange,
  remoteBrowserAccess,
  closeProviderOAuthFlow,
  installCapabilities,
  modelDirty,
  configuredModelProviderOptions,
}: ModelSettingsActionsOptions) {
  const {
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
  } = state;

  const saveModelSettings = async () => {
    if (
      !settings ||
      saving ||
      modelCallOrderSaving ||
      modelConfigurationSaving
    ) {
      return;
    }

    if (modelPresetCreating) {
      const label = form.presetLabel.trim();
      const provider = form.provider.trim();
      const model = form.model.trim();
      if (
        !label ||
        !provider ||
        !model ||
        form.maxTokens <= 0 ||
        form.contextWindowTokens <= 0 ||
        form.temperature < 0 ||
        form.temperature > 2
      ) {
        return;
      }
      setModelConfigurationSaving(true);
      try {
        const payload = await createModelConfiguration(client, {
          label,
          provider,
          model,
          maxTokens: form.maxTokens,
          contextWindowTokens: form.contextWindowTokens,
          temperature: form.temperature,
          reasoningEffort: form.reasoningEffort || null,
        });
        const createdPreset = payload.created_model_preset;
        const nextOrder = createdPreset ? [...modelCallOrder, createdPreset] : null;
        applyPayload(payload);
        if (createdPreset) {
          setForm(agentDraftFromPayload(payload, createdPreset));
        }

        let finalPayload = payload;
        if (nextOrder) {
          const orderedPayload = await updateModelCallOrder(client, nextOrder);
          applyPayload(orderedPayload);
          finalPayload = orderedPayload;
        }
        if (createdPreset) {
          setForm(agentDraftFromPayload(finalPayload, createdPreset));
        }
        modelPresetBeforeCreateRef.current = null;
        onModelNameChange(finalPayload.agent.model || null);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setModelConfigurationSaving(false);
      }
      return;
    }

    if (!modelDirty) return;
    const selectedPreset = settings.model_presets.find(
      (preset) => !preset.is_default && preset.name === form.modelPreset,
    );
    if (!selectedPreset) return;
    const reasoningEffort = form.reasoningEffort || null;
    setSaving(true);
    try {
      const payload = await updateModelConfiguration(client, {
        name: selectedPreset.name,
        label:
          form.presetLabel.trim() !== selectedPreset.label
            ? form.presetLabel.trim()
            : undefined,
        model: form.model !== selectedPreset.model ? form.model : undefined,
        provider: form.provider !== selectedPreset.provider ? form.provider : undefined,
        maxTokens:
          form.maxTokens !== selectedPreset.max_tokens ? form.maxTokens : undefined,
        contextWindowTokens:
          form.contextWindowTokens !==
          normalizeContextWindowTokens(selectedPreset.context_window_tokens)
            ? form.contextWindowTokens
            : undefined,
        temperature:
          form.temperature !== selectedPreset.temperature ? form.temperature : undefined,
        reasoningEffort:
          reasoningEffort !== selectedPreset.reasoning_effort ? reasoningEffort : undefined,
      });
      applyPayload(payload);
      setForm(agentDraftFromPayload(payload, selectedPreset.name));
      onModelNameChange(payload.agent.model || null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const beginModelPresetCreation = () => {
    if (!settings || saving || modelCallOrderSaving || modelConfigurationSaving) return;
    const primaryPreset = settings.model_presets.find(
      (preset) => !preset.is_default && preset.name === settings.model_call_order?.[0],
    );
    const currentProvider = primaryPreset?.provider === "auto"
      ? primaryPreset.resolved_provider ?? settings.agent.resolved_provider
      : primaryPreset?.provider ?? settings.agent.provider;
    const provider =
      configuredModelProviderOptions.find((option) => option.name === currentProvider)?.name ??
      configuredModelProviderOptions[0]?.name ??
      "";
    modelPresetBeforeCreateRef.current = form.modelPreset;
    setForm((prev) => ({
      ...prev,
      modelPreset: "",
      presetLabel: "",
      provider,
      model: "",
      maxTokens: primaryPreset?.max_tokens ?? settings.agent.max_tokens,
      contextWindowTokens: normalizeContextWindowTokens(
        primaryPreset?.context_window_tokens ?? settings.agent.context_window_tokens,
      ),
      temperature: primaryPreset?.temperature ?? settings.agent.temperature,
      reasoningEffort: primaryPreset?.reasoning_effort ?? settings.agent.reasoning_effort ?? "",
    }));
    setModelPresetCreating(true);
  };

  const cancelModelPresetCreation = () => {
    if (!settings || modelConfigurationSaving) return;
    const previousPreset = modelPresetBeforeCreateRef.current;
    setModelPresetCreating(false);
    setForm(agentDraftFromPayload(settings, previousPreset ?? undefined));
    modelPresetBeforeCreateRef.current = null;
  };

  const changeModelCallOrder = async (nextOrder: string[]) => {
    const unchanged =
      nextOrder.length === modelCallOrder.length &&
      nextOrder.every((name, index) => name === modelCallOrder[index]);
    if (
      !settings ||
      saving ||
      modelCallOrderSaving ||
      modelConfigurationSaving ||
      nextOrder.length === 0 ||
      unchanged
    ) {
      return;
    }
    const previousOrder = [...modelCallOrder];
    setModelCallOrder(nextOrder);
    setModelCallOrderSaving(true);
    try {
      const payload = await updateModelCallOrder(client, nextOrder);
      applyPayload(payload, { preserveAgentForm: true });
      onModelNameChange(payload.agent.model || null);
      setError(null);
    } catch (err) {
      setModelCallOrder(previousOrder);
      setError((err as Error).message);
    } finally {
      setModelCallOrderSaving(false);
    }
  };

  const handleMigrateModelConfigurations = async () => {
    if (modelMigrationSaving) return;
    setModelMigrationSaving(true);
    try {
      const payload = await migrateModelConfigurations(client);
      applyPayload(payload);
      onModelNameChange(payload.agent.model || null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setModelMigrationSaving(false);
    }
  };

  const handleDeleteModelConfiguration = async () => {
    if (
      !modelPresetPendingDelete ||
      saving ||
      modelCallOrderSaving ||
      modelConfigurationSaving
    ) {
      return;
    }
    setSaving(true);
    try {
      const payload = await deleteModelConfiguration(client, modelPresetPendingDelete.name);
      applyPayload(payload);
      setModelPresetPendingDelete(null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveProvider = async (providerName: string) => {
    if (providerSaving) return;
    const provider = settings?.providers.find((item) => item.name === providerName);
    if (!provider) return;
    const isOauthProvider = provider.auth_type === "oauth";
    const providerForm = providerForms[providerName] ?? providerFormFromRow(provider);
    const apiKey = providerForm.apiKey.trim();
    const apiKeyRequired = provider.api_key_required ?? true;
    if (!isOauthProvider && !provider.configured && apiKeyRequired && !apiKey) {
      setError(t("settings.byok.apiKeyRequired"));
      return;
    }
    setProviderSaving(providerName);
    try {
      const supportName = providerName === "bedrock"
        ? "bedrock"
        : providerName === "azure_openai"
          ? "azure"
          : null;
      if (supportName && !(await installCapabilities([supportName]))) return;
      const update: ProviderSettingsUpdate = { provider: providerName };
      if (!isOauthProvider) {
        update.apiKey = apiKey || undefined;
        update.apiBase = providerForm.apiBase.trim();
        if (provider.is_custom) update.displayName = providerForm.displayName.trim();
      }
      for (const field of provider.advanced_fields ?? []) {
        if (field === "api_type") update.apiType = providerForm.apiType;
        if (field === "proxy") update.proxy = providerForm.proxy.trim();
        if (field === "extra_headers") {
          update.extraHeaders = providerForm.extraHeaders.trim();
        }
        if (field === "extra_body") update.extraBody = providerForm.extraBody.trim();
        if (field === "extra_query") update.extraQuery = providerForm.extraQuery.trim();
        if (field === "thinking_style") {
          update.thinkingStyle = providerForm.thinkingStyle.trim();
        }
        if (field === "region") update.region = providerForm.region.trim();
        if (field === "profile") update.profile = providerForm.profile.trim();
      }
      const payload = await updateProviderSettings(client, update);
      applyPayload(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, image: true }));
      }
      await maybeRestartHostEngine(payload);
      setProviderForms((prev) => ({
        ...prev,
        [providerName]: {
          ...providerForm,
          displayName: providerForm.displayName.trim(),
          apiKey: "",
          apiBase: providerForm.apiBase.trim(),
          proxy: providerForm.proxy.trim(),
          thinkingStyle: providerForm.thinkingStyle.trim(),
          region: providerForm.region.trim(),
          profile: providerForm.profile.trim(),
        },
      }));
      setVisibleProviderKeys((prev) => ({ ...prev, [providerName]: false }));
      setEditingProviderKeys((prev) => ({ ...prev, [providerName]: false }));
      if (!isOauthProvider) setExpandedProvider(null);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProviderSaving(null);
    }
  };

  const createCustomProvider = async (draft: CustomProviderDraft): Promise<boolean> => {
    if (providerSaving) return false;
    setProviderSaving(CUSTOM_PROVIDER_CREATION_KEY);
    try {
      const payload = await createProviderSettings(client, {
        name: draft.name.trim(),
        apiKey: draft.apiKey.trim() || undefined,
        apiBase: draft.apiBase.trim(),
        proxy: draft.proxy.trim(),
        extraHeaders: draft.extraHeaders.trim(),
        extraBody: draft.extraBody.trim(),
        extraQuery: draft.extraQuery.trim(),
        thinkingStyle: draft.thinkingStyle.trim(),
      });
      applyPayload(payload);
      setExpandedProvider(null);
      setError(null);
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setProviderSaving(null);
    }
  };

  const runProviderOAuth = async (providerName: string, action: "login" | "logout") => {
    if (providerSaving) return;
    let popup: Window | null = null;
    if (
      action === "login"
      && providerName === "xai_grok"
      && !remoteBrowserAccess
    ) {
      try {
        popup = window.open("about:blank", "_blank");
        if (popup) popup.opener = null;
      } catch {
        popup = null;
      }
    }
    setProviderSaving(providerName);
    try {
      const payload =
        action === "login"
          ? await loginProviderOAuth(
              client,
              providerName,
              providerName === "openai_codex" && remoteBrowserAccess,
            )
          : await logoutProviderOAuth(client, providerName);
      if (isProviderOAuthAuthorizationRequired(payload)) {
        try {
          if (popup && !popup.closed) popup.location.href = payload.authorization_url;
        } catch {
          // The dialog keeps the authorization link available when the popup was closed.
        }
        providerOAuthFlowRef.current = payload;
        setProviderOAuthFlow(payload);
        setProviderOAuthResponse("");
        setProviderOAuthDialogError(null);
        setExpandedProvider(providerName);
        setError(null);
        return;
      }
      popup?.close();
      closeProviderOAuthFlow();
      applyPayload(payload);
      setExpandedProvider(providerName);
      setError(null);
    } catch (err) {
      popup?.close();
      setError((err as Error).message);
    } finally {
      setProviderSaving(null);
    }
  };

  const completeProviderOAuthResponse = async () => {
    const flow = providerOAuthFlowRef.current;
    const authorizationResponse = providerOAuthResponse.trim();
    if (!flow || !authorizationResponse || providerOAuthCompleting) return;
    setProviderOAuthCompleting(true);
    setProviderOAuthDialogError(null);
    try {
      const payload = await completeProviderOAuth(
        client,
        flow.provider,
        flow.flow_id,
        authorizationResponse,
      );
      if (providerOAuthFlowRef.current?.flow_id !== flow.flow_id) return;
      if (isProviderOAuthPending(payload)) return;
      applyPayload(payload);
      setExpandedProvider(flow.provider);
      setError(null);
      closeProviderOAuthFlow();
    } catch (err) {
      if (providerOAuthFlowRef.current?.flow_id === flow.flow_id) {
        setProviderOAuthDialogError((err as Error).message);
      }
    } finally {
      setProviderOAuthCompleting(false);
    }
  };

  const resetProviderDraft = useCallback((providerName: string) => {
    const provider = settings?.providers.find((item) => item.name === providerName);
    if (!provider) return;
    setProviderForms((prev) => ({
      ...prev,
      [providerName]: providerFormFromRow(provider),
    }));
    setVisibleProviderKeys((prev) => ({ ...prev, [providerName]: false }));
    setEditingProviderKeys((prev) => ({ ...prev, [providerName]: false }));
  }, [settings]);

  const handleToggleProvider = useCallback((providerName: string) => {
    if (expandedProvider) resetProviderDraft(expandedProvider);
    setExpandedProvider(expandedProvider === providerName ? null : providerName);
  }, [expandedProvider, resetProviderDraft]);

  const toggleProviderKeyVisibility = (providerName: string) => {
    const isVisible = visibleProviderKeys[providerName];
    setVisibleProviderKeys((prev) => ({ ...prev, [providerName]: !isVisible }));
  };

  const toggleProviderKeyEditing = (providerName: string) => {
    setEditingProviderKeys((prev) => {
      const nextEditing = !prev[providerName];
      if (!nextEditing) {
        setProviderForms((forms) => ({
          ...forms,
          [providerName]: {
            ...(forms[providerName] ?? providerFormFromRow(
              settings?.providers.find((provider) => provider.name === providerName) ?? {
                name: providerName,
                label: providerName,
                configured: false,
              },
            )),
            apiKey: "",
          },
        }));
        setVisibleProviderKeys((visible) => ({ ...visible, [providerName]: false }));
      }
      return { ...prev, [providerName]: nextEditing };
    });
  };

  return {
    beginModelPresetCreation,
    cancelModelPresetCreation,
    changeModelCallOrder,
    completeProviderOAuthResponse,
    createCustomProvider,
    handleDeleteModelConfiguration,
    handleMigrateModelConfigurations,
    handleToggleProvider,
    resetProviderDraft,
    runProviderOAuth,
    saveModelSettings,
    saveProvider,
    toggleProviderKeyEditing,
    toggleProviderKeyVisibility,
  };
}
