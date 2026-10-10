import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, Download, ExternalLink, Eye, Info, Loader2, Monitor, MousePointer2, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import computerUseIcon from "@/assets/apps/computer-use.webp";
import cuaBlackLogo from "@/assets/apps/cua-black.svg";
import cuaWhiteLogo from "@/assets/apps/cua-white.svg";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Disclosure, DisclosureContent } from "@/components/ui/disclosure";
import { cn } from "@/lib/utils";
import type { CuaDriverCheck, CuaDriverSetup, McpPresetAction, McpPresetInfo } from "@/lib/types";
import type { CuaCheckFeedback } from "@/components/settings/system/useSystemSettingsState";

export const CUA_CAPABILITY = "webui.cua-driver.v1";
export const CUA_SETUP_CAPABILITY = "webui.cua-driver-guided-setup.v1";
export const CUA_PERMISSIONS_CAPABILITY = "webui.cua-driver-permission-request.v1";
export const CUA_RECONNECT_CAPABILITY = "webui.cua-driver-reconnect.v1";
export const CUA_UNINSTALL_CAPABILITY = "webui.cua-driver-uninstall.v1";
export const CUA_UNINSTALL_RESET_CAPABILITY = "webui.computer-use-uninstall-reset.v1";
export const CUA_NATIVE_CAPABILITY = "webui.computer-use-native.v1";

/** nanobot's capability icon; the upstream driver keeps its own attribution. */
export function ComputerUseIcon() {
  return <img src={computerUseIcon} alt="" aria-hidden draggable={false} width={40} height={40} className="h-full w-full rounded-control object-cover" />;
}

// An optional feature is authorized by its named capability and a recognized
// shape, not by a matching package version or an optimistic type assertion.
export function cuaDriverSetup(value: unknown, capabilities: unknown): CuaDriverSetup | null {
  if (!Array.isArray(capabilities) || !capabilities.includes(CUA_CAPABILITY)
    || !value || typeof value !== "object") return null;
  const setup = value as Record<string, unknown>;
  if (setup.permission_app !== undefined && setup.permission_app !== "CuaDriver"
    && !(setup.permission_app === "nanobot Computer Use" && capabilities.includes(CUA_NATIVE_CAPABILITY))) return null;
  if (setup.schema !== 1 || typeof setup.version !== "string" || typeof setup.platform !== "string"
    || typeof setup.machine !== "string" || typeof setup.supported !== "boolean"
    || typeof setup.installed !== "boolean" || typeof setup.managed !== "boolean"
    || !["observe", "control", "custom", "off"].includes(String(setup.mode))) return null;
  return setup as unknown as CuaDriverSetup;
}

/** Shared presentation of gateway facts; enabling access is not a connection check. */
export function cuaDriverStatus(preset: McpPresetInfo, setup: CuaDriverSetup | null, check?: CuaDriverCheck, error?: string | null) {
  if (!setup) return "unconfirmed";
  if (!setup.supported) return "unsupported";
  if (!setup.managed) return "manual";
  if (!setup.installed) return "notInstalled";
  if (!preset.configured || setup.mode === "off") return "accessOff";
  if (check?.sharing_paused) return "sharingPaused";
  const mac = setup.platform === "Darwin";
  // First-run grants can prevent the driver from connecting. Finish that
  // prerequisite before presenting reconnect as the next step.
  if (mac && check && (check.accessibility !== true || check.screen_recording !== true)) return "permissionPending";
  if (error || check?.connected === false) return "connectionIssue";
  if (preset.runtime_status === "failed") return "connectionIssue";
  if (check?.connected === true && preset.runtime_status === "connected") return "ready";
  return "enabled";
}

