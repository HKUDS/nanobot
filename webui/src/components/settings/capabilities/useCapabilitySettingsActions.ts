import { useCallback, useRef, type Dispatch, type SetStateAction } from "react";
import type { TFunction } from "i18next";

import {
  webSearchProviderAcceptsApiKey,
  webSearchDraftState,
} from "@/components/settings/capabilities/WebSettings";
import type { CapabilitySettingsState } from "@/components/settings/capabilities/useCapabilitySettingsState";
import type {
  ApplySettingsPayload,
  MaybeRestartHostEngine,
  PendingRestartSections,
} from "@/components/settings/contracts";
import {
  updateImageGenerationSettings,
  updateNetworkSafetySettings,
  updateTranscriptionSettings,
  updateWebSearchSettings,
} from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ImageGenerationSettingsUpdate, SettingsPayload, WebSearchSettingsUpdate } from "@/lib/types";
import { imageGenerationFormFromPayload } from "@/components/settings/capabilities/ImageGenerationSettings";
import { transcriptionFormFromPayload } from "@/components/settings/capabilities/TranscriptionSettings";
import { networkSafetyFormFromPayload } from "@/components/settings/capabilities/SecuritySettings";

interface CapabilitySettingsActionsOptions {
  state: CapabilitySettingsState;
  settings: SettingsPayload | null;
  client: NanobotClient;
  t: TFunction;
  applyPayload: ApplySettingsPayload;
  maybeRestartHostEngine: MaybeRestartHostEngine;
  setPendingRestartSections: Dispatch<SetStateAction<PendingRestartSections>>;
  installCapabilities: (names: string[]) => Promise<boolean>;
}

