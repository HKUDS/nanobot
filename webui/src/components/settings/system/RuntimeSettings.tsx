import { useState } from "react";
import { Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AgentSettingsDraft } from "@/components/settings/models/ModelsSettings";
import {
  ReadOnlyRow,
  SettingsGroup,
  SettingsRow,
  SettingsSectionTitle,
  StatusPill,
} from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { getRuntimeHost, isNativeRuntime } from "@/lib/runtime";
import type { NanobotFeatureInfo, SettingsPayload } from "@/lib/types";

export function RuntimeSettings({
  form,
  settings,
  onRestart,
  isRestarting,
  requiresRestartPending,
  langfuseFeature,
  capabilitiesLoading,
  capabilityAction,
  capabilityError,
  onInstallCapability,
}: {
  form: AgentSettingsDraft;
  settings: SettingsPayload;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
  langfuseFeature?: NanobotFeatureInfo;
  capabilitiesLoading: boolean;
  capabilityAction: string | null;
  capabilityError: string | null;
  onInstallCapability: (name: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const runtimeSurface = settings.surface ?? settings.runtime_surface;
  const runtimeHost = getRuntimeHost(runtimeSurface, settings.runtime_capabilities);
  const openLogs = runtimeHost.openLogs;
  const exportDiagnostics = runtimeHost.exportDiagnostics;
  const isNativeHost = isNativeRuntime(runtimeSurface);
  const restartActionLabel = isNativeHost
    ? tx("app.system.restartEngine", "Restart engine")
    : t("app.system.restart");
  const restartingActionLabel = isNativeHost
    ? tx("app.system.restartingEngine", "Restarting engine...")
    : t("app.system.restarting");
  const [diagnosticsPath, setDiagnosticsPath] = useState<string | null>(null);
  const [hostActionMessage, setHostActionMessage] = useState<{
    target: "logs" | "diagnostics";
    message: string;
  } | null>(null);
  const [hostActionBusy, setHostActionBusy] =
    useState<"logs" | "diagnostics" | null>(null);
  const engineState = isRestarting
    ? tx("settings.values.restartingEngine", "Restarting")
    : settings.apply_state?.status === "pending"
      ? tx("settings.values.pending", "Pending")
      : tx("settings.values.ready", "Ready");
  const runHostAction = async (
    target: "logs" | "diagnostics",
    action: (() => Promise<string | void>) | undefined,
    successMessage: (result: string | void) => string,
    failureMessage: string,
  ) => {
    if (!action) {
      setHostActionMessage({
        target,
        message: tx(
          "settings.status.hostApiUnavailable",
          "These actions are only available in the desktop app.",
        ),
      });
      return;
    }
    setHostActionBusy(target);
    setHostActionMessage(null);
    try {
      const result = await action();
      setHostActionMessage({ target, message: successMessage(result) });
    } catch {
      setHostActionMessage({ target, message: failureMessage });
    } finally {
      setHostActionBusy(null);
    }
  };
  return (
    <div className="settings-stack">
      {isNativeHost ? (
        <section>
          <SettingsSectionTitle>{tx("settings.sections.nativeHost", "Native host")}</SettingsSectionTitle>
          <SettingsGroup>
            <ReadOnlyRow title={tx("settings.rows.engine", "Engine")} value={engineState} />
            {settings.runtime_capabilities?.can_open_logs ? (
              <SettingsRow
                title={tx("settings.rows.logs", "Logs")}
                description={
                  hostActionMessage?.target === "logs" ? hostActionMessage.message : undefined
                }
              >
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void runHostAction(
                      "logs",
                      openLogs,
                      () => tx("settings.status.logsOpened", "Opened logs folder."),
                      tx("settings.status.logsOpenFailed", "Could not open logs folder."),
                    )
                  }
                  disabled={hostActionBusy !== null}
                  className="rounded-full"
                >
                  {hostActionBusy === "logs"
                    ? tx("settings.actions.opening", "Opening...")
                    : tx("settings.actions.open", "Open")}
                </Button>
              </SettingsRow>
            ) : null}
            {settings.runtime_capabilities?.can_export_diagnostics ? (
              <SettingsRow
                title={tx("settings.rows.diagnostics", "Diagnostics")}
                description={
                  hostActionMessage?.target === "diagnostics"
                    ? hostActionMessage.message
                    : diagnosticsPath || undefined
                }
              >
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void runHostAction(
                      "diagnostics",
                      exportDiagnostics ? async () => {
                        const path = await exportDiagnostics();
                        setDiagnosticsPath(path);
                        return path;
                      } : undefined,
                      (path) =>
                        t("settings.status.diagnosticsExported", {
                          path: String(path ?? ""),
                          defaultValue: "Diagnostics exported to {{path}}.",
                        }),
                      tx("settings.status.diagnosticsExportFailed", "Could not export diagnostics."),
                    )
                  }
                  disabled={hostActionBusy !== null}
                  className="rounded-full"
                >
                  {hostActionBusy === "diagnostics"
                    ? tx("settings.actions.exporting", "Exporting...")
                    : tx("settings.actions.export", "Export")}
                </Button>
              </SettingsRow>
            ) : null}
          </SettingsGroup>
        </section>
      ) : null}

      <section>
        <SettingsSectionTitle>{tx("settings.observability.title", "Observability")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title="Langfuse"
            description={
              settings.observability?.configured
                ? undefined
                : tx(
                    "settings.observability.environment",
                    "Set LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY, then restart nanobot.",
                  )
            }
          >
            {capabilitiesLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
            ) : langfuseFeature?.installed ? (
              <StatusPill tone={settings.observability?.configured ? "success" : "neutral"}>
                {settings.observability?.configured
                  ? tx("settings.values.ready", "Ready")
                  : tx("settings.values.needsSetup", "Needs setup")}
              </StatusPill>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={capabilityAction === "enable:langfuse"}
                onClick={() => onInstallCapability("langfuse")}
                className="rounded-full"
              >
                {capabilityAction === "enable:langfuse" ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : null}
                {capabilityAction === "enable:langfuse"
                  ? tx("settings.capabilities.installing", "Installing required packages…")
                  : tx("settings.observability.enable", "Enable tracing support")}
              </Button>
            )}
          </SettingsRow>
        </SettingsGroup>
        {capabilityError ? <p className="mt-2 text-[12px] text-destructive">{capabilityError}</p> : null}
      </section>

      <section>
        <SettingsSectionTitle>{t("settings.sections.system")}</SettingsSectionTitle>
        <SettingsGroup>
          {!isNativeHost ? (
            <ReadOnlyRow
              title={tx("settings.rows.gateway", "Gateway")}
              value={`${settings.runtime.gateway_host}:${settings.runtime.gateway_port}`}
            />
          ) : null}
          <ReadOnlyRow title={t("settings.rows.configPath")} value={settings.runtime.config_path} />
          {!settings.runtime_config ? (
            <ReadOnlyRow title={tx("settings.rows.workspacePath", "Default workspace")} value={settings.runtime.workspace_path} />
          ) : null}
          {!settings.runtime_config ? (
            <ReadOnlyRow title={tx("settings.rows.timezone", "Timezone")} value={form.timezone} />
          ) : null}
          {onRestart ? (
            <SettingsRow
              title={t("settings.rows.restart")}
              description={
                requiresRestartPending
                  ? tx("settings.status.savedRestartApply", "Saved. Restart to apply changes.")
                  : undefined
              }
            >
              <Button
                size="sm"
                variant="outline"
                onClick={onRestart}
                disabled={isRestarting}
                className="rounded-full"
              >
                {isRestarting ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {isRestarting ? restartingActionLabel : restartActionLabel}
              </Button>
            </SettingsRow>
          ) : null}
        </SettingsGroup>
      </section>
    </div>
  );
}
