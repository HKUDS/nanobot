import { useCallback, useEffect } from "react";

import type { SettingsSectionKey } from "@/components/settings/contracts";
import {
  CLI_APPS_REFRESH_MAX_RETRIES,
  CLI_APPS_REFRESH_RETRY_MS,
} from "@/components/settings/system/AppsSettings";
import type { SystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import {
  fetchApiService,
  fetchAutomations,
  fetchNanobotFeatures,
} from "@/lib/api";

interface SystemSettingsEffectsOptions {
  state: SystemSettingsState;
  activeSection: SettingsSectionKey;
  getToken: () => string;
  pageVisible: boolean;
}

const MCP_RUNTIME_STATUS_REFRESH_MS = 1_000;

export function useSystemSettingsEffects({
  state,
  activeSection,
  getToken,
  pageVisible,
}: SystemSettingsEffectsOptions) {
  const {
    setApiService,
    setApiServiceError,
    setApiServiceLoading,
    setAutomations,
    setAutomationsError,
    setAutomationsLoading,
    toolsCatalog,
    toolsCatalogInvalidation,
    setCliAppsError,
    setCliAppsLoading,
    setMcpError,
    setMcpPresetsLoading,
    setNanobotFeatures,
    setNanobotFeaturesError,
    setNanobotFeaturesLoading,
  } = state;

  useEffect(() => {
    setCliAppsError(null);
    setMcpError(null);
  }, [toolsCatalog]);

  const cliPending = Boolean(state.cliApps?.catalog_refresh_pending);
  const mcpConnecting = Boolean(state.mcpPresets?.presets.some(preset => preset.runtime_status === "connecting"));

  useEffect(() => {
    if (activeSection !== "apps") return;
    let cancelled = false;
    let retry: number | null = null;
    let retryCount = 0;
    const loadCliApps = (showLoading: boolean) => {
      if (showLoading) setCliAppsLoading(true);
      toolsCatalog.loadCliApps()
        .then(() => {
          if (cancelled) return;
          if (toolsCatalog.getSnapshot().cliApps?.catalog_refresh_pending && retryCount < CLI_APPS_REFRESH_MAX_RETRIES) {
            retryCount += 1;
            retry = window.setTimeout(() => {
              retry = null;
              loadCliApps(false);
            }, CLI_APPS_REFRESH_RETRY_MS);
          }
          setCliAppsError(null);
          setCliAppsLoading(false);
        })
        .catch((err) => {
          if (!cancelled) {
            setCliAppsError((err as Error).message);
            setCliAppsLoading(false);
          }
        });
    };
    const cached = toolsCatalog.getSnapshot().cliApps;
    setCliAppsLoading(!cached);
    if (!toolsCatalog.cliFresh()) loadCliApps(!cached);
    else if (cliPending) retry = window.setTimeout(() => loadCliApps(false), CLI_APPS_REFRESH_RETRY_MS);
    return () => {
      cancelled = true;
      if (retry !== null) window.clearTimeout(retry);
    };
  }, [activeSection, toolsCatalog, toolsCatalogInvalidation, cliPending]);

  useEffect(() => {
    if (
      !pageVisible
      || !["channels", "models", "browser", "image", "voice", "memory", "capabilities", "runtime"].includes(activeSection)
    ) {
      return;
    }
    let cancelled = false;
    let refreshing = false;
    const refresh = async (showLoading = false): Promise<void> => {
      if (refreshing) return;
      refreshing = true;
      if (showLoading) setNanobotFeaturesLoading(true);
      try {
        const payload = await fetchNanobotFeatures(getToken());
        if (!cancelled) {
          setNanobotFeatures(payload);
          setNanobotFeaturesError(null);
        }
      } catch (err) {
        const message = (err as Error).message;
        if (!cancelled && message !== "HTTP 404") setNanobotFeaturesError(message);
      } finally {
        refreshing = false;
        if (!cancelled && showLoading) setNanobotFeaturesLoading(false);
      }
    };
    void refresh(true);
    const interval = activeSection === "channels"
      ? window.setInterval(() => void refresh(false), 5000)
      : null;
    const refreshOnFocus = () => {
      if (activeSection === "channels" && document.visibilityState !== "hidden") {
        void refresh(false);
      }
    };
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnFocus);
    return () => {
      cancelled = true;
      if (interval !== null) window.clearInterval(interval);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnFocus);
    };
  }, [activeSection, getToken, pageVisible]);

  useEffect(() => {
    if (activeSection !== "runtime") return;
    let cancelled = false;
    setApiServiceLoading(true);
    fetchApiService(getToken())
      .then((payload) => {
        if (!cancelled) {
          setApiService(payload);
          setApiServiceError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setApiServiceError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setApiServiceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeSection, getToken]);

  useEffect(() => {
    if (activeSection !== "apps" || !pageVisible) return;
    let cancelled = false;
    let retry: number | null = null;
    const loadMcpPresets = (showLoading: boolean) => {
      if (showLoading) setMcpPresetsLoading(true);
      toolsCatalog.loadMcpPresets()
        .then(() => {
          if (cancelled) return;
          setMcpError(null);
          if (toolsCatalog.getSnapshot().mcpPresets?.presets.some((preset) => preset.runtime_status === "connecting")) {
            retry = window.setTimeout(() => {
              retry = null;
              loadMcpPresets(false);
            }, MCP_RUNTIME_STATUS_REFRESH_MS);
          }
        })
        .catch((err) => {
          if (!cancelled) setMcpError((err as Error).message);
        })
        .finally(() => {
          if (!cancelled && showLoading) setMcpPresetsLoading(false);
        });
    };
    const cached = toolsCatalog.getSnapshot().mcpPresets;
    setMcpPresetsLoading(!cached);
    if (!toolsCatalog.mcpFresh()) loadMcpPresets(!cached);
    else if (mcpConnecting) retry = window.setTimeout(() => loadMcpPresets(false), MCP_RUNTIME_STATUS_REFRESH_MS);
    return () => {
      cancelled = true;
      if (retry !== null) window.clearTimeout(retry);
    };
  }, [activeSection, toolsCatalog, toolsCatalogInvalidation, pageVisible, mcpConnecting]);

  const refreshAutomations = useCallback(
    async (showLoading = false) => {
      if (showLoading) setAutomationsLoading(true);
      try {
        const payload = await fetchAutomations(getToken());
        setAutomations(payload);
        setAutomationsError(null);
      } catch (err) {
        setAutomationsError((err as Error).message);
      } finally {
        if (showLoading) setAutomationsLoading(false);
      }
    },
    [getToken],
  );

  useEffect(() => {
    if (activeSection !== "automations" || !pageVisible) return;
    let cancelled = false;
    let refreshing = false;
    const refresh = async (showLoading = false) => {
      if (cancelled || refreshing) return;
      refreshing = true;
      if (showLoading) setAutomationsLoading(true);
      try {
        const payload = await fetchAutomations(getToken());
        if (cancelled) return;
        setAutomations(payload);
        setAutomationsError(null);
      } catch (err) {
        if (!cancelled) setAutomationsError((err as Error).message);
      } finally {
        refreshing = false;
        if (!cancelled && showLoading) setAutomationsLoading(false);
      }
    };
    void refresh(true);
    const interval = window.setInterval(() => void refresh(false), 5000);
    const refreshOnFocus = () => void refresh(false);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [activeSection, getToken, pageVisible]);

  return { refreshAutomations };
}
