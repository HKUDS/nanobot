import type { Dispatch, SetStateAction } from "react";
import type { TFunction } from "i18next";

import type {
  ApplySettingsPayload,
  MaybeRestartHostEngine,
  PendingRestartSections,
} from "@/components/settings/contracts";
import type { AutomationAction } from "@/components/settings/system/AutomationsSettings";
import { DEFAULT_CUSTOM_MCP_FORM } from "@/components/settings/system/AppsSettings";
import type { SystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import {
  cancelMcpOAuth,
  completeMcpOAuth,
  disableNanobotFeature,
  enableNanobotFeature,
  fetchNanobotFeatures,
  fetchSettings,
  fetchMcpOAuthStatus,
  fetchMcpPresets,
  importMcpConfig,
  runAutomationAction,
  runCliAppAction,
  runMcpPresetAction,
  saveCustomMcpServer,
  startMcpOAuth,
  startApiService,
  stopApiService,
  updateAutomation,
  updateMcpServerTools,
} from "@/lib/api";
import { notifyCliAppsChanged } from "@/lib/cli-app-events";
import { notifyMcpPresetsChanged } from "@/lib/mcp-preset-events";
import type { NanobotClient } from "@/lib/nanobot-client";
import type {
  AutomationUpdatePayload,
  McpOAuthFlowPayload,
  McpPresetsPayload,
  NanobotFeatureInfo,
  SessionAutomationJob,
} from "@/lib/types";

function isExpectedMcpOAuthPendingReloadFailure(
  payload: McpPresetsPayload,
  expectedName?: string,
): boolean {
  if (
    !expectedName
    || payload.last_action?.ok === false
    || payload.hot_reload?.ok !== false
  ) return false;

  const normalizedName = expectedName.trim().toLowerCase();
  const failed = payload.hot_reload.failed ?? [];
  if (
    !normalizedName
    || failed.length !== 1
    || failed[0].trim().toLowerCase() !== normalizedName
  ) return false;

  return payload.presets.some((preset) => (
    preset.name.trim().toLowerCase() === normalizedName
    && preset.auth === "oauth"
    && preset.status === "authorization_required"
  ));
}

interface SystemSettingsActionsOptions {
  state: SystemSettingsState;
  featureCatalog: NanobotFeatureInfo[];
  client: NanobotClient;
  token: string;
  getToken: () => string;
  t: TFunction;
  applyPayload: ApplySettingsPayload;
  maybeRestartHostEngine: MaybeRestartHostEngine;
  setPendingRestartSections: Dispatch<SetStateAction<PendingRestartSections>>;
  refreshAutomations: (showLoading?: boolean) => Promise<void>;
}

export function createSystemSettingsActions({
  state,
  featureCatalog,
  client,
  token,
  getToken,
  t,
  applyPayload,
  maybeRestartHostEngine,
  setPendingRestartSections,
  refreshAutomations,
}: SystemSettingsActionsOptions) {
  const {
    apiServiceAction,
    customMcpForm,
    mcpConfigImport,
    mcpOAuthCallbackUrl,
    mcpOAuthFlowRef,
    mcpOAuthNavigatedUrlRef,
    mcpOAuthPopupRef,
    nanobotFeatures,
    setApiService,
    setApiServiceAction,
    setApiServiceError,
    setAutomationAction,
    setAutomationPendingDelete,
    setAutomationPendingEdit,
    setAutomations,
    setAutomationsError,
    setCliApps,
    setCliAppsAction,
    setCliAppsError,
    setCliAppsFocusName,
    setCliAppsMessage,
    setCustomMcpForm,
    setMcpConfigImport,
    setMcpError,
    setMcpFieldValues,
    setMcpMessage,
    setMcpOAuthCallbackError,
    setMcpOAuthCallbackUrl,
    setMcpOAuthCompleting,
    setMcpOAuthFlow,
    setMcpOAuthPopupBlocked,
    setMcpPresetAction,
    setMcpPresets,
    setNanobotFeatureAction,
    setNanobotFeatureConfirm,
    setNanobotFeatures,
    setNanobotFeaturesError,
  } = state;

  const installCapabilities = async (names: string[]): Promise<boolean> => {
    const missing = names.filter(
      (name) => !featureCatalog.find((feature) => feature.name === name)?.installed,
    );
    if (!missing.length) return true;
    setNanobotFeatureAction(`enable:${names.join("+")}`);
    setNanobotFeaturesError(null);
    try {
      let latest = nanobotFeatures;
      for (const name of missing) {
        latest = await enableNanobotFeature(client, name);
        if (latest.requires_restart) {
          setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
        }
      }
      if (latest) setNanobotFeatures(latest);
      return true;
    } catch (err) {
      setNanobotFeaturesError((err as Error).message);
      return false;
    } finally {
      setNanobotFeatureAction(null);
    }
  };

  const handleApiServiceAction = async (
    action: "start" | "stop",
    values?: { host: string; port: number; timeout: number; apiKey?: string },
  ) => {
    if (apiServiceAction) return;
    setApiServiceAction(action);
    setApiServiceError(null);
    try {
      const payload = action === "start"
        ? await startApiService(client, values!)
        : await stopApiService(client);
      setApiService(payload);
      const refreshed = await fetchNanobotFeatures(token);
      setNanobotFeatures(refreshed);
      const nextSettings = await fetchSettings(token);
      applyPayload(nextSettings);
    } catch (err) {
      setApiServiceError((err as Error).message);
    } finally {
      setApiServiceAction(null);
    }
  };

  const handleCliAppAction = async (
    action: "install" | "update" | "uninstall" | "test",
    name: string,
  ) => {
    const key = `${action}:${name}`;
    setCliAppsAction(key);
    setCliAppsMessage(null);
    setCliAppsError(null);
    try {
      const payload = await runCliAppAction(client, action, name);
      setCliApps(payload);
      if (action !== "test") {
        notifyCliAppsChanged(payload);
      }
      setCliAppsMessage(payload.last_action?.message ?? null);
      setCliAppsFocusName(action === "uninstall" ? null : name);
    } catch (err) {
      setCliAppsError((err as Error).message);
    } finally {
      setCliAppsAction(null);
    }
  };

  const handleNanobotFeatureAction = async (
    action: "enable" | "disable",
    name: string,
    confirmed = false,
  ) => {
    const feature = featureCatalog.find((item) => item.name === name);
    if (action === "enable" && !confirmed && feature && !feature.installed && feature.install_supported) {
      setNanobotFeaturesError(null);
      setNanobotFeatureConfirm(feature);
      return;
    }
    const key = `${action}:${name}`;
    setNanobotFeatureAction(key);
    setNanobotFeatureConfirm(null);
    setNanobotFeaturesError(null);
    try {
      const payload = action === "enable"
        ? await enableNanobotFeature(client, name)
        : await disableNanobotFeature(client, name);
      setNanobotFeatures(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
    } catch (err) {
      setNanobotFeaturesError((err as Error).message);
    } finally {
      setNanobotFeatureAction(null);
    }
  };

  const handleAutomationAction = async (
    action: AutomationAction,
    job: SessionAutomationJob,
  ) => {
    const key = `${action}:${job.id}`;
    setAutomationAction(key);
    setAutomationsError(null);
    try {
      const payload = await runAutomationAction(client, action, job.id);
      setAutomations(payload);
      if (action === "delete") setAutomationPendingDelete(null);
      if (action === "run") {
        window.setTimeout(() => void refreshAutomations(false), 1200);
        window.setTimeout(() => void refreshAutomations(false), 4000);
      }
    } catch (err) {
      setAutomationsError((err as Error).message);
    } finally {
      setAutomationAction(null);
    }
  };

  const handleAutomationEdit = async (
    job: SessionAutomationJob,
    values: AutomationUpdatePayload,
  ) => {
    const key = `update:${job.id}`;
    setAutomationAction(key);
    setAutomationsError(null);
    try {
      const payload = await updateAutomation(client, job.id, values);
      setAutomations(payload);
      setAutomationPendingEdit(null);
    } catch (err) {
      setAutomationsError((err as Error).message);
    } finally {
      setAutomationAction(null);
    }
  };

  const closeMcpOAuthPopup = () => {
    const popup = mcpOAuthPopupRef.current;
    mcpOAuthPopupRef.current = null;
    mcpOAuthNavigatedUrlRef.current = null;
    if (!popup) return;
    try {
      if (!popup.closed) popup.close();
    } catch {
      // The authorization page may have navigated cross-origin before it closed itself.
    }
  };

  const openMcpOAuthPopup = (authorizationUrl?: string): Window | null => {
    let popup: Window | null = null;
    try {
      popup = window.open(
        authorizationUrl ?? "about:blank",
        "nanobot-mcp-oauth",
        "popup,width=560,height=720,resizable=yes,scrollbars=yes",
      );
      if (popup) {
        mcpOAuthPopupRef.current = popup;
        mcpOAuthNavigatedUrlRef.current = authorizationUrl ?? null;
        if (!authorizationUrl) {
          try {
            popup.document.title = t("settings.oauth.signingIn", { defaultValue: "Preparing sign-in…" });
            popup.document.body.textContent = t("settings.mcp.preparingSignIn", {
              defaultValue: "Preparing secure sign-in…",
            });
          } catch {
            // about:blank can become unavailable if the window is reused mid-navigation.
          }
        }
        try {
          popup.opener = null;
          popup.focus();
        } catch {
          // A cross-origin authorization page can restrict window access.
        }
      }
    } catch {
      // Browsers can reject popup creation before returning a window handle.
    }
    setMcpOAuthPopupBlocked(!popup);
    return popup;
  };

  const navigateMcpOAuthPopup = (flow: McpOAuthFlowPayload) => {
    const authorizationUrl = flow.authorization_url;
    if (!authorizationUrl) return;
    const popup = mcpOAuthPopupRef.current;
    // OAuth pages can use Cross-Origin-Opener-Policy, which severs the
    // WindowProxy and makes an open tab appear closed. Once navigation was
    // requested, do not mistake that browser isolation for a blocked popup.
    if (popup && mcpOAuthNavigatedUrlRef.current === authorizationUrl) return;
    try {
      if (popup && !popup.closed) {
        popup.location.replace(authorizationUrl);
        mcpOAuthNavigatedUrlRef.current = authorizationUrl;
        popup.focus();
        setMcpOAuthPopupBlocked(false);
        return;
      }
      if (popup) return;
    } catch {
      // Fall through to the explicit Continue in browser action.
    }
    setMcpOAuthPopupBlocked(true);
  };

  const finishMcpOAuthFlow = async (flow: McpOAuthFlowPayload) => {
    if (mcpOAuthFlowRef.current?.flow_id !== flow.flow_id) return;
    closeMcpOAuthPopup();
    mcpOAuthFlowRef.current = null;
    setMcpOAuthFlow(null);
    setMcpPresetAction(null);
    setMcpOAuthCallbackUrl("");
    setMcpOAuthCompleting(false);
    setMcpOAuthCallbackError(null);

    if (flow.status === "connected") {
      try {
        const payload = await fetchMcpPresets(getToken());
        setMcpPresets(payload);
        notifyMcpPresetsChanged(payload);
        setMcpMessage(null);
        setMcpError(null);
      } catch (err) {
        setMcpError((err as Error).message);
      }
      return;
    }

    if (flow.status === "authorized" && flow.hot_reload) {
      if (flow.hot_reload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      setMcpError(
        flow.hot_reload.message
        || t("settings.mcp.reloadFailed", {
          defaultValue: "Signed in, but nanobot could not connect the tools. Try restarting nanobot.",
        }),
      );
      return;
    }

    if (flow.status === "failed") {
      setMcpError(
        flow.error
        || t("settings.mcp.oauthFailed", {
          defaultValue: "Unable to connect. Try signing in again.",
        }),
      );
    }
  };

  const monitorMcpOAuthFlow = async (initial: McpOAuthFlowPayload) => {
    let current = initial;
    while (mcpOAuthFlowRef.current?.flow_id === current.flow_id) {
      navigateMcpOAuthPopup(current);
      const terminal =
        current.status === "connected"
        || current.status === "failed"
        || current.status === "cancelled"
        || (current.status === "authorized" && Boolean(current.hot_reload));
      if (terminal) {
        await finishMcpOAuthFlow(current);
        return;
      }

      await new Promise((resolve) => window.setTimeout(resolve, 800));
      if (mcpOAuthFlowRef.current?.flow_id !== current.flow_id) return;
      try {
        current = await fetchMcpOAuthStatus(getToken(), current.flow_id);
        if (mcpOAuthFlowRef.current?.flow_id !== current.flow_id) return;
        mcpOAuthFlowRef.current = current;
        setMcpOAuthFlow(current);
      } catch (err) {
        if (mcpOAuthFlowRef.current?.flow_id !== current.flow_id) return;
        closeMcpOAuthPopup();
        mcpOAuthFlowRef.current = null;
        setMcpOAuthFlow(null);
        setMcpPresetAction(null);
        setMcpOAuthCallbackUrl("");
        setMcpOAuthCompleting(false);
        setMcpOAuthCallbackError(null);
        setMcpError((err as Error).message);
        return;
      }
    }
  };

  const handleMcpOAuthConnect = async (name: string, reset = false) => {
    openMcpOAuthPopup();
    const key = `oauth:${name}`;
    setMcpPresetAction(key);
    setMcpMessage(null);
    setMcpError(null);
    setMcpOAuthCallbackUrl("");
    setMcpOAuthCompleting(false);
    setMcpOAuthCallbackError(null);
    try {
      const flow = await startMcpOAuth(client, name, reset);
      mcpOAuthFlowRef.current = flow;
      setMcpOAuthFlow(flow);
      navigateMcpOAuthPopup(flow);
      void monitorMcpOAuthFlow(flow);
    } catch (err) {
      closeMcpOAuthPopup();
      mcpOAuthFlowRef.current = null;
      setMcpOAuthFlow(null);
      setMcpPresetAction(null);
      setMcpOAuthCallbackUrl("");
      setMcpOAuthCompleting(false);
      setMcpOAuthCallbackError(null);
      setMcpError((err as Error).message);
    }
  };

  const handleMcpOAuthCancel = async () => {
    const flow = mcpOAuthFlowRef.current;
    if (!flow) return;
    mcpOAuthFlowRef.current = null;
    setMcpOAuthFlow(null);
    setMcpPresetAction(null);
    setMcpOAuthCallbackUrl("");
    setMcpOAuthCompleting(false);
    setMcpOAuthCallbackError(null);
    closeMcpOAuthPopup();
    try {
      await cancelMcpOAuth(client, flow.flow_id);
    } catch (err) {
      setMcpError((err as Error).message);
    }
  };

  const handleMcpOAuthOpen = () => {
    const authorizationUrl = mcpOAuthFlowRef.current?.authorization_url;
    if (!authorizationUrl) return;
    openMcpOAuthPopup(authorizationUrl);
  };

  const handleMcpOAuthComplete = async () => {
    const flow = mcpOAuthFlowRef.current;
    const callbackUrl = mcpOAuthCallbackUrl.trim();
    if (!flow || flow.completion_input !== "callback_url") return;
    if (!callbackUrl) {
      setMcpOAuthCallbackError(t("settings.oauth.pasteCallbackToContinue"));
      return;
    }
    setMcpOAuthCompleting(true);
    setMcpOAuthCallbackError(null);
    try {
      const next = await completeMcpOAuth(client, flow.flow_id, callbackUrl);
      if (mcpOAuthFlowRef.current?.flow_id !== flow.flow_id) return;
      mcpOAuthFlowRef.current = next;
      setMcpOAuthFlow(next);
    } catch (err) {
      if (mcpOAuthFlowRef.current?.flow_id !== flow.flow_id) return;
      setMcpOAuthCallbackError((err as Error).message);
    } finally {
      if (mcpOAuthFlowRef.current?.flow_id === flow.flow_id) {
        setMcpOAuthCompleting(false);
      }
    }
  };

  const applyMcpActionFeedback = (
    payload: McpPresetsPayload,
    announceSuccess = false,
    expectedOAuthPendingName?: string,
  ) => {
    const expectedOAuthPending = isExpectedMcpOAuthPendingReloadFailure(
      payload,
      expectedOAuthPendingName,
    );
    const actionError = payload.last_action?.ok === false
      ? payload.last_action.error || payload.last_action.message
      : payload.hot_reload?.ok === false && !expectedOAuthPending
        ? payload.hot_reload.message
        : null;
    setMcpError(actionError || null);
    setMcpMessage(
      actionError || !announceSuccess
        ? null
        : payload.last_action?.message ?? null,
    );
  };

  const handleMcpPresetAction = async (
    action: "enable" | "disable" | "remove" | "test" | "reconnect",
    name: string,
    values: Record<string, string> = {},
  ) => {
    const key = `${action}:${name}`;
    setMcpPresetAction(key);
    setMcpMessage(null);
    setMcpError(null);
    try {
      const payload = await runMcpPresetAction(client, action, name, values);
      setMcpPresets(payload);
      applyMcpActionFeedback(payload, action === "test");
      if (action !== "test") {
        notifyMcpPresetsChanged(payload);
      }
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await maybeRestartHostEngine(payload);
      if (action === "enable") {
        setMcpFieldValues((prev) => ({ ...prev, [name]: {} }));
      }
    } catch (err) {
      setMcpError((err as Error).message);
    } finally {
      setMcpPresetAction(null);
    }
  };

  const handleSaveCustomMcp = async () => {
    const name = customMcpForm.name.trim();
    const expectsOAuthAuthorization = (
      customMcpForm.transport !== "stdio" && customMcpForm.auth === "oauth"
    );
    const key = `custom:${name || "new"}`;
    setMcpPresetAction(key);
    setMcpMessage(null);
    setMcpError(null);
    try {
      const payload = await saveCustomMcpServer(client, {
        name,
        transport: customMcpForm.transport,
        auth:
          customMcpForm.transport !== "stdio" && customMcpForm.auth === "oauth"
            ? "oauth"
            : "",
        command: customMcpForm.command,
        args: customMcpForm.args,
        url: customMcpForm.url,
        env: customMcpForm.env,
        headers:
          customMcpForm.transport !== "stdio" && customMcpForm.auth === "headers"
            ? customMcpForm.headers
            : "",
        tool_timeout: customMcpForm.toolTimeout,
      });
      setMcpPresets(payload);
      applyMcpActionFeedback(
        payload,
        false,
        expectsOAuthAuthorization ? name : undefined,
      );
      notifyMcpPresetsChanged(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await maybeRestartHostEngine(payload);
      setCustomMcpForm((prev) => ({ ...DEFAULT_CUSTOM_MCP_FORM, transport: prev.transport }));
    } catch (err) {
      setMcpError((err as Error).message);
    } finally {
      setMcpPresetAction(null);
    }
  };

  const handleImportMcpConfig = async () => {
    setMcpPresetAction("import");
    setMcpMessage(null);
    setMcpError(null);
    try {
      const payload = await importMcpConfig(client, mcpConfigImport);
      setMcpPresets(payload);
      applyMcpActionFeedback(payload);
      notifyMcpPresetsChanged(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await maybeRestartHostEngine(payload);
      setMcpConfigImport("");
    } catch (err) {
      setMcpError((err as Error).message);
    } finally {
      setMcpPresetAction(null);
    }
  };

  const handleMcpToolsChange = async (name: string, enabledTools: string[]) => {
    setMcpPresetAction(`tools:${name}`);
    setMcpMessage(null);
    setMcpError(null);
    try {
      const payload = await updateMcpServerTools(client, name, enabledTools);
      setMcpPresets(payload);
      applyMcpActionFeedback(payload);
      notifyMcpPresetsChanged(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await maybeRestartHostEngine(payload);
    } catch (err) {
      setMcpError((err as Error).message);
    } finally {
      setMcpPresetAction(null);
    }
  };

  return {
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
    installCapabilities,
  };
}
