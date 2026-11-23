import { useEffect, useRef, useState, type ReactNode } from "react";
import { CircleAlert, Loader2, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ProviderPicker } from "@/components/settings/shared/ModelControls";
import { SettingsGroup, SettingsRow, SettingsSectionTitle, StatusPill } from "@/components/settings/shared/SettingsControls";
import { SettingsAdvancedOptions } from "@/components/settings/shared/SettingsFeature";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleButton } from "@/components/ui/toggle-button";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { checkSandboxSettings } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import { sandboxLauncherDisplay } from "@/lib/sandbox-display";
import type { SandboxCheck, SettingsPayload } from "@/lib/types";
import type { RuntimeConfigController } from "./RuntimeConfigSettings";
import type { SettingsFocusTarget } from "@/components/settings/contracts";
import { RUNTIME_CONFIG_FIELDS } from "./runtime-config-fields";

export function SandboxSettings({ settings, state, client, isRestarting, children, focusTarget }: {
  settings: SettingsPayload;
  state: RuntimeConfigController;
  client: NanobotClient;
  isRestarting: boolean;
  children: ReactNode;
  focusTarget?: SettingsFocusTarget;
}) {
  const { t } = useTranslation();
  const saved = settings.advanced.exec_sandbox_status!;
  const launcherName = sandboxLauncherDisplay(saved.supported_backend)?.name ?? t("settings.sandbox.launcher");
  const tx = (key: string) => t(`settings.sandbox.${key}`, { launcher: launcherName });
  const [result, setResult] = useState<SandboxCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const generation = useRef(0);
  const section = useRef<HTMLElement>(null);
  const launcherInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!focusTarget) return;
    section.current?.scrollIntoView({ block: "start" });
    const target = focusTarget === "sandbox-launcher" && launcherInput.current && !launcherInput.current.disabled
      ? launcherInput.current : section.current;
    target?.focus({ preventScroll: true });
  }, [focusTarget]);
  useEffect(() => {
    generation.current += 1;
    setResult(null);
    setChecking(false);
    setCheckError(false);
    return () => { generation.current += 1; };
  }, [client, saved.revision, saved.state, saved.reason, saved.launcher]);
  const field = (path: string) => RUNTIME_CONFIG_FIELDS.find((item) => item.path === path)!;
  const enabledField = field("tools.exec.enable");
  const sandboxField = field("tools.exec.sandbox");
  const launcherField = field("tools.exec.sandbox_launcher");
  const enabled = state.value(enabledField.path) !== false;
  const backend = String(state.value(sandboxField.path));
  const dirty = RUNTIME_CONFIG_FIELDS.some((item) => (item.group === "shell" || item.path === enabledField.path) && state.dirty(item));
  const busy = state.saving !== null || isRestarting || checking;
  const status = dirty ? "unchecked" : checking ? "checking" : result?.revision === saved.revision ? result.state : saved.state;
  const error = state.errors.shell;
  const reason = dirty ? "" : result?.revision === saved.revision ? result.reason : saved.reason;
  const launcher = result?.revision === saved.revision ? result.launcher : saved.launcher;
  const options = [{ name: "none", label: tx("off") }];
  if (saved.supported_backend) options.unshift({ name: saved.supported_backend, label: saved.supported_backend === "seatbelt" ? "Seatbelt" : "bwrap" });
  if (backend && !options.some((item) => item.name === backend)) options.unshift({ name: backend, label: backend });

  const check = async () => {
    const id = ++generation.current;
    setChecking(true);
    setCheckError(false);
    try {
      const response = await checkSandboxSettings(client);
      if (id !== generation.current) return;
      if (response.sandbox.revision !== saved.revision) { setCheckError(true); return; }
      setResult(response.sandbox);
    } catch {
      if (id === generation.current) setCheckError(true);
    } finally {
      if (id === generation.current) setChecking(false);
    }
  };
  return <section ref={section} tabIndex={-1} className="scroll-mt-6" aria-label={tx("title")}>
    <SettingsSectionTitle>{tx("title")}</SettingsSectionTitle>
    <SettingsGroup>
      <SettingsRow title={t("settings.runtimeConfig.fields.tools_exec_enable.label")}>
        <ToggleButton checked={enabled} disabled={busy} label={t("settings.runtimeConfig.fields.tools_exec_enable.label")}
          onChange={(value) => state.commit(enabledField, value)} />
      </SettingsRow>
      <SettingsRow title={tx("method")}>
        <ProviderPicker providers={options} value={backend || "none"} emptyLabel={tx("off")}
          triggerProps={{ id: "runtime-tools.exec.sandbox", "aria-label": t("settings.runtimeConfig.fields.tools_exec_sandbox.label"), disabled: busy || !enabled }}
          onChange={(value) => {
            if (value === "none" && backend) setConfirmDisable(true);
            else state.commit(sandboxField, value === "none" ? "" : value);
          }} />
      </SettingsRow>
      <SettingsRow title={tx("status")}>
        <StatusPill tone={status === "passed" ? "success" : status === "unavailable" || status === "unsupported" ? "warning" : "neutral"}>{tx(`states.${status}`)}</StatusPill>
      </SettingsRow>
      <div className="settings-list-inset pb-4 pt-1" aria-live="polite">
        <div className="flex items-start gap-2 text-ui leading-6 text-muted-foreground">
          {checking ? <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
            : status === "passed" ? <ShieldCheck className="mt-1 h-4 w-4 shrink-0" aria-hidden /> : <CircleAlert className="mt-1 h-4 w-4 shrink-0" aria-hidden />}
          <p>{!saved.supported_backend && enabled ? tx("help.unsupported") : reason ? t(`settings.sandbox.reasons.${reason}`, { launcher: launcherName, defaultValue: tx("reasons.unknown") }) : tx(`help.${dirty ? "unsaved" : status}`)}</p>
        </div>
        {launcher ? <p className="mt-2 break-all font-mono text-caption text-muted-foreground">{launcher}</p> : null}
        <p className="mt-2 text-caption leading-5 text-muted-foreground">{tx("scope")}</p>
        {saved.supported_backend && enabled && backend ? <Button variant="outline" size="sm" className="mt-3 rounded-full" disabled={busy || dirty} onClick={() => void check()}>{tx(checking ? "checking" : "check")}</Button> : null}
        {checkError ? <p role="alert" className="mt-2 text-caption text-destructive">{tx("checkError")}</p> : null}
        {error ? <p id="sandbox-settings-error" role="alert" className="mt-2 text-caption text-destructive">{error}</p> : null}
      </div>
      <SettingsAdvancedOptions initialOpen={focusTarget === "sandbox-launcher"}>
        {saved.supported_backend ? <div className="settings-list-inset pb-4 pt-2">
          <label htmlFor="runtime-tools.exec.sandbox_launcher" className="text-control-label">{tx("path")}</label>
          <p id="sandbox-launcher-help" className="mb-3 mt-1 text-caption leading-5 text-muted-foreground">{tx("pathHelp")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Input ref={launcherInput} id="runtime-tools.exec.sandbox_launcher" className="min-w-0 flex-1 basis-56 text-ui" value={String(state.value(launcherField.path))}
              aria-invalid={state.invalidField === launcherField.path || undefined}
              aria-describedby={state.invalidField === launcherField.path ? "sandbox-launcher-help sandbox-settings-error" : "sandbox-launcher-help"}
              placeholder={tx("automatic")} disabled={busy} onChange={(event) => state.change(launcherField, event.target.value)} />
            <Button variant="outline" size="sm" disabled={busy || !state.dirty(launcherField)} onClick={() => void state.save("shell")}>{t("settings.actions.save")}</Button>
          </div>
        </div> : null}
        {children}
      </SettingsAdvancedOptions>
    </SettingsGroup>
    <AlertDialog open={confirmDisable} onOpenChange={setConfirmDisable}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{tx("disableTitle")}</AlertDialogTitle>
        <AlertDialogDescription>{tx("disableHelp")}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>{tx("keep")}</AlertDialogCancel><AlertDialogAction onClick={() => state.commit(sandboxField, "")}>{tx("disable")}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>;
}
