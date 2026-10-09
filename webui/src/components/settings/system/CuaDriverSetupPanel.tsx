import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown, Download, ExternalLink, Eye, Loader2, Monitor, MousePointer2, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import computerUseIcon from "@/assets/apps/computer-use.webp";
import cuaBlackLogo from "@/assets/apps/cua-black.svg";
import cuaWhiteLogo from "@/assets/apps/cua-white.svg";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CuaDriverCheck, CuaDriverSetup, McpPresetAction, McpPresetInfo } from "@/lib/types";

export const CUA_CAPABILITY = "webui.cua-driver.v1";
export const CUA_SETUP_CAPABILITY = "webui.cua-driver-guided-setup.v1";
export const CUA_PERMISSIONS_CAPABILITY = "webui.cua-driver-permission-request.v1";
export const CUA_RECONNECT_CAPABILITY = "webui.cua-driver-reconnect.v1";

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
  if (setup.permission_app !== undefined && setup.permission_app !== "CuaDriver") return null;
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
  if (error || check?.connected === false) return "connectionIssue";
  const mac = setup.platform === "Darwin";
  if (mac && check && (check.accessibility !== true || check.screen_recording !== true)) return "permissionPending";
  if (preset.runtime_status === "failed") return "connectionIssue";
  if (check?.connected === true && preset.runtime_status === "connected") return "ready";
  return "enabled";
}

export function CuaDriverOverview({ docsUrl, setup }: { docsUrl: string; setup: CuaDriverSetup | null }) {
  const { t } = useTranslation();
  return <div>
    <ul className="space-y-5 rounded-panel bg-muted/35 p-4 sm:p-5">
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
    </ul>
    <section className="mt-5 border-t border-border/45 pt-4">
      <div className="flex items-center gap-2.5">
        <span className="h-6 w-6 shrink-0" aria-hidden>
          <img src={cuaBlackLogo} alt="" className="h-full w-full object-contain dark:hidden" />
          <img src={cuaWhiteLogo} alt="" className="hidden h-full w-full object-contain dark:block" />
        </span>
        <div className="min-w-0">
          <h3 className="text-xs font-medium">Cua Driver{setup && <span className="ml-2 font-normal text-muted-foreground">{setup.version}</span>}</h3>
          <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{t("cuaDriver.attribution")}</p>
        </div>
      </div>
      <div className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground">
        <p>{t("cuaDriver.gatewayHint")}</p>
        <p>{t("cuaDriver.nativeFeedback")}</p>
        <p>{t("cuaDriver.installHint")}</p>
      </div>
      {docsUrl && <a href={docsUrl} target="_blank" rel="noopener noreferrer" className="touch-target mt-2 inline-flex min-h-9 items-center gap-1 rounded-compact text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t("cuaDriver.docs")}<ExternalLink className="h-3 w-3" aria-hidden />
      </a>}
    </section>
  </div>;
}