function CuaDriverFeatures() {
  const { t } = useTranslation();
  return <ul className="space-y-5 rounded-panel bg-muted/35 p-4 sm:p-5">
      {[
        { icon: Eye, title: "seeTitle", description: "seeDescription" },
        { icon: MousePointer2, title: "actTitle", description: "actDescription" },
        { icon: ShieldCheck, title: "chooseTitle", description: "chooseDescription" },
      ].map(({ icon: Icon, title, description }) => <li key={title} className="flex items-start gap-3">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0">
          <h3 className="text-[13px] font-medium leading-5">{t(`cuaDriver.${title}`)}</h3>
          <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">{t(`cuaDriver.${description}`)}</p>
        </div>
      </li>)}
    </ul>;
}

export function CuaDriverOverview({ docsUrl, setup }: { docsUrl: string; setup: CuaDriverSetup | null }) {
  const { t } = useTranslation();
  const native = setup?.permission_app === "nanobot Computer Use";
  return <div>
    <section>
      <div className="flex items-center gap-2.5">
        <span className="h-6 w-6 shrink-0" aria-hidden>
          <img src={cuaBlackLogo} alt="" className="h-full w-full object-contain dark:hidden" />
          <img src={cuaWhiteLogo} alt="" className="hidden h-full w-full object-contain dark:block" />
        </span>
        <div className="min-w-0">
          <h3 className="text-xs font-medium">{native ? "Computer Use" : "Cua Driver"}{setup && <span className="ml-2 font-normal text-muted-foreground">{setup.version}</span>}</h3>
          <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{t("cuaDriver.attribution")}</p>
        </div>
      </div>
      <div className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground">
        <p>{t("cuaDriver.gatewayHint")}</p>
        <p>{t(native ? "cuaDriver.nativeFeedbackScoped" : "cuaDriver.nativeFeedback")}</p>
        <p>{t("cuaDriver.scopeHint")} {t("cuaDriver.allowHint")}</p>
      </div>
      <Disclosure className="mt-3 border-t border-border/45 pt-1 text-xs text-muted-foreground"
        summaryClassName="touch-target flex items-center gap-1.5 rounded-compact focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        contentClassName="pb-2 leading-5"
        summary={<>{t("cuaDriver.installDetails")}<ChevronDown className="h-3 w-3 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" aria-hidden /></>}>
        <p>{t(native ? "cuaDriver.nativeInstallHint" : "cuaDriver.installHint")}</p>
      </Disclosure>
      {docsUrl && <a href={native ? "https://github.com/trycua/cua/tree/d27f6a89d8aeef0f56363ee9bb60bbc565912b1e/libs/cua-driver" : docsUrl} target="_blank" rel="noopener noreferrer" className="touch-target mt-2 inline-flex min-h-9 items-center gap-1 rounded-compact text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t(native ? "cuaDriver.source" : "cuaDriver.docs")}<ExternalLink className="h-3 w-3" aria-hidden />
      </a>}
    </section>
  </div>;
}