export function useCapabilitySettingsActions({
  state,
  settings,
  client,
  t,
  applyPayload,
  maybeRestartHostEngine,
  setPendingRestartSections,
  installCapabilities,
}: CapabilitySettingsActionsOptions) {
  const {
    imageGenerationForm,
    networkSafetyForm,
    setImageGenerationSaving,
    setNetworkSafetySaving,
    setTranscriptionSaving,
    setWebSearchForm,
    setWebSearchKeyEditing,
    setWebSearchKeyVisible,
    setWebSearchSaving,
    transcriptionForm,
    webSearchForm,
    webSearchKeyEditing,
  } = state;
  const latestWebSearchForm = useRef(webSearchForm);
  latestWebSearchForm.current = webSearchForm;
  const setError = (section: "image" | "voice" | "web" | "safety", message?: string) =>
    state.setCapabilityErrors((prev) => ({ ...prev, [section]: message }));

  const persistImageSettings = async (values: ImageGenerationSettingsUpdate) => {
    setError("image");
    setImageGenerationSaving(true);
    try {
      const payload = await updateImageGenerationSettings(client, values);
      applyPayload(payload, { preserveAgentForm: true, preserveCapabilityForms: true });
      state.setImageGenerationForm((current) => current === imageGenerationForm ? imageGenerationFormFromPayload(payload) : current);
      if (!payload.restart_required_sections && payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, image: true }));
      }
      await maybeRestartHostEngine(payload);
      setError("image");
    } finally {
      setImageGenerationSaving(false);
    }
  };

  const saveImageRequestSettings = (values: Pick<ImageGenerationSettingsUpdate, "extraHeaders" | "extraBody">) =>
    persistImageSettings({ ...imageGenerationForm, ...values });

  const saveImageGenerationSettings = async () => {
    if (!settings || !Number.isFinite(imageGenerationForm.maxImagesPerTurn)) return false;
    if (imageGenerationForm.enabled && !settings.image_generation.providers.find(
      (provider) => provider.name === imageGenerationForm.provider,
    )?.configured) return false;
    try {
      await persistImageSettings(imageGenerationForm);
      return true;
    } catch (err) {
      const message = (err as Error).message;
      setError("image", message === "image generation provider is not configured"
        ? t("settings.image.missingCredential") : message);
      return false;
    }
  };

  const saveTranscriptionSettings = async () => {
    if (!settings || !Number.isFinite(transcriptionForm.maxDurationSec) || !Number.isFinite(transcriptionForm.maxUploadMb)) return false;
    setError("voice");
    setTranscriptionSaving(true);
    try {
      const payload = await updateTranscriptionSettings(client, transcriptionForm);
      applyPayload(payload, { preserveAgentForm: true, preserveCapabilityForms: true });
      state.setTranscriptionForm((current) => current === transcriptionForm ? transcriptionFormFromPayload(payload) : current);
      if (!payload.restart_required_sections && payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, browser: true }));
      }
      await maybeRestartHostEngine(payload);
      setError("voice");
      return true;
    } catch (err) {
      setError("voice", (err as Error).message);
      return false;
    } finally {
      setTranscriptionSaving(false);
    }
  };

  const saveNetworkSafetySettings = async () => {
    if (!settings) return false;
    setError("safety");
    setNetworkSafetySaving(true);
    try {
      const payload = await updateNetworkSafetySettings(client, networkSafetyForm);
      applyPayload(payload, { preserveAgentForm: true, preserveCapabilityForms: true });
      state.setNetworkSafetyForm((current) => current === networkSafetyForm ? networkSafetyFormFromPayload(payload) : current);
      if (!payload.restart_required_sections && payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await maybeRestartHostEngine(payload);
      setError("safety");
      return true;
    } catch (err) {
      setError("safety", (err as Error).message);
      return false;
    } finally {
      setNetworkSafetySaving(false);
    }
  };

  const saveWebSearch = async () => {
    if (!settings || !Number.isFinite(webSearchForm.maxResults ?? settings.web_search.max_results) ||
      !Number.isFinite(webSearchForm.timeout ?? settings.web_search.timeout)) return false;
    const provider = settings.web_search.providers.find((item) => item.name === webSearchForm.provider);
    if (!provider) return false;
    const apiKey = webSearchForm.apiKey?.trim() ?? "";
    const baseUrl = webSearchForm.baseUrl?.trim() ?? "";
    if (webSearchDraftState(settings, webSearchForm).missingCredential) return false;

    setError("web");
    setWebSearchSaving(true);
    try {
      if (provider.name === "olostep" && !(await installCapabilities(["olostep"]))) return false;
      const webFetchRestartRequired =
        (webSearchForm.useJinaReader ?? settings.web.fetch.use_jina_reader) !==
        settings.web.fetch.use_jina_reader;
      const update: WebSearchSettingsUpdate = {
        provider: webSearchForm.provider,
        maxResults: webSearchForm.maxResults,
        timeout: webSearchForm.timeout,
        useJinaReader: webSearchForm.useJinaReader,
      };
      if (
        webSearchProviderAcceptsApiKey(provider) &&
        (apiKey || (provider.credential === "optional_api_key" && webSearchKeyEditing))
      ) {
        update.apiKey = apiKey;
      }
      if (provider.credential === "base_url") update.baseUrl = baseUrl;
      const payload = await updateWebSearchSettings(client, update);
      applyPayload(payload, { preserveAgentForm: true, preserveCapabilityForms: true });
      if (!payload.restart_required_sections && (payload.requires_restart || webFetchRestartRequired)) {
        setPendingRestartSections((prev) => ({ ...prev, browser: true }));
      }
      await maybeRestartHostEngine(payload);
      setWebSearchForm((prev) => prev !== webSearchForm ? prev : ({
        provider: payload.web_search.provider,
        apiKey: "",
        baseUrl: payload.web_search.base_url ?? prev.baseUrl ?? "",
        maxResults: payload.web_search.max_results,
        timeout: payload.web_search.timeout,
        useJinaReader: payload.web.fetch.use_jina_reader,
      }));
      if (latestWebSearchForm.current === webSearchForm) {
        setWebSearchKeyVisible(false);
        setWebSearchKeyEditing(false);
      }
      setError("web");
      return true;
    } catch (err) {
      setError("web", (err as Error).message);
      return false;
    } finally {
      setWebSearchSaving(false);
    }
  };

  const resetWebSearchDraft = useCallback(() => {
    if (!settings) return;
    setWebSearchForm({
      provider: settings.web_search.provider,
      apiKey: "",
      baseUrl: settings.web_search.base_url ?? "",
      maxResults: settings.web_search.max_results,
      timeout: settings.web_search.timeout,
      useJinaReader: settings.web.fetch.use_jina_reader,
    });
    setWebSearchKeyVisible(false);
    setWebSearchKeyEditing(false);
  }, [settings]);

  const handleWebSearchProviderChange = useCallback((provider: string) => {
    if (!settings) return;
    setWebSearchForm((prev) => ({
      provider,
      apiKey: "",
      baseUrl: provider === settings.web_search.provider ? settings.web_search.base_url ?? "" : "",
      maxResults: prev.maxResults ?? settings.web_search.max_results,
      timeout: prev.timeout ?? settings.web_search.timeout,
      useJinaReader: prev.useJinaReader ?? settings.web.fetch.use_jina_reader,
    }));
    setWebSearchKeyVisible(false);
    setWebSearchKeyEditing(false);
  }, [settings]);

  return {
    handleWebSearchProviderChange,
    resetWebSearchDraft,
    saveImageGenerationSettings,
    saveImageRequestSettings,
    saveNetworkSafetySettings,
    saveTranscriptionSettings,
    saveWebSearch,
  };
}
