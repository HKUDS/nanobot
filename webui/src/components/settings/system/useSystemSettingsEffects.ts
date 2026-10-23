import { useEffect } from "react";

import type { SettingsSectionKey } from "@/components/settings/contracts";
import {
  CLI_APPS_REFRESH_MAX_RETRIES,
  CLI_APPS_REFRESH_RETRY_MS,
} from "@/components/settings/system/AppsSettings";
import type { SystemSettingsState } from "@/components/settings/system/useSystemSettingsState";
import { useStateRefresh } from "@/hooks/useStateRefresh";
import {
  fetchApiService,
  fetchAutomations,
  fetchCliApps,
  fetchMcpPresets,
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
    setCliApps,
    setCliAppsError,
    setCliAppsLoading,
    setMcpError,
    setMcpPresets,
    setMcpPresetsLoading,
    setNanobotFeatures,
    setNanobotFeaturesError,
    setNanobotFeaturesLoading,
  } = state;

  useEffect(() => {
    if (activeSection !== "apps") return;
    let cancelled = false;
    let retry: number | null = null;
    let retryCount = 0;
    const loadCliApps = (showLoading: boolean) => {
      if (showLoading) setCliAppsLoading(true);
      fetchCliApps(getToken())
        .then((payload) => {
          if (cancelled) return;
          if (payload.catalog_refresh_pending && retryCount < CLI_APPS_REFRESH_MAX_RETRIES) {
            retryCount += 1;
            retry = window.setTimeout(() => {
              retry = null;
              loadCliApps(false);
            }, CLI_APPS_REFRESH_RETRY_MS);
          }
          setCliApps(payload);
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
    loadCliApps(true);
    return () => {
      cancelled = true;
      if (retry !== null) window.clearTimeout(retry);
    };
  }, [activeSection, getToken]);

  useStateRefresh("channels",
    ["channels", "models", "browser", "image", "voice", "memory", "capabilities", "runtime"].includes(activeSection),
    async (signal, initial) => {
      if (initial) setNanobotFeaturesLoading(true);
      try {
        const payload = await fetchNanobotFeatures(getToken(), "", signal);
        if (!signal.aborted) {
          setNanobotFeatures(payload);
          setNanobotFeaturesError(null);
        }
      } catch (err) {
        if (!signal.aborted && (err as Error).message !== "HTTP 404") setNanobotFeaturesError((err as Error).message);
        throw err;
      } finally {
        if (!signal.aborted && initial) setNanobotFeaturesLoading(false);
      }
    }, activeSection);

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
      fetchMcpPresets(getToken())
        .then((payload) => {
          if (cancelled) return;
          setMcpPresets(payload);
          setMcpError(null);
          if (payload.presets.some((preset) => preset.runtime_status === "connecting")) {
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
    loadMcpPresets(true);
    return () => {
      cancelled = true;
      if (retry !== null) window.clearTimeout(retry);
    };
  }, [activeSection, getToken, pageVisible]);

  useStateRefresh("automations", activeSection === "automations", async (signal, initial) => {
    if (initial) setAutomationsLoading(true);
    try {
      const payload = await fetchAutomations(getToken(), "", signal);
      if (!signal.aborted) {
        setAutomations(payload);
        setAutomationsError(null);
      }
    } catch (err) {
      if (!signal.aborted) setAutomationsError((err as Error).message);
      throw err;
    } finally {
      if (!signal.aborted && initial) setAutomationsLoading(false);
    }
  });
}