function CuaDriverPermissions({ check, appName, busy, onOpen, onReconnect }: {
  check: CuaDriverCheck;
  appName: string;
  busy: boolean;
  onOpen: (target: "accessibility" | "screen_recording" | "finder") => void;
  onReconnect?: () => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<"accessibility" | "screen_recording" | null>(null);
  // A manual selection only changes the instructions, never the grant status.
  // Keep both steps reachable when the driver cannot report its permissions.
  const current = selected && check[selected] !== true ? selected
    : check.accessibility !== true ? "accessibility" : "screen_recording";
  const permission = t(current === "accessibility" ? "cuaDriver.accessibility" : "cuaDriver.screenRecording");
  return <section aria-label={t("cuaDriver.finishSetup")}>
    <h3 className="text-base font-semibold">{t("cuaDriver.finishSetup")}</h3>
    <ol className="mt-4 grid grid-cols-2 gap-2">
      {(["accessibility", "screen_recording"] as const).map((key, index) => <li key={key} className="min-w-0">
        <button type="button" disabled={busy || check[key] === true} aria-current={current === key ? "step" : undefined}
          className={cn("flex h-full w-full items-start gap-2 rounded-control border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50 motion-reduce:transition-none",
            current === key ? "border-foreground/20 bg-muted/60" : "border-border/50 hover:bg-muted/35",
            (busy || check[key] === true) && "cursor-default")}
          onClick={() => setSelected(key)}>
          <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-xs text-muted-foreground" aria-hidden>
            {check[key] === true ? <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> : index + 1}
          </span>
          <span className="min-w-0">
            <span className="block text-xs font-medium">{t(key === "accessibility" ? "cuaDriver.accessibility" : "cuaDriver.screenRecording")}</span>
            <span className="mt-0.5 block text-[11px] leading-4 text-muted-foreground">{t(check[key] === true ? "cuaDriver.granted" : check[key] === false ? "cuaDriver.needed" : "cuaDriver.unknown")}</span>
          </span>
        </button>
      </li>)}
    </ol>
    <div className="mt-5">
      <p className="text-[13px] leading-5">{t("cuaDriver.permissionGuide", { permission, appName })}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{t(current === "accessibility" ? "cuaDriver.accessibilitySettingsHint" : "cuaDriver.screenSettingsHint")}</p>
      <Button size="sm" className="touch-target mt-3 min-h-10 w-full rounded-control px-4 text-[13px]" disabled={busy}
        aria-label={t("cuaDriver.openPermission", { permission })} onClick={() => onOpen(current)}>
        {t("cuaDriver.openSettings")}<ExternalLink className="ml-1.5 h-3 w-3 shrink-0" aria-hidden />
      </Button>
      <Disclosure className="mt-1.5 text-xs text-muted-foreground"
        summaryClassName="touch-target flex items-center gap-1.5 rounded-compact focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        contentClassName="space-y-3 pb-2 pt-2 leading-5"
        summary={<>{t("cuaDriver.setupHelp")}<ChevronDown className="h-3 w-3 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" aria-hidden /></>}>
        <div>
          <p className="font-medium text-foreground">{t("cuaDriver.missingApp", { appName })}</p>
          <p className="mt-1">{t("cuaDriver.dragHint", { appName })}</p>
          <Button variant="link" size="sm" className="touch-target px-0 text-xs" disabled={busy} onClick={() => onOpen("finder")}>{t("cuaDriver.showFinder")}</Button>
        </div>
        {onReconnect && <div>
          <p className="font-medium text-foreground">{t("cuaDriver.afterRelaunch")}</p>
          <p className="mt-1">{t("cuaDriver.afterRelaunchHint", { appName })}</p>
          <Button variant="link" size="sm" className="touch-target px-0 text-xs" disabled={busy} onClick={onReconnect}>{t("cuaDriver.reconnect")}</Button>
        </div>}
        <p>{t("cuaDriver.onceHint", { appName })}</p>
        <p>{t("cuaDriver.autoCheck")} {t("cuaDriver.checked")}</p>
      </Disclosure>
    </div>
  </section>;
}

export function CuaDriverSetupPanel({ preset, capabilities, actionKey, check, checkFeedback, error, onAction, onBackToChat, active = true }: {
  preset: McpPresetInfo;
  capabilities: unknown;
  actionKey: string | null;
  check?: CuaDriverCheck;
  checkFeedback?: CuaCheckFeedback | null;
  error: string | null;
  onAction: (action: McpPresetAction, name: string, values?: Record<string, string>) => void;
  onBackToChat?: () => void;
  active?: boolean;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"observe" | "control">(preset.driver_setup?.mode === "control" ? "control" : "observe");
  const [editingAccess, setEditingAccess] = useState(false);
  const [confirmUninstall, setConfirmUninstall] = useState(false);
  const [resetPermissions, setResetPermissions] = useState(false);
  const resetHintId = useId();
  const uninstallRef = useRef<HTMLButtonElement>(null);
  const primaryActionRef = useRef<HTMLButtonElement>(null);
  const changeAccessRef = useRef<HTMLButtonElement>(null);
  const accessChoiceRef = useRef<HTMLInputElement>(null);
  const setup = cuaDriverSetup(preset.driver_setup, capabilities);
  const appName = setup?.permission_app ?? "CuaDriver";
  const native = appName === "nanobot Computer Use";
  const previousInstalled = useRef(setup?.installed);
  useEffect(() => {
    if (previousInstalled.current && setup?.installed === false) primaryActionRef.current?.focus({ preventScroll: true });
    previousInstalled.current = setup?.installed;
  }, [setup?.installed]);
  const checking = actionKey === "test:cua-driver";
  const installing = actionKey === "install:cua-driver";
  const busy = Boolean(actionKey?.endsWith(":cua-driver")) && !checking;
  const enabled = Boolean(setup && setup.mode !== "off" && preset.configured);
  const needsConsent = !enabled || (editingAccess && setup?.mode !== mode);
  const canManage = Boolean(setup?.supported && setup.managed);
  const guided = canManage && Array.isArray(capabilities) && capabilities.includes(CUA_SETUP_CAPABILITY);
  const mac = setup?.platform === "Darwin";
  const canRequestPermissions = mac && guided && Array.isArray(capabilities) && capabilities.includes(CUA_PERMISSIONS_CAPABILITY);
  const canReconnect = guided && Array.isArray(capabilities) && capabilities.includes(CUA_RECONNECT_CAPABILITY);
  const canUninstall = canManage && setup?.installed && Array.isArray(capabilities) && capabilities.includes(CUA_UNINSTALL_CAPABILITY);
  const canResetPermissions = canUninstall && native && mac && capabilities.includes(CUA_UNINSTALL_RESET_CAPABILITY);
  const permissionsReady = !mac || (check?.accessibility === true && check?.screen_recording === true);
  const checkingPermissions = mac && guided && enabled && !check && !error;
  const statusKey = cuaDriverStatus(preset, setup, check, error);
  const ready = statusKey === "ready";
  const wasEditingAccess = useRef(false);
  useEffect(() => {
    if (editingAccess) accessChoiceRef.current?.focus({ preventScroll: true });
    if (wasEditingAccess.current && !editingAccess) changeAccessRef.current?.focus({ preventScroll: true });
    wasEditingAccess.current = editingAccess;
  }, [editingAccess]);
  const previousModeRef = useRef(setup?.mode);
  useEffect(() => {
    if (previousModeRef.current === setup?.mode) return;
    previousModeRef.current = setup?.mode;
    setMode(setup?.mode === "control" ? "control" : "observe");
    setEditingAccess(false);
  }, [setup?.mode]);
  const polling = useRef({ busy: Boolean(actionKey), ready, onAction });
  polling.current = { busy: Boolean(actionKey), ready, onAction };

  useEffect(() => {
    if (!active || !guided || !enabled) return;
    let disposed = false;
    let pending = false;
    let attempts = 0;
    let freshCheck = true;
    let timer: ReturnType<typeof setTimeout>;
    const inspect = async () => {
      if (disposed || pending || document.visibilityState === "hidden") return;
      if (!freshCheck && (polling.current.ready || attempts >= 24)) return;
      if (polling.current.busy) {
        timer = setTimeout(inspect, 5000);
        return;
      }
      pending = true;
      freshCheck = false;
      attempts += 1;
      try {
        await polling.current.onAction("test", preset.name, { quiet: "true" });
      } finally {
        pending = false;
        // Serial, bounded checks; a closed dialog or changed host owns no timer.
        if (!disposed && attempts < 24) timer = setTimeout(inspect, 5000);
      }
    };
    const resume = () => {
      if (document.visibilityState === "hidden") return;
      clearTimeout(timer);
      attempts = 0;
      freshCheck = true;
      // Visibility and focus often fire together. Coalesce them, and refresh
      // once after any in-flight check that began before the user returned.
      if (!pending) timer = setTimeout(inspect, 100);
    };
    timer = setTimeout(inspect, 0);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      disposed = true;
      clearTimeout(timer);
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [active, guided, enabled, preset.name]);

  const act = (action: McpPresetAction) => {
    onAction(action, preset.name, action === "install"
      ? { consent: `${CUA_CAPABILITY}:install` }
      : action === "enable" ? {
        mode, consent: `${CUA_CAPABILITY}:${mode}`,
        ...(canRequestPermissions && !enabled ? { permissions: CUA_PERMISSIONS_CAPABILITY } : {}),
      } : {});
  };
  const accessId = useId();
  // Missing first-run grants can prevent the daemon from starting at all.
  // An unavailable connection must not hide the path to finish system setup.
  const pendingPermissions = mac && guided && enabled && Boolean(check) && !permissionsReady;
  const reconnectNeeded = enabled && (statusKey === "connectionIssue" || statusKey === "sharingPaused") && canReconnect;
  const feedback = checkFeedback?.state === "done" ? checkFeedback : null;
  const checkedGrants = feedback?.check;
  const checkOutcome = feedback?.error ? "checkFailed"
    : !checkedGrants ? "checkIncomplete"
    : checkedGrants.sharing_paused ? "sharingPausedHint"
    : mac && (checkedGrants.accessibility === false || checkedGrants.screen_recording === false) ? "checkPermissions"
    : mac && (checkedGrants.accessibility !== true || checkedGrants.screen_recording !== true) ? "checkUnknown"
    : checkedGrants.connected && feedback?.runtimeConnected ? "checkReady" : "checkDisconnected";
  // Once there is a clear next action, diagnostics should not compete with it.
  // Hosts without guided setup still need the direct manual check path.
  const checkInDetails = ready || reconnectNeeded;
  const checkButton = <Button variant="ghost" size="sm" className="touch-target min-h-10 rounded-full px-3 text-xs text-muted-foreground" disabled={busy || checking} onClick={() => act("test")}>
    {checking && <Loader2 className="mr-1.5 h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />}{t(checking ? "cuaDriver.checking" : "cuaDriver.check")}
  </Button>;
  const accessOptions = <fieldset disabled={busy}>
    <legend className="mb-2.5 text-[13px] font-medium">{t("cuaDriver.access")}</legend>
    <div className="space-y-2">
      {(["observe", "control"] as const).map(value => {
        const Icon = value === "observe" ? Eye : MousePointer2;
        const selected = mode === value;
        return <label key={value} className={cn(
          "flex cursor-pointer items-center gap-3 rounded-control border px-3.5 py-3 transition-colors motion-reduce:transition-none has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-inset has-[:focus-visible]:ring-ring/50",
          selected ? "border-foreground/20 bg-muted/60" : "border-border/60 hover:bg-muted/35",
          busy && "cursor-default opacity-60",
        )}>
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1">
            <span id={`${accessId}-${value}`} className="block font-medium">{t(`cuaDriver.${value}`)}</span>
            <span id={`${accessId}-${value}-hint`} className="mt-0.5 block text-xs leading-[18px] text-muted-foreground">{t(`cuaDriver.${value}Hint`)}</span>
          </span>
          <input ref={selected ? accessChoiceRef : undefined} type="radio" name={accessId} value={value} checked={selected}
            aria-labelledby={`${accessId}-${value}`} aria-describedby={`${accessId}-${value}-hint`}
            onChange={() => setMode(value)} className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-none" />
        </label>;
      })}
    </div>
  </fieldset>;

  return <div className="flex min-h-0 flex-col text-[13px] leading-5">
    <div className="min-h-0 space-y-5 overflow-y-auto overscroll-contain px-5 pb-4 pt-2 scrollbar-thin scrollbar-track-transparent sm:px-6 [&>.inline-disclosure[data-state=closed]]:!mt-0">
      {!setup ? <p role="status">{t("cuaDriver.unconfirmed")}</p> : <>
        {canManage && !setup.installed && <CuaDriverFeatures />}
        <section aria-label={t("cuaDriver.device")} className={cn("flex items-start gap-2.5 text-xs", setup.installed && "border-b border-border/45 pb-4")}>
          <Monitor className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="min-w-0 break-words font-medium [overflow-wrap:anywhere]">{setup.machine}</h3>
              {canManage && <span role="status" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                {checkingPermissions ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
                  : <span className={cn("h-1.5 w-1.5 rounded-full", ready ? "bg-emerald-500" : "bg-muted-foreground/50")} aria-hidden />}
                {t(`cuaDriver.${statusKey === "accessOff" ? "installed" : statusKey}`)}
              </span>}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("cuaDriver.device")} · {mac ? "macOS" : setup.platform}</p>
          </div>
        </section>
        {!setup.supported && <p role="status">{t("cuaDriver.unsupported")}</p>}
        {!setup.managed && <p role="status">{t("cuaDriver.manual")}</p>}
        {canManage && <>
          {setup.installed ? <>
            {!enabled && accessOptions}
            {!enabled && canRequestPermissions && <p className="text-xs text-muted-foreground">{t(native ? "cuaDriver.nativeRequestHint" : "cuaDriver.requestHint", { appName })}</p>}
            {(!mac || !guided) && <p className="text-xs text-muted-foreground">{t(mac ? "cuaDriver.permissions" : "cuaDriver.desktopSession")}</p>}
            {reconnectNeeded && !editingAccess && <section aria-label={t("cuaDriver.reconnect")}>
              <h3 className="text-base font-semibold">{t("cuaDriver.reconnect")}</h3>
              <p className="mt-1.5 text-[13px] leading-5 text-muted-foreground">{t(statusKey === "sharingPaused" ? "cuaDriver.sharingPausedHint" : "cuaDriver.reconnectHint")}</p>
            </section>}
            {pendingPermissions && check && !editingAccess && <CuaDriverPermissions check={check} appName={appName} busy={busy}
              onOpen={target => onAction("setup", preset.name, { target })}
              // macOS can relaunch the bundle without its private socket arguments.
              // Missing grants cannot be inferred from that absent connection;
              // keep an explicit recovery path without auto-restarting the app.
              onReconnect={canReconnect && !check.connected ? () => act("reconnect") : undefined} />}
            {checkingPermissions && !editingAccess && <p className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />{t("cuaDriver.checkingPermissions")}</p>}
            {ready && onBackToChat && <p className="text-[13px] leading-5">{t("cuaDriver.connectedHint")}</p>}
            {enabled && <div>
              <Button ref={changeAccessRef} variant="ghost" size="sm" className="touch-target -mx-2 h-auto min-h-9 whitespace-normal rounded-control px-2 py-2 text-left text-xs font-normal text-muted-foreground" disabled={busy}
                aria-label={t("cuaDriver.changeAccess")}
                aria-expanded={editingAccess} aria-controls={`${accessId}-editor`}
                onClick={() => {
                  setMode(setup.mode === "control" ? "control" : "observe");
                  setEditingAccess(!editingAccess);
                }}>
                  {t("cuaDriver.currentAccess", { mode: t(setup.mode === "control" ? "cuaDriver.control" : setup.mode === "observe" ? "cuaDriver.observe" : "cuaDriver.custom") })}
                  <ChevronDown className={cn("ml-1.5 h-3 w-3 shrink-0 transition-transform motion-reduce:transition-none", editingAccess && "rotate-180")} aria-hidden />
                </Button>
              <DisclosureContent id={`${accessId}-editor`} open={editingAccess} className="pt-2.5">{accessOptions}</DisclosureContent>
            </div>}
            {enabled && !editingAccess && !pendingPermissions && <Disclosure className="text-xs text-muted-foreground"
              summaryClassName="touch-target flex items-center gap-1.5 rounded-compact focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              summary={<>{t("cuaDriver.connectionDetails")}<ChevronDown className="h-3 w-3 shrink-0 transition-transform group-data-[state=open]/disclosure:rotate-180 motion-reduce:transition-none" aria-hidden /></>}>
              <p className="mt-2">{t("cuaDriver.checked")}</p>
              <p className="mt-2">{t("cuaDriver.disableHint")}</p>
              {check && mac && !ready && !pendingPermissions && <p className="mt-1 text-xs text-muted-foreground">{t("cuaDriver.grants", {
                  accessibility: t(check.accessibility === true ? "cuaDriver.granted" : check.accessibility === false ? "cuaDriver.needed" : "cuaDriver.unknown"),
                  screen: t(check.screen_recording === true ? "cuaDriver.granted" : check.screen_recording === false ? "cuaDriver.needed" : "cuaDriver.unknown"),
                })}</p>}
              {checkInDetails && <div className="-ml-3 mt-2">{checkButton}</div>}
            </Disclosure>}
            {(!enabled || editingAccess) && <p className="text-xs leading-5 text-muted-foreground">
              {t("cuaDriver.scopeHint")}{" "}{t("cuaDriver.allowHint")}
            </p>}
          </> : null}
        </>}
      </>}
      {error && error !== feedback?.error && <p role="alert" className="rounded-control bg-destructive/5 px-3 py-2 text-xs text-destructive [overflow-wrap:anywhere]">{error}</p>}
    </div>
    {canManage && (enabled || needsConsent) && <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-border/45 bg-muted/20 px-5 py-3 sm:px-6">
      {checkFeedback?.state === "checking" && <span role="status" className="sr-only">{t("cuaDriver.checking")}</span>}
      {feedback && <div role={feedback.error ? "alert" : "status"} aria-label={t("cuaDriver.checkResult")} aria-atomic="true"
        className="flex w-full items-start gap-2.5 rounded-control bg-muted/45 px-3 py-2.5 text-xs leading-5">
        {checkOutcome === "checkReady" ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
          : <Info className={cn("mt-0.5 h-4 w-4 shrink-0", feedback.error ? "text-destructive" : "text-muted-foreground")} aria-hidden />}
        <div className="min-w-0">
          <p className="font-medium">{t("cuaDriver.checkResult")}</p>
          <p className={cn("mt-0.5 [overflow-wrap:anywhere]", feedback.error && "text-destructive")}>{t(`cuaDriver.${checkOutcome}`, { appName })}</p>
          {feedback.error && <p className="mt-1 text-muted-foreground [overflow-wrap:anywhere]">{feedback.error}</p>}
          {!feedback.error && <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{t("cuaDriver.checked")}</p>}
        </div>
      </div>}
      {busy && <p role="status" className={cn("w-full text-xs leading-5 text-muted-foreground", !installing && needsConsent && "sr-only")}>{t(installing ? native ? "cuaDriver.installingAction" : "cuaDriver.installing" : "cuaDriver.working")}{installing && !native && <> {t("cuaDriver.downloadBackground")}</>}</p>}
      {!setup?.installed && !installing && <p className="w-full pb-1 text-xs leading-5 text-muted-foreground">{t("cuaDriver.installOnly")}</p>}
      {!setup?.installed && <span className="mr-auto inline-flex items-center gap-2 text-xs text-muted-foreground" title={t("cuaDriver.attribution")}>
        <span className="h-5 w-5 shrink-0" aria-hidden>
          <img src={cuaBlackLogo} alt="" className="h-full w-full object-contain dark:hidden" />
          <img src={cuaWhiteLogo} alt="" className="hidden h-full w-full object-contain dark:block" />
        </span>
        Cua Driver
      </span>}
      {enabled && needsConsent && <p className="w-full text-xs text-muted-foreground">{t("cuaDriver.pendingChange")}</p>}
      {enabled && <Button variant="ghost" size="sm" className="touch-target mr-auto min-h-10 rounded-full px-3 text-muted-foreground" disabled={busy} onClick={() => act("disable")}>{t("cuaDriver.disable")}</Button>}
      {canUninstall && !enabled && <Button ref={uninstallRef} variant="ghost" size="sm" className="touch-target mr-auto min-h-10 rounded-full px-3 text-muted-foreground" disabled={busy} onClick={() => {
        setResetPermissions(false);
        setConfirmUninstall(true);
      }}>{t("cuaDriver.uninstall")}</Button>}
      {enabled && editingAccess && <Button variant="ghost" size="sm" className="touch-target min-h-10 rounded-full px-3" disabled={busy} onClick={() => {
        setMode(setup?.mode === "control" ? "control" : "observe");
        setEditingAccess(false);
      }}>{t("common.cancel")}</Button>}
      {enabled && !editingAccess && !checkInDetails && checkButton}
      {reconnectNeeded && !editingAccess && <Button size="sm" className="touch-target h-auto min-h-10 max-w-full whitespace-normal rounded-full px-5 py-2" disabled={busy} onClick={() => act("reconnect")}>{t("cuaDriver.reconnect")}</Button>}
      {needsConsent && <Button ref={primaryActionRef} size="sm" className="touch-target h-auto min-h-10 max-w-full whitespace-normal rounded-full px-5 py-2" disabled={busy} onClick={() => act(setup?.installed ? "enable" : "install")}>
        {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
          : !setup?.installed && <Download className="mr-1.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
        {t(busy ? installing ? "cuaDriver.installingAction" : "cuaDriver.working"
          : setup?.installed ? mode === "control" ? "cuaDriver.allowControl" : "cuaDriver.allowObserve" : native ? "cuaDriver.installAction" : "cuaDriver.install")}
      </Button>}
      {ready && !editingAccess && onBackToChat && <Button size="sm" className="touch-target h-auto min-h-10 max-w-full whitespace-normal rounded-full px-5 py-2" disabled={busy} onClick={onBackToChat}>{t("settings.backToChat")}</Button>}
    </div>}
    <AlertDialog open={confirmUninstall} onOpenChange={setConfirmUninstall}>
      <AlertDialogContent onCloseAutoFocus={event => { event.preventDefault(); uninstallRef.current?.focus({ preventScroll: true }); }}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("cuaDriver.uninstallTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t(canResetPermissions ? "cuaDriver.nativeUninstallHint" : "cuaDriver.uninstallHint", { machine: setup?.machine })}</AlertDialogDescription>
        </AlertDialogHeader>
        {canResetPermissions && <label className="flex cursor-pointer items-start gap-3 rounded-control border border-border/60 bg-muted/30 p-3.5 text-left transition-colors settings-hover has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-inset has-[:focus-visible]:ring-ring">
          <span className="relative mt-0.5 h-5 w-5 shrink-0">
            <input type="checkbox" checked={resetPermissions} onChange={event => setResetPermissions(event.target.checked)}
              aria-label={t("cuaDriver.resetPermissions")} aria-describedby={resetHintId}
              className="peer absolute inset-0 z-10 h-5 w-5 cursor-pointer opacity-0" />
            <span aria-hidden className={cn("pointer-events-none absolute inset-0 grid place-items-center rounded-compact border transition-colors",
              resetPermissions ? "border-foreground bg-foreground text-background" : "border-border bg-background text-transparent")}>
              <Check className="h-3 w-3" strokeWidth={2.75} />
            </span>
          </span>
          <span className="min-w-0 text-sm leading-5">
            <span className="font-medium">{t("cuaDriver.resetPermissions")}</span>
            <span id={resetHintId} className="mt-1 block text-xs leading-5 text-muted-foreground">{t("cuaDriver.resetPermissionsHint")}</span>
          </span>
        </label>}
        <AlertDialogFooter>
          <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
          <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={() => onAction("uninstall", preset.name, {
            consent: canResetPermissions && resetPermissions ? CUA_UNINSTALL_RESET_CAPABILITY : CUA_UNINSTALL_CAPABILITY,
          })}>{t("cuaDriver.uninstall")}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;
}
