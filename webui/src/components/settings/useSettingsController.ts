import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { imageGenerationFormFromPayload } from "@/components/settings/capabilities/ImageGenerationSettings";
import {
  networkSafetyFormFromPayload,
  visibleWebuiDefaultAccessMode,
} from "@/components/settings/capabilities/SecuritySettings";
import {
  DEFAULT_TRANSCRIPTION_SETTINGS,
  transcriptionFormFromPayload,
} from "@/components/settings/capabilities/TranscriptionSettings";
import { useCapabilitySettingsActions } from "@/components/settings/capabilities/useCapabilitySettingsActions";
import { useCapabilitySettingsState } from "@/components/settings/capabilities/useCapabilitySettingsState";
import { webSearchFormFromPayload } from "@/components/settings/capabilities/WebSettings";
import type {
  ApplySettingsPayload,
  PendingRestartSections,
  RestartAwarePayload,
  SettingsSectionKey,
} from "@/components/settings/contracts";
import { agentDraftFromPayload } from "@/components/settings/models/ModelsSettings";
import { useModelSettingsActions } from "@/components/settings/models/useModelSettingsActions";
import {
  useProviderFormsSync,
  useProviderOAuthPolling,
} from "@/components/settings/models/useModelSettingsEffects";
import { useModelSettingsState } from "@/components/settings/models/useModelSettingsState";
import { normalizeContextWindowTokens } from "@/components/settings/shared/ModelControls";
import { createSystemSettingsActions } from "@/components/settings/system/createSystemSettingsActions";
import { useSystemSettingsEffects } from "@/components/settings/system/useSystemSettingsEffects";
import { useSystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchSettings, fetchSettingsUsage } from "@/lib/api";
import {
  readLocalPreferences,
  writeLocalPreferences,
  type LocalPreferences,
} from "@/lib/local-preferences";
import { isLoopbackHost } from "@/lib/network";
import type { SettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

interface SettingsControllerOptions {
  initialSection: SettingsSectionKey;
  initialSettings: SettingsPayload | null;
  onModelNameChange: (modelName: string | null) => void;
  onSettingsChange?: (payload: SettingsPayload) => void;
  onSectionChange?: (section: SettingsSectionKey) => void;
  onRestart?: () => void;
  onNativeEngineRestart?: () => Promise<string>;
}

const EMPTY_PENDING_RESTART_SECTIONS: PendingRestartSections = {
  runtime: false,
  browser: false,
  image: false,
};

function pendingRestartSectionsFromPayload(payload: SettingsPayload): PendingRestartSections {
  const sections = payload.restart_required_sections ?? [];
  return {
    runtime: sections.includes("runtime"),
    browser: sections.includes("browser"),
    image: sections.includes("image"),
  };
}

export function useSettingsController({
  initialSection,
  initialSettings,
  onModelNameChange,
  onSettingsChange,
  onSectionChange,
  onRestart,
  onNativeEngineRestart,
}: SettingsControllerOptions) {
  const { t } = useTranslation();
  const { client, getToken, token } = useClient();
  const pageVisible = usePageVisibility();
  const remoteBrowserAccess =
    typeof window !== "undefined" && !isLoopbackHost(window.location.hostname);
  const [settings, setSettings] = useState<SettingsPayload | null>(() => initialSettings);
  const [loading, setLoading] = useState(() => initialSettings === null);
  const [hostEngineApplying, setHostEngineApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SettingsSectionKey>(initialSection);
  const [pendingRestartSections, setPendingRestartSections] = useState<PendingRestartSections>(
    EMPTY_PENDING_RESTART_SECTIONS,
  );
  const [localPrefs, setLocalPrefs] = useState<LocalPreferences>(() => readLocalPreferences());
  const modelState = useModelSettingsState(initialSettings);
  const {
    editingProviderKeys, expandedProvider, form, modelCallOrder, modelCallOrderSaving,
    modelConfigurationSaving, modelMigrationSaving, modelPresetBeforeCreateRef,
    modelPresetCreating, modelPresetEditingName, modelPresetNameError, modelPresetPendingDelete,
    providerForms, providerOAuthCompleting,
    providerOAuthDialogError, providerOAuthFlow, providerOAuthFlowRef, providerOAuthResponse,
    providerSaving, saving, setForm,
    setModelCallOrder, setModelPresetCreating, setModelPresetEditingName, setModelPresetNameError,
    setModelPresetPendingDelete,
    setProviderForms, setProviderOAuthCompleting, setProviderOAuthDialogError,
    setProviderOAuthFlow, setProviderOAuthResponse, visibleProviderKeys,
  } = modelState;
  const capabilityState = useCapabilitySettingsState(initialSettings);
  const {
    imageGenerationForm, imageGenerationSaving, networkSafetyForm, networkSafetySaving,
    setImageGenerationForm, setNetworkSafetyForm, setTranscriptionForm, setWebSearchForm,
    setWebSearchKeyEditing, setWebSearchKeyVisible, transcriptionForm,
    transcriptionSaving, webSearchForm, webSearchKeyEditing, webSearchKeyVisible,
    webSearchSaving,
  } = capabilityState;
  const systemState = useSystemSettingsState();
  const {
    apiService, apiServiceAction, apiServiceError, apiServiceLoading, appsKindFilter, appsQuery,
    automationAction, automationPendingDelete, automationPendingEdit, automations,
    automationsError, automationsFilter, automationsLoading, automationsQuery, automationsSort,
    channelsQuery, cliApps, cliAppsAction, cliAppsError, cliAppsFocusName, cliAppsLoading,
    cliAppsMessage, customMcpForm, mcpConfigImport, mcpError, mcpFieldValues, mcpMessage,
    mcpOAuthCallbackError, mcpOAuthCallbackUrl, mcpOAuthCompleting, mcpOAuthFlow,
    mcpOAuthPopupBlocked, mcpPresetAction, mcpPresets, mcpPresetsLoading, nanobotFeatureAction,
    nanobotFeatureConfirm, nanobotFeatures, nanobotFeaturesError, nanobotFeaturesLoading,
    setAppsKindFilter, setAppsQuery, setAutomationPendingDelete,
    setAutomationPendingEdit, setAutomationsFilter,
    setAutomationsQuery, setAutomationsSort, setChannelsQuery,
    setCliAppsError,
    setCliAppsMessage, setCustomMcpForm, setMcpConfigImport, setMcpError, setMcpFieldValues,
    setMcpMessage, setMcpOAuthCallbackError, setMcpOAuthCallbackUrl,
    setNanobotFeatureConfirm, setNanobotFeatures,
    setNanobotFeaturesError,
  } = systemState;
  const featureCatalog = nanobotFeatures?.features ?? [];

  useEffect(() => {
    setActiveSection(initialSection);
  }, [initialSection]);

  const selectSection = useCallback(
    (section: SettingsSectionKey) => {
      setActiveSection(section);
      onSectionChange?.(section);
    },
    [onSectionChange],
  );
  const applyPayload: ApplySettingsPayload = useCallback(
    (
      payload: SettingsPayload,
      options: { preserveAgentForm?: boolean } = {},
    ) => {
      setSettings(payload);
      if (!options.preserveAgentForm) {
        const nextForm = agentDraftFromPayload(payload);
        setForm(nextForm);
        setModelPresetEditingName(nextForm.modelPreset);
        setModelPresetCreating(false);
      }
      setModelCallOrder(payload.model_call_order ?? []);
      setWebSearchForm((prev) => webSearchFormFromPayload(payload, prev));
      setImageGenerationForm(imageGenerationFormFromPayload(payload));
      setTranscriptionForm(transcriptionFormFromPayload(payload));
      setNetworkSafetyForm(networkSafetyFormFromPayload(payload));
      if (payload.restart_required_sections) {
        setPendingRestartSections(pendingRestartSectionsFromPayload(payload));
      }
      onSettingsChange?.(payload);
    },
    [onSettingsChange],
  );

  const closeProviderOAuthFlow = useCallback(() => {
    providerOAuthFlowRef.current = null;
    setProviderOAuthFlow(null);
    setProviderOAuthResponse("");
    setProviderOAuthCompleting(false);
    setProviderOAuthDialogError(null);
  }, []);
  useProviderOAuthPolling({
    state: modelState,
    client,
    applyPayload,
    setError,
    closeProviderOAuthFlow,
  });

  useEffect(() => {
    if (!initialSettings || settings !== null) return;
    applyPayload(initialSettings);
    setLoading(false);
  }, [applyPayload, initialSettings, settings]);

  useEffect(() => {
    let cancelled = false;
    const showLoading = settings === null;
    if (showLoading) setLoading(true);
    fetchSettings(getToken())
      .then((payload) => {
        if (!cancelled) {
          applyPayload(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled && showLoading) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applyPayload, getToken]);

  const hasSettings = settings !== null;
  useEffect(() => {
    if (activeSection !== "overview" || !hasSettings || !pageVisible) return;
    let cancelled = false;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const usage = await fetchSettingsUsage(getToken());
        if (!cancelled) {
          setSettings((current) => (current ? { ...current, usage } : current));
        }
      } catch {
        // Usage is best-effort telemetry; the settings snapshot remains usable.
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 5000);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [activeSection, getToken, hasSettings, pageVisible]);
  const { refreshAutomations } = useSystemSettingsEffects({
    state: systemState,
    activeSection,
    getToken,
    pageVisible,
  });

  useEffect(() => {
    writeLocalPreferences(localPrefs);
  }, [localPrefs]);
  useProviderFormsSync(modelState, settings);

  const modelDirty = useMemo(() => {
    if (!settings) return false;
    const selectedPreset = settings.model_presets.find(
      (preset) => !preset.is_default && preset.name === modelPresetEditingName,
    );
    if (!selectedPreset) return false;
    return (
      form.modelPreset !== selectedPreset.name ||
      form.model !== selectedPreset.model ||
      form.provider !== selectedPreset.provider ||
      form.maxTokens !== selectedPreset.max_tokens ||
      form.contextWindowTokens !== normalizeContextWindowTokens(selectedPreset.context_window_tokens) ||
      form.temperature !== selectedPreset.temperature ||
      form.reasoningEffort !== (selectedPreset.reasoning_effort ?? "")
    );
  }, [form, modelPresetEditingName, settings]);

  const imageGenerationDirty = useMemo(() => {
    if (!settings) return false;
    return (
      imageGenerationForm.enabled !== settings.image_generation.enabled ||
      imageGenerationForm.provider !== settings.image_generation.provider ||
      imageGenerationForm.model !== settings.image_generation.model ||
      imageGenerationForm.defaultAspectRatio !== settings.image_generation.default_aspect_ratio ||
      imageGenerationForm.defaultImageSize !== settings.image_generation.default_image_size ||
      imageGenerationForm.maxImagesPerTurn !== settings.image_generation.max_images_per_turn
    );
  }, [imageGenerationForm, settings]);

  const transcriptionDirty = useMemo(() => {
    if (!settings) return false;
    const transcription = settings.transcription ?? DEFAULT_TRANSCRIPTION_SETTINGS;
    return (
      transcriptionForm.enabled !== transcription.enabled ||
      transcriptionForm.provider !== transcription.provider ||
      transcriptionForm.model !== transcription.model ||
      transcriptionForm.language !== (transcription.language ?? "") ||
      transcriptionForm.maxDurationSec !== transcription.max_duration_sec ||
      transcriptionForm.maxUploadMb !== transcription.max_upload_mb
    );
  }, [settings, transcriptionForm]);

  const networkSafetyDirty = useMemo(() => {
    if (!settings) return false;
    const currentLocalServiceAccess =
      settings.advanced.webui_allow_local_service_access ?? settings.advanced.allow_local_preview_access ?? true;
    const currentDefaultAccess = visibleWebuiDefaultAccessMode(settings.advanced.webui_default_access_mode);
    return (
      networkSafetyForm.webuiAllowLocalServiceAccess !== currentLocalServiceAccess ||
      networkSafetyForm.webuiDefaultAccessMode !== currentDefaultAccess
    );
  }, [networkSafetyForm, settings]);

  const configuredModelProviderOptions = useMemo(
    () =>
      settings?.providers
        .filter((provider) => provider.configured && provider.model_selectable !== false)
        .map((provider) => ({ name: provider.name, label: provider.label })) ?? [],
    [settings],
  );

  const hasPendingRestart = useMemo(
    () =>
      !!settings?.requires_restart ||
      pendingRestartSections.runtime ||
      pendingRestartSections.browser ||
      pendingRestartSections.image,
    [pendingRestartSections, settings?.requires_restart],
  );

  const restartViaSettingsSurface = useCallback(async () => {
    const isNativeHost = (settings?.surface ?? settings?.runtime_surface) === "native";
    if (
      isNativeHost &&
      settings?.runtime_capabilities?.can_restart_engine &&
      onNativeEngineRestart
    ) {
      setHostEngineApplying(true);
      try {
        const nextToken = await onNativeEngineRestart();
        const payload = await fetchSettings(nextToken);
        applyPayload(payload);
        setPendingRestartSections(EMPTY_PENDING_RESTART_SECTIONS);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setHostEngineApplying(false);
      }
      return;
    }
    onRestart?.();
  }, [applyPayload, onNativeEngineRestart, onRestart, settings]);

  const maybeRestartHostEngine = useCallback(
    async (payload: RestartAwarePayload) => {
      const surface = payload.surface ?? payload.runtime_surface ?? settings?.surface ?? settings?.runtime_surface;
      const capabilities = payload.runtime_capabilities ?? settings?.runtime_capabilities;
      const isNativeHost = surface === "native";
      if (
        !payload.requires_restart ||
        !isNativeHost ||
        !capabilities?.can_restart_engine ||
        !onNativeEngineRestart
      ) {
        return;
      }
      setHostEngineApplying(true);
      try {
        const nextToken = await onNativeEngineRestart();
        const refreshed = await fetchSettings(nextToken);
        applyPayload(refreshed);
        setPendingRestartSections(EMPTY_PENDING_RESTART_SECTIONS);
        setError(null);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setHostEngineApplying(false);
      }
    },
    [applyPayload, onNativeEngineRestart, settings],
  );
  const systemActions = createSystemSettingsActions({
    state: systemState,
    featureCatalog,
    client,
    token,
    getToken,
    t,
    applyPayload,
    maybeRestartHostEngine,
    setPendingRestartSections,
    refreshAutomations,
  });
  const { installCapabilities } = systemActions;
  const modelActions = useModelSettingsActions({
    state: modelState,
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
  });
  const capabilityActions = useCapabilitySettingsActions({
    state: capabilityState,
    settings,
    client,
    t,
    applyPayload,
    maybeRestartHostEngine,
    setPendingRestartSections,
    setError,
    installCapabilities,
    imageGenerationDirty,
    transcriptionDirty,
    networkSafetyDirty,
  });
  const {
    beginModelPresetCreation,
    cancelModelPresetCreation,
    changeModelCallOrder,
    completeProviderOAuthResponse,
    createCustomProvider,
    handleDeleteModelConfiguration,
    handleMigrateModelConfigurations,
    handleToggleProvider,
    runProviderOAuth,
    saveModelSettings,
    saveProvider,
    toggleProviderKeyEditing,
    toggleProviderKeyVisibility,
  } = modelActions;
  const {
    handleWebSearchProviderChange,
    resetWebSearchDraft,
    saveImageGenerationSettings,
    saveNetworkSafetySettings,
    saveTranscriptionSettings,
    saveWebSearch,
  } = capabilityActions;
  const {
    handleApiServiceAction,
    handleAutomationAction,
    handleAutomationEdit,
    handleCliAppAction,
    handleImportMcpConfig,
    handleMcpOAuthCancel,
    handleMcpOAuthComplete,
    handleMcpOAuthConnect,
    handleMcpOAuthOpen,
    handleMcpPresetAction,
    handleMcpToolsChange,
    handleNanobotFeatureAction,
    handleSaveCustomMcp,
  } = systemActions;

  return {
    activeSection,
    apiService,
    apiServiceAction,
    apiServiceError,
    apiServiceLoading,
    appsKindFilter,
    appsQuery,
    automationAction,
    automationPendingDelete,
    automationPendingEdit,
    automations,
    automationsError,
    automationsFilter,
    automationsLoading,
    automationsQuery,
    automationsSort,
    beginModelPresetCreation,
    cancelModelPresetCreation,
    changeModelCallOrder,
    channelsQuery,
    cliApps,
    cliAppsAction,
    cliAppsError,
    cliAppsFocusName,
    cliAppsLoading,
    cliAppsMessage,
    closeProviderOAuthFlow,
    completeProviderOAuthResponse,
    createCustomProvider,
    customMcpForm,
    editingProviderKeys,
    error,
    expandedProvider,
    featureCatalog,
    form,
    handleApiServiceAction,
    handleAutomationAction,
    handleAutomationEdit,
    handleCliAppAction,
    handleDeleteModelConfiguration,
    handleImportMcpConfig,
    handleMcpOAuthCancel,
    handleMcpOAuthComplete,
    handleMcpOAuthConnect,
    handleMcpOAuthOpen,
    handleMcpPresetAction,
    handleMcpToolsChange,
    handleMigrateModelConfigurations,
    handleNanobotFeatureAction,
    handleSaveCustomMcp,
    handleToggleProvider,
    handleWebSearchProviderChange,
    hasPendingRestart,
    hostEngineApplying,
    imageGenerationDirty,
    imageGenerationForm,
    imageGenerationSaving,
    installCapabilities,
    loading,
    localPrefs,
    mcpConfigImport,
    mcpError,
    mcpFieldValues,
    mcpMessage,
    mcpOAuthCallbackError,
    mcpOAuthCallbackUrl,
    mcpOAuthCompleting,
    mcpOAuthFlow,
    mcpOAuthPopupBlocked,
    mcpPresetAction,
    mcpPresets,
    mcpPresetsLoading,
    modelCallOrder,
    modelCallOrderSaving,
    modelConfigurationSaving,
    modelDirty,
    modelMigrationSaving,
    modelPresetBeforeCreateRef,
    modelPresetCreating,
    modelPresetEditingName,
    modelPresetNameError,
    modelPresetPendingDelete,
    nanobotFeatureAction,
    nanobotFeatureConfirm,
    nanobotFeatures,
    nanobotFeaturesError,
    nanobotFeaturesLoading,
    networkSafetyDirty,
    networkSafetyForm,
    networkSafetySaving,
    pendingRestartSections,
    providerForms,
    providerOAuthCompleting,
    providerOAuthDialogError,
    providerOAuthFlow,
    providerOAuthResponse,
    providerSaving,
    remoteBrowserAccess,
    resetWebSearchDraft,
    restartViaSettingsSurface,
    runProviderOAuth,
    saveImageGenerationSettings,
    saveModelSettings,
    saveNetworkSafetySettings,
    saveProvider,
    saveTranscriptionSettings,
    saveWebSearch,
    saving,
    selectSection,
    setAppsKindFilter,
    setAppsQuery,
    setAutomationPendingDelete,
    setAutomationPendingEdit,
    setAutomationsFilter,
    setAutomationsQuery,
    setAutomationsSort,
    setChannelsQuery,
    setCliAppsError,
    setCliAppsMessage,
    setCustomMcpForm,
    setForm,
    setImageGenerationForm,
    setLocalPrefs,
    setMcpConfigImport,
    setMcpError,
    setMcpFieldValues,
    setMcpMessage,
    setMcpOAuthCallbackError,
    setMcpOAuthCallbackUrl,
    setModelPresetCreating,
    setModelPresetEditingName,
    setModelPresetNameError,
    setModelPresetPendingDelete,
    setNanobotFeatureConfirm,
    setNanobotFeatures,
    setNanobotFeaturesError,
    setNetworkSafetyForm,
    setProviderForms,
    setProviderOAuthDialogError,
    setProviderOAuthResponse,
    setTranscriptionForm,
    setWebSearchForm,
    setWebSearchKeyEditing,
    setWebSearchKeyVisible,
    settings,
    t,
    toggleProviderKeyEditing,
    toggleProviderKeyVisibility,
    token,
    transcriptionDirty,
    transcriptionForm,
    transcriptionSaving,
    visibleProviderKeys,
    webSearchForm,
    webSearchKeyEditing,
    webSearchKeyVisible,
    webSearchSaving,
  };
}

export type SettingsController = ReturnType<typeof useSettingsController>;