export function CuaDriverSetupPanel({ preset, capabilities, actionKey, check, error, onAction, onBackToChat, active = true }: {
  preset: McpPresetInfo;
  capabilities: unknown;
  actionKey: string | null;
  check?: CuaDriverCheck;
  error: string | null;
  onAction: (action: McpPresetAction, name: string, values?: Record<string, string>) => void;
  onBackToChat?: () => void;
  active?: boolean;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"observe" | "control">(preset.driver_setup?.mode === "control" ? "control" : "observe");
  const [editingAccess, setEditingAccess] = useState(false);
  const changeAccessRef = useRef<HTMLButtonElement>(null);
  const setup = cuaDriverSetup(preset.driver_setup, capabilities);
  const appName = setup?.permission_app ?? "CuaDriver";
  const checking = actionKey === "test:cua-driver";
  const busy = Boolean(actionKey?.endsWith(":cua-driver")) && !checking;
  const enabled = Boolean(setup && setup.mode !== "off" && preset.configured);
  const needsConsent = !enabled || (editingAccess && setup?.mode !== mode);
  const canManage = Boolean(setup?.supported && setup.managed);
  const guided = canManage && Array.isArray(capabilities) && capabilities.includes(CUA_SETUP_CAPABILITY);
  const mac = setup?.platform === "Darwin";
  const canRequestPermissions = mac && guided && Array.isArray(capabilities) && capabilities.includes(CUA_PERMISSIONS_CAPABILITY);
  const canReconnect = guided && Array.isArray(capabilities) && capabilities.includes(CUA_RECONNECT_CAPABILITY);
  const permissionsReady = !mac || (check?.accessibility === true && check?.screen_recording === true);
  const checkingPermissions = mac && guided && enabled && !check && !error;
  const statusKey = cuaDriverStatus(preset, setup, check, error);
  const ready = statusKey === "ready";
  useEffect(() => {
    setMode(setup?.mode === "control" ? "control" : "observe");
    setEditingAccess(false);
    changeAccessRef.current?.focus({ preventScroll: true });
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
  const accessOptions = <fieldset disabled={busy}>
    <legend className="mb-2.5 text-[13px] font-medium">{t("cuaDriver.access")}</legend>
    <div className="space-y-2">
      {(["observe", "control"] as const).map(value => {
        const Icon = value === "observe" ? Eye : MousePointer2;
        const selected = mode === value;
        return <label key={value} className={cn(
          "flex cursor-pointer items-center gap-3 rounded-control border px-3.5 py-3 transition-colors motion-reduce:transition-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2",
          selected ? "border-foreground/20 bg-muted/60" : "border-border/60 hover:bg-muted/35",
          busy && "cursor-default opacity-60",
        )}>
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1">
            <span id={`${accessId}-${value}`} className="block font-medium">{t(`cuaDriver.${value}`)}</span>
            <span id={`${accessId}-${value}-hint`} className="mt-0.5 block text-xs leading-[18px] text-muted-foreground">{t(`cuaDriver.${value}Hint`)}</span>
          </span>
          <input type="radio" name={accessId} value={value} checked={selected}
            aria-labelledby={`${accessId}-${value}`} aria-describedby={`${accessId}-${value}-hint`}
            onChange={() => setMode(value)} className="h-4 w-4 shrink-0 accent-primary" />
        </label>;
      })}
    </div>
  </fieldset>;

  return <div className="flex min-h-0 flex-1 flex-col text-[13px] leading-5">
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 pb-3 pt-2 scrollbar-thin scrollbar-track-transparent sm:px-6">
      {!setup ? <p role="status">{t("cuaDriver.unconfirmed")}</p> : <>
        <section aria-label={t("cuaDriver.device")} className="flex items-start gap-3 rounded-control bg-muted/50 p-3.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-compact bg-background/80">
            <Monitor className="h-[18px] w-[18px] text-muted-foreground" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="min-w-0 break-words font-medium [overflow-wrap:anywhere]">{setup.machine}</h3>
              {canManage && <span role="status" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                {checkingPermissions ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
                  : <span className={cn("h-1.5 w-1.5 rounded-full", ready ? "bg-emerald-500" : "bg-muted-foreground/50")} aria-hidden />}
                {t(`cuaDriver.${statusKey}`)}
              </span>}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("cuaDriver.device")} · {mac ? "macOS" : setup.platform}</p>
          </div>
        </section>
        {!setup.supported && <p role="status">{t("cuaDriver.unsupported")}</p>}
        {!setup.managed && <p role="status">{t("cuaDriver.manual")}</p>}
        {canManage && <>
          {setup.installed ? <>
            {enabled && <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <p className="font-medium">{t("cuaDriver.currentAccess", { mode: t(setup.mode === "control" ? "cuaDriver.control" : setup.mode === "observe" ? "cuaDriver.observe" : "cuaDriver.custom") })}</p>
              <Button ref={changeAccessRef} variant="ghost" size="sm" className="touch-target -mr-2 rounded-full text-xs" disabled={busy}
                aria-expanded={editingAccess} aria-controls={`${accessId}-editor`}
                onClick={() => {
                  setMode(setup.mode === "control" ? "control" : "observe");
                  setEditingAccess(!editingAccess);
                }}>{t(editingAccess ? "common.cancel" : "cuaDriver.changeAccess")}</Button>
            </div>}
            {(!enabled || editingAccess) && <div id={`${accessId}-editor`}>{accessOptions}</div>}
            {!enabled && canRequestPermissions && <p className="text-xs text-muted-foreground">{t("cuaDriver.requestHint", { appName })}</p>}
            {(!mac || !guided) && <p className="text-xs text-muted-foreground">{t(mac ? "cuaDriver.permissions" : "cuaDriver.desktopSession")}</p>}
            {enabled && statusKey === "connectionIssue" && canReconnect && <section className="rounded-control bg-muted/40 p-3.5" aria-label={t("cuaDriver.reconnect")}>
              <h3 className="font-medium">{t("cuaDriver.connectionIssue")}</h3>
              <p className="mt-1 text-xs text-muted-foreground">{t("cuaDriver.reconnectHint")}</p>
              <Button size="sm" className="touch-target mt-3 h-auto min-h-10 whitespace-normal rounded-full px-4 py-2" disabled={busy} onClick={() => act("reconnect")}>{t("cuaDriver.reconnect")}</Button>
            </section>}
            {pendingPermissions && <section aria-label={t("cuaDriver.finishSetup")}>
              <h3 className="font-medium">{t("cuaDriver.finishSetup")}</h3>
              <p className="mt-1 text-xs text-muted-foreground">{t("cuaDriver.onceHint", { appName })}</p>
              <div className="mt-3 divide-y divide-border/45">
                {(["accessibility", "screen_recording"] as const).filter(key => check?.[key] !== true).map((key, index) => <div key={key} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
                  <span className="flex min-w-0 flex-[1_1_8rem] items-center gap-3">
                    {key === "accessibility" ? <MousePointer2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /> : <Monitor className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                    <span className="min-w-0">
                      <span className="block font-medium">{t(key === "accessibility" ? "cuaDriver.accessibility" : "cuaDriver.screenRecording")}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{t(key === "accessibility" ? "cuaDriver.accessibilityPurpose" : "cuaDriver.screenPurpose")}</span>
                    </span>
                  </span>
                  <Button variant={index === 0 ? "default" : "outline"} size="sm" className="touch-target ml-auto shrink-0 rounded-full text-xs" disabled={busy} aria-label={t("cuaDriver.openPermission", { permission: t(key === "accessibility" ? "cuaDriver.accessibility" : "cuaDriver.screenRecording") })}
                    onClick={() => onAction("setup", preset.name, { target: key })}>
                    {t("cuaDriver.openSettings")}<ExternalLink className="ml-1.5 h-3 w-3 shrink-0" aria-hidden />
                  </Button>
                </div>)}
              </div>
              <details className="group/help text-xs text-muted-foreground">
                <summary className="touch-target flex cursor-pointer list-none items-center gap-1.5 rounded-compact focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                  {t("cuaDriver.missingApp", { appName })}<ChevronDown className="h-3 w-3 shrink-0 transition-transform group-open/help:rotate-180 motion-reduce:transition-none" aria-hidden />
                </summary>
                {canRequestPermissions && <Button variant="outline" size="sm" className="touch-target my-2 h-auto min-h-10 whitespace-normal rounded-full px-4 py-2" disabled={busy}
                  onClick={() => onAction("setup", preset.name, { target: "permissions", consent: CUA_PERMISSIONS_CAPABILITY })}>
                  {t("cuaDriver.requestPermissions")}
                </Button>}
                <p className="mt-1">{t("cuaDriver.dragHint", { appName })}</p>
                <Button variant="link" size="sm" className="touch-target px-0 text-xs" disabled={busy} onClick={() => onAction("setup", preset.name, { target: "finder" })}>{t("cuaDriver.showFinder")}</Button>
              </details>
              <p className="mt-1 text-xs text-muted-foreground">{t("cuaDriver.autoCheck")}</p>
            </section>}
            {enabled && <section aria-label={t("cuaDriver.check")} className="border-t border-border/45 pt-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 flex-[1_1_12rem] text-xs text-muted-foreground">{t(checkingPermissions ? "cuaDriver.checkingPermissions" : "cuaDriver.checked")}</p>
                <Button variant="ghost" size="sm" className="touch-target -mr-2 shrink-0 rounded-full text-xs" disabled={busy || checking} onClick={() => act("test")}>
                  {checking && <Loader2 className="mr-1.5 h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />}
                  {t("cuaDriver.check")}
                </Button>
              </div>
              {check && mac && !ready && !pendingPermissions && <p className="mt-1 text-xs text-muted-foreground">{t("cuaDriver.grants", {
                  accessibility: t(check.accessibility === true ? "cuaDriver.granted" : check.accessibility === false ? "cuaDriver.needed" : "cuaDriver.unknown"),
                  screen: t(check.screen_recording === true ? "cuaDriver.granted" : check.screen_recording === false ? "cuaDriver.needed" : "cuaDriver.unknown"),
                })}</p>}
              {error && <p role="alert" className="mt-2 break-words text-xs text-destructive">{error}</p>}
            </section>}
            <p className="text-xs leading-5 text-muted-foreground">
              {t("cuaDriver.scopeHint")}{" "}{t("cuaDriver.allowHint")}
            </p>
          </> : <p className="text-muted-foreground">{t("cuaDriver.installOnly")}</p>}
        </>}
      </>}
      {error && !(canManage && enabled && setup?.installed) && <p role="alert" className="text-destructive">{error}</p>}
      {busy && !actionKey?.startsWith("test:") && !actionKey?.startsWith("setup:") && <p role="status" className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />{t(actionKey?.startsWith("install:") ? "cuaDriver.installing" : "cuaDriver.working")}</p>}
    </div>
    {canManage && (enabled || needsConsent) && <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-border/45 bg-muted/20 px-5 py-3 sm:px-6">
      {enabled && needsConsent && <p className="w-full text-xs text-muted-foreground">{t("cuaDriver.pendingChange")}</p>}
      {enabled && <Button variant="outline" size="sm" className={cn("touch-target min-h-10 rounded-full px-5", (needsConsent || ready) && "mr-auto")} disabled={busy} onClick={() => act("disable")}>{t("cuaDriver.disable")}</Button>}
      {needsConsent && <Button size="sm" className="touch-target h-auto min-h-10 max-w-full whitespace-normal rounded-full px-5 py-2" disabled={busy} onClick={() => act(setup?.installed ? "enable" : "install")}>
        {!setup?.installed && <Download className="mr-1.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
        {t(setup?.installed ? mode === "control" ? "cuaDriver.allowControl" : "cuaDriver.allowObserve" : "cuaDriver.install")}
      </Button>}
      {ready && !editingAccess && onBackToChat && <Button size="sm" className="touch-target h-auto min-h-10 max-w-full whitespace-normal rounded-full px-5 py-2" disabled={busy} onClick={onBackToChat}>{t("settings.backToChat")}</Button>}
    </div>}
  </div>;
}
