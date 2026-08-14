import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Eye, EyeOff, Moon, PanelLeft, ShieldCheck, Sun, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { channelUiPresentation } from "@/channel-plugins/registry";
import { Sidebar } from "@/components/Sidebar";
import type { SidebarDeleteItem } from "@/components/ChatList";
import type { SettingsSectionKey } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { PaneWorkbench } from "@/components/workbench/PaneWorkbench";
import {
  MAX_WORKBENCH_PANES,
  addWorkbenchPane,
  attachWorkbenchPane,
  createWorkbenchTab,
  detachWorkbenchPane,
  dissolveWorkbenchTab,
  orderWorkbenchTabs,
  reconcileWorkbench,
  renameWorkbenchTab,
  setWorkbenchLayout,
  setWorkbenchPaneLayoutOrder,
  setWorkbenchSplitRatios,
  workbenchTab,
  workbenchTabForPane,
  type WorkbenchState,
} from "@/components/workbench/workbench-model";
import { floatingSurfaceElevationClassName } from "@/components/ui/floating-surface";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

import { useSessions } from "@/hooks/useSessions";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { useSidebarState } from "@/hooks/useSidebarState";
import { useSkills } from "@/hooks/useSkills";
import { useLogoFallback } from "@/hooks/useLogoFallback";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ThemeProvider, useTheme } from "@/hooks/useTheme";
import { logoFallbackUrls } from "@/lib/provider-brand";
import { cn } from "@/lib/utils";
import {
  BootstrapAuthRequiredError,
  clearSavedSecret,
  consumeUrlBootstrapSecret,
  deriveWsUrl,
  fetchBootstrap,
  loadSavedSecret,
  saveSecret,
} from "@/lib/bootstrap";
import { displayTitle, sortSessions } from "@/lib/chat-groups";
import { deriveTitle } from "@/lib/format";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import type {
  BootstrapResponse,
  ChatSummary,
  RuntimeSurface,
  PairingRequestInfo,
  SessionAutomationJob,
  SettingsPayload,
  WorkspaceScopePayload,
  WorkspacesPayload,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchPairingRequests,
  fetchSettings,
  fetchWorkspaces,
  runPairingAction,
} from "@/lib/api";
import {
  createRuntimeHost,
  toRuntimeSurface,
} from "@/lib/runtime";
import { projectNameFromPath, scopeWithAccessMode } from "@/lib/workspace";
import {
  createTemporaryChatSession,
  deriveTemporaryChatTitle,
} from "@/lib/temporary-chat";

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "auth"; failed?: boolean }
  | {
      status: "ready";
      client: NanobotClient;
      token: string;
      tokenExpiresAt: number | null;
      modelName: string | null;
      ingressLimits: BootstrapResponse["limits"] | null;
      runtimeSurface: RuntimeSurface;
    };

const SIDEBAR_STORAGE_KEY = "nanobot-webui.sidebar";
const SESSION_UPDATES_STORAGE_KEY = "nanobot-webui.sidebar.session-updates.v1";
const LEGACY_COMPLETED_RUNS_STORAGE_KEY = "nanobot-webui.sidebar.completed-runs.v1";
const RESTART_STARTED_KEY = "nanobot-webui.restartStartedAt";
const RESTART_ROUTE_KEY = "nanobot-webui.restartRoute";
const RESTART_ROUTE_TTL_MS = 5 * 60 * 1000;
const SIDEBAR_WIDTH = 272;
const SIDEBAR_RAIL_WIDTH = 56;
const MOBILE_SIDEBAR_WIDTH = `min(${SIDEBAR_WIDTH}px, calc(100vw - 0.75rem))`;
const TOKEN_REFRESH_MARGIN_MS = 30_000;
const TOKEN_REFRESH_MIN_DELAY_MS = 5_000;
const PAIRING_POLL_INTERVAL_MS = 5_000;
const PAIRING_IDLE_POLL_INTERVAL_MS = 15_000;
const PAIRING_DISMISS_SNOOZE_MS = 30_000;
type ShellView = "chat" | "settings" | "apps" | "automations" | "skills";
type ShellRoute = {
  view: ShellView;
  activeKey: string | null;
  settingsSection: SettingsSectionKey;
  temporary?: boolean;
};
const loadSettingsView = () => import("@/components/settings/SettingsView");
const SettingsView = lazy(async () => {
  const module = await loadSettingsView();
  return { default: module.SettingsView };
});
const SessionSearchDialog = lazy(async () => {
  const module = await import("@/components/SessionSearchDialog");
  return { default: module.SessionSearchDialog };
});
const DeleteConfirm = lazy(async () => {
  const module = await import("@/components/DeleteConfirm");
  return { default: module.DeleteConfirm };
});
const RenameChatDialog = lazy(async () => {
  const module = await import("@/components/RenameChatDialog");
  return { default: module.RenameChatDialog };
});

function SurfaceLoadingFallback() {
  const { t } = useTranslation();
  return (
    <div
      aria-busy="true"
      className="flex h-full w-full flex-col gap-5 px-5 py-8 sm:px-8 lg:px-12"
    >
      <span className="sr-only">{t("settings.status.loading")}</span>
      <div className="h-4 w-20 animate-pulse rounded bg-muted/70 motion-reduce:animate-none" />
      <div className="h-9 w-48 animate-pulse rounded bg-muted/70 motion-reduce:animate-none" />
      <div className="mt-4 h-12 w-full max-w-3xl animate-pulse rounded-md bg-muted/55 motion-reduce:animate-none" />
      <div className="h-28 w-full max-w-3xl animate-pulse rounded-md bg-muted/40 motion-reduce:animate-none" />
    </div>
  );
}

const SETTINGS_SECTION_KEYS: SettingsSectionKey[] = [
  "overview",
  "appearance",
  "models",
  "image",
  "voice",
  "browser",
  "channels",
  "apps",
  "automations",
  "skills",
  "runtime",
  "advanced",
];

function isSettingsSectionKey(value: string | null): value is SettingsSectionKey {
  return SETTINGS_SECTION_KEYS.includes(value as SettingsSectionKey);
}

function defaultShellRoute(): ShellRoute {
  return { view: "chat", activeKey: null, settingsSection: "overview" };
}

function shellViewForSettingsSection(section: SettingsSectionKey): ShellView {
  if (section === "apps" || section === "automations" || section === "skills") return section;
  return "settings";
}

function fallbackRestartHash(hash: string): boolean {
  return !hash || hash === "/" || hash === "/new";
}

function rememberRestartRoute(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RESTART_ROUTE_KEY, window.location.hash || "#/new");
  } catch {
    // ignore storage errors
  }
}

function maybeRestoreRestartHash(hash: string): string {
  if (typeof window === "undefined" || !fallbackRestartHash(hash)) return hash;
  try {
    const startedAt = Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
    const storedHash = window.localStorage.getItem(RESTART_ROUTE_KEY);
    if (!startedAt || !storedHash || Date.now() - startedAt > RESTART_ROUTE_TTL_MS) {
      window.localStorage.removeItem(RESTART_ROUTE_KEY);
      return hash;
    }
    window.localStorage.removeItem(RESTART_ROUTE_KEY);
    const nextHash = storedHash.startsWith("#") ? storedHash : `#${storedHash}`;
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
    return nextHash.slice(1);
  } catch {
    return hash;
  }
}

function readShellRoute(): ShellRoute {
  if (typeof window === "undefined") return defaultShellRoute();
  const currentHash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const hash = maybeRestoreRestartHash(currentHash);
  if (!hash || hash === "/" || hash === "/new") return defaultShellRoute();

  const [path, query = ""] = hash.split("?", 2);
  const params = new URLSearchParams(query);
  const rawSettingsSection = params.get("section");
  const settingsSection = isSettingsSectionKey(rawSettingsSection)
    ? rawSettingsSection
    : "overview";
  const activeKey = params.get("chat")?.trim() || null;

  if (path === "/settings") {
    return {
      view: shellViewForSettingsSection(settingsSection),
      activeKey,
      settingsSection,
    };
  }
  if (path === "/apps") {
    return { view: "apps", activeKey, settingsSection: "apps" };
  }
  if (path === "/automations") {
    return { view: "automations", activeKey, settingsSection: "automations" };
  }
  if (path === "/skills") {
    return { view: "skills", activeKey, settingsSection: "skills" };
  }
  if (path.startsWith("/temporary/")) {
    const encoded = path.slice("/temporary/".length);
    try {
      const chatId = decodeURIComponent(encoded).trim();
      return chatId
        ? {
            view: "chat",
            activeKey: `websocket:${chatId}`,
            settingsSection: "overview",
            temporary: true,
          }
        : defaultShellRoute();
    } catch {
      return defaultShellRoute();
    }
  }
  if (path.startsWith("/chat/")) {
    const encoded = path.slice("/chat/".length);
    try {
      const key = decodeURIComponent(encoded).trim();
      return key
        ? { view: "chat", activeKey: key, settingsSection: "overview" }
        : defaultShellRoute();
    } catch {
      return defaultShellRoute();
    }
  }
  return defaultShellRoute();
}

function shellRouteHash(route: ShellRoute): string {
  if (route.view === "chat") {
    if (route.temporary && route.activeKey?.startsWith("websocket:")) {
      const chatId = route.activeKey.slice("websocket:".length);
      return `#/temporary/${encodeURIComponent(chatId)}`;
    }
    return route.activeKey
      ? `#/chat/${encodeURIComponent(route.activeKey)}`
      : "#/new";
  }
  const params = new URLSearchParams();
  if (route.activeKey) params.set("chat", route.activeKey);
  if (route.view === "settings" && route.settingsSection !== "overview") {
    params.set("section", route.settingsSection);
  }
  const query = params.toString();
  return `#/${route.view}${query ? `?${query}` : ""}`;
}

function writeShellRoute(route: ShellRoute, replace = false): void {
  if (typeof window === "undefined") return;
  const nextHash = shellRouteHash(route);
  if (window.location.hash === nextHash) return;
  if (replace) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
    return;
  }
  window.location.hash = nextHash;
}

function bootstrapTokenExpiresAt(expiresInSeconds: number): number {
  return Date.now() + Math.max(0, expiresInSeconds) * 1000;
}

function tokenRefreshDelayMs(expiresAt: number): number {
  const remaining = Math.max(0, expiresAt - Date.now());
  const margin = Math.min(
    TOKEN_REFRESH_MARGIN_MS,
    Math.max(1_000, remaining / 2),
  );
  return Math.max(TOKEN_REFRESH_MIN_DELAY_MS, remaining - margin);
}

function AuthForm({
  failed,
  onSecret,
}: {
  failed: boolean;
  onSecret: (secret: string) => void;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<"required" | "invalid" | null>(
    failed ? "invalid" : null,
  );
  const errorMessage = validationError ? t(`app.auth.${validationError}`) : null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) {
      setValidationError("required");
      inputRef.current?.focus();
      return;
    }
    setSubmitting(true);
    onSecret(secret);
  };

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4"
      >
        <div className="space-y-2">
          <h1 className="text-sm font-medium text-foreground">
            <label htmlFor="webui-access-password">{t("app.auth.label")}</label>
          </h1>
          <div className="relative">
            <Input
              ref={inputRef}
              id="webui-access-password"
              name="webui-access-password"
              type={passwordVisible ? "text" : "password"}
              autoComplete="current-password"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setValidationError(null);
              }}
              disabled={submitting}
              aria-invalid={validationError ? true : undefined}
              aria-describedby={validationError ? "webui-auth-error" : undefined}
              className="pr-10"
              autoFocus
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={submitting}
              aria-label={t(
                passwordVisible ? "app.auth.hidePassword" : "app.auth.showPassword",
              )}
              aria-controls="webui-access-password"
              onClick={() => setPasswordVisible((visible) => !visible)}
              className="absolute right-1 top-1/2 h-8 w-8 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              {passwordVisible ? (
                <EyeOff className="h-4 w-4" strokeWidth={1.75} aria-hidden />
              ) : (
                <Eye className="h-4 w-4" strokeWidth={1.75} aria-hidden />
              )}
            </Button>
          </div>
          {errorMessage ? (
            <p id="webui-auth-error" role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
        <Button
          type="submit"
          className="w-full"
          disabled={submitting}
        >
          {t("app.auth.submit")}
        </Button>
      </form>
    </div>
  );
}

function readSidebarOpen(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

function readSessionUpdateChatIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw =
      window.localStorage.getItem(SESSION_UPDATES_STORAGE_KEY)
      ?? window.localStorage.getItem(LEGACY_COMPLETED_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

function writeSessionUpdateChatIds(chatIds: Set<string>): void {
  try {
    window.localStorage.setItem(
      SESSION_UPDATES_STORAGE_KEY,
      JSON.stringify(Array.from(chatIds)),
    );
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

function normalizeWorkspaceScope(scope: WorkspaceScopePayload): WorkspaceScopePayload {
  const accessMode = scope.access_mode === "restricted" ? "restricted" : "full";
  return {
    ...scope,
    project_name: scope.project_name ?? projectNameFromPath(scope.project_path),
    access_mode: accessMode,
    restrict_to_workspace: accessMode === "restricted",
  };
}

function isBootstrapAuthRequired(error: unknown): boolean {
  if (error instanceof BootstrapAuthRequiredError) return true;
  const msg = error instanceof Error ? error.message : String(error);
  return msg.includes("HTTP 401") || msg.includes("HTTP 403");
}

function HostChrome({
  onToggleSidebar,
  onSidebarPreviewEnter,
  onSidebarPreviewLeave,
  sidebarOpen = true,
  rightAction,
}: {
  onToggleSidebar?: () => void;
  onSidebarPreviewEnter?: () => void;
  onSidebarPreviewLeave?: () => void;
  sidebarOpen?: boolean;
  rightAction?: ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <header className="host-drag-region pointer-events-none absolute inset-x-0 top-0 z-40 h-11 bg-transparent text-foreground/90">
      {onToggleSidebar ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          data-testid="host-sidebar-toggle"
          onClick={onToggleSidebar}
          onFocus={!sidebarOpen ? onSidebarPreviewEnter : undefined}
          onBlur={!sidebarOpen ? onSidebarPreviewLeave : undefined}
          onMouseEnter={!sidebarOpen ? onSidebarPreviewEnter : undefined}
          onMouseLeave={!sidebarOpen ? onSidebarPreviewLeave : undefined}
          className="host-no-drag pointer-events-auto absolute left-[88px] top-[8px] h-7 w-7 rounded-lg bg-transparent text-muted-foreground/85 shadow-none hover:bg-transparent hover:text-foreground"
        >
          <PanelLeft className="h-[15px] w-[15px]" strokeWidth={1.75} />
        </Button>
      ) : null}
      {rightAction ? (
        <div className="host-no-drag pointer-events-auto absolute right-3 top-2">
          {rightAction}
        </div>
      ) : null}
    </header>
  );
}

function PairingCodePopup({
  requests,
  total,
  busyCode,
  error,
  onApprove,
  onDismiss,
}: {
  requests: PairingRequestInfo[];
  total: number;
  busyCode: string | null;
  error: string | null;
  onApprove: (code: string) => void;
  onDismiss: (code: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const normalizedCode = normalizePairingCode(value);
  const matchedRequest = useMemo(
    () => requests.find((request) => request.code === normalizedCode) ?? null,
    [normalizedCode, requests],
  );
  const firstRequest = requests[0] ?? null;
  const displayRequest = matchedRequest ?? firstRequest;
  const expires = formatPairingExpiry(firstRequest?.expires_in_seconds);
  const isCompleteCode = normalizedCode.length === 9;
  const showNoMatch = isCompleteCode && !matchedRequest && !busyCode;

  useEffect(() => {
    if (!matchedRequest || busyCode) return;
    onApprove(matchedRequest.code);
  }, [busyCode, matchedRequest, onApprove]);

  useEffect(() => {
    if (!requests.length) setValue("");
  }, [requests.length]);

  if (!firstRequest) return null;

  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label={t("app.pairing.title", { defaultValue: "Pair a chat user" })}
      className={cn(
        "fixed right-4 top-[calc(0.75rem+env(safe-area-inset-top))] z-[70]",
        "w-[min(calc(100vw-2rem),24rem)] rounded-[24px]",
        floatingSurfaceElevationClassName,
        "p-4",
        "animate-in fade-in-0 slide-in-from-top-2 duration-200",
      )}
    >
      <div className="flex items-start gap-3">
        <PairingChannelBadge channel={displayRequest.channel} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[15px] font-semibold tracking-[-0.01em]">
                {t("app.pairing.title", { defaultValue: "Pair a chat user" })}
              </p>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                {t("app.pairing.description", {
                  defaultValue: "Enter the pairing code shown in the chat.",
                })}
              </p>
            </div>
            <button
              type="button"
              aria-label={t("common.close", { defaultValue: "Close" })}
              onClick={() => onDismiss(firstRequest.code)}
              className="rounded-full p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>

          <label className="mt-4 block text-[12.5px] font-medium text-foreground">
            {t("app.pairing.code", { defaultValue: "Pairing code" })}
          </label>
          <PairingCodeSlots
            value={value}
            disabled={Boolean(busyCode)}
            matched={Boolean(matchedRequest)}
            invalid={showNoMatch}
            ariaLabel={t("app.pairing.code", { defaultValue: "Pairing code" })}
            onChange={(next) => setValue(formatPairingCodeInput(next))}
          />

          <div className="mt-3 flex items-center justify-between gap-3 text-[12.5px] text-muted-foreground">
            <span>
              {matchedRequest
                ? t("app.pairing.matched", {
                    defaultValue: "Matched {{channel}}. Connecting...",
                    channel: channelLabel(matchedRequest.channel),
                  })
                : t("app.pairing.expiresInline", {
                    defaultValue: "Code expires {{expires}}.",
                    expires,
                  })}
            </span>
            {total > 1 ? (
              <span className="shrink-0">
                {t("app.pairing.queueCount", {
                  defaultValue: "{{count}} pending",
                  count: total,
                })}
              </span>
            ) : null}
          </div>

          {showNoMatch ? (
            <p className="mt-2 text-[12px] leading-5 text-destructive">
              {t("app.pairing.noMatch", {
                defaultValue: "No pending request matches this code.",
              })}
            </p>
          ) : null}

          {error ? (
            <p className="mt-2 text-[12px] leading-5 text-destructive">{error}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PairingChannelBadge({ channel }: { channel: string }) {
  const presentation = pairingChannelPresentation(channel);
  const initials = presentation.initials;
  const color = presentation.color;
  const logoUrls = useMemo(
    () => logoFallbackUrls(presentation?.logoUrl),
    [presentation?.logoUrl],
  );
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(logoUrls);

  return (
    <div
      className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-2xl border bg-background shadow-sm"
      style={{
        borderColor: `${color}30`,
        boxShadow: `inset 0 0 0 1px ${color}14, 0 1px 2px rgba(15,23,42,0.06)`,
      }}
      aria-hidden
    >
      {logoUrl ? (
        <img
          src={logoUrl}
          alt=""
          decoding="async"
          loading="lazy"
          className="h-6 w-6 object-contain"
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      ) : presentation ? (
        <span className="text-[11px] font-bold tracking-[-0.02em]" style={{ color }}>
          {initials}
        </span>
      ) : (
        <ShieldCheck className="h-5 w-5" style={{ color }} />
      )}
    </div>
  );
}

function PairingCodeSlots({
  value,
  disabled,
  matched,
  invalid,
  ariaLabel,
  onChange,
}: {
  value: string;
  disabled: boolean;
  matched: boolean;
  invalid: boolean;
  ariaLabel: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);
  const compact = compactPairingCode(value);
  const activeIndex = Math.min(compact.length, 7);
  const slots = Array.from({ length: 8 }, (_, index) => compact[index] ?? "");
  const renderSlot = (char: string, index: number) => {
    const highlighted = focused && index === activeIndex && !matched && !invalid;
    return (
      <div
        key={index}
        className={cn(
          "grid h-10 w-7 place-items-center rounded-xl border",
          "bg-background/80 font-mono text-[16px] font-semibold uppercase",
          "text-foreground shadow-[0_1px_1px_rgba(15,23,42,0.04)] transition",
          matched
            ? "border-emerald-500/45 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : invalid
              ? "border-destructive/55 bg-destructive/5 text-destructive"
              : highlighted
                ? "border-foreground/30 bg-background text-foreground"
                : char
                  ? "border-border/80 bg-background text-foreground"
                  : "border-border/55 bg-muted/35 text-muted-foreground",
        )}
      >
        {char || " "}
      </div>
    );
  };

  return (
    <div
      className={cn(
        "relative mt-2 rounded-2xl border border-transparent p-1",
        "transition duration-150",
        focused && !disabled ? "border-ring/20 bg-muted/35" : "bg-transparent",
      )}
      onClick={() => inputRef.current?.focus()}
    >
      <input
        ref={inputRef}
        value={value}
        aria-label={ariaLabel}
        inputMode="text"
        autoCapitalize="characters"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        maxLength={9}
        disabled={disabled}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => onChange(event.target.value)}
        className="absolute inset-0 z-10 h-full w-full cursor-text opacity-0 disabled:cursor-default"
      />
      <div className="pointer-events-none flex items-center gap-1.5">
        {slots.slice(0, 4).map((char, index) => renderSlot(char, index))}
        <div className="mx-0.5 h-px w-2.5 rounded-full bg-muted-foreground/35" />
        {slots.slice(4).map((char, index) => renderSlot(char, index + 4))}
      </div>
    </div>
  );
}

function compactPairingCode(raw: string): string {
  return raw.replace(/[^a-zA-Z0-9]/g, "").slice(0, 8).toUpperCase();
}

function formatPairingCodeInput(raw: string): string {
  const compact = compactPairingCode(raw);
  if (compact.length <= 4) return compact;
  return `${compact.slice(0, 4)}-${compact.slice(4)}`;
}

function normalizePairingCode(raw: string): string {
  return formatPairingCodeInput(raw);
}

function pairingChannelKey(channel: string): string {
  const raw = channel.trim().toLowerCase();
  if (!raw) return "";
  return raw.split(/[.:]/)[0] ?? raw;
}

function channelLabel(channel: string): string {
  return pairingChannelPresentation(channel).label;
}

function pairingChannelPresentation(channel: string) {
  const key = pairingChannelKey(channel);
  const plugin = channelUiPresentation(key);
  return {
    label: plugin?.displayName ?? channel,
    initials: plugin?.initials ?? channel.slice(0, 2).toUpperCase(),
    color: plugin?.color ?? "#10B981",
    logoUrl: plugin?.logoUrl,
  };
}

function formatPairingExpiry(seconds: number | null | undefined): string {
  if (seconds == null) return "soon";
  if (seconds <= 0) return "expired";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.ceil(seconds / 60)} min`;
}

export default function App() {
  const { t } = useTranslation();
  const [state, setState] = useState<BootState>({ status: "loading" });
  const bootstrapSecretRef = useRef("");

  const refreshReadyClient = useCallback(
    async (client: NanobotClient, fallbackSurface: RuntimeSurface) => {
      const boot = await fetchBootstrap("", bootstrapSecretRef.current);
      const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
      const runtimeSurface = boot.runtime_surface
        ? toRuntimeSurface(boot.runtime_surface)
        : fallbackSurface;
      const runtimeHost = createRuntimeHost(runtimeSurface, boot.runtime_capabilities);
      const tokenExpiresAt = boot.expires_in
        ? bootstrapTokenExpiresAt(boot.expires_in)
        : null;
      if (runtimeHost.socketFactory) {
        client.updateUrl(url, runtimeHost.socketFactory);
      } else {
        client.updateUrl(url);
      }
      client.updateMaxFrameBytes(boot.limits?.transport.max_frame_bytes);
      setState((current) =>
        current.status === "ready" && current.client === client
          ? {
              ...current,
              token: boot.api_token ?? "",
              tokenExpiresAt,
              modelName: boot.model_name ?? current.modelName,
              ingressLimits: boot.limits ?? current.ingressLimits,
              runtimeSurface,
            }
          : current,
      );
      return { token: boot.api_token ?? "", url };
    },
    [],
  );

  const bootstrapWithSecret = useCallback(
    (secret: string) => {
      let cancelled = false;
      (async () => {
        setState({ status: "loading" });
        try {
          const boot = await fetchBootstrap("", secret);
          if (cancelled) return;
          if (secret) saveSecret(secret);
          const url = deriveWsUrl(boot.ws_path, boot.token, boot.ws_url);
          const runtimeSurface = toRuntimeSurface(boot.runtime_surface);
          const runtimeHost = createRuntimeHost(runtimeSurface, boot.runtime_capabilities);
          const client = new NanobotClient({
            url,
            maxFrameBytes: boot.limits?.transport.max_frame_bytes,
            socketFactory: runtimeHost.socketFactory,
            onReauth: async () => {
              try {
                const refreshed = await refreshReadyClient(client, runtimeSurface);
                return refreshed.url;
              } catch {
                return null;
              }
            },
          });
          bootstrapSecretRef.current = secret;
          client.connect();
          setState({
            status: "ready",
            client,
            token: boot.api_token ?? "",
            tokenExpiresAt: boot.expires_in
              ? bootstrapTokenExpiresAt(boot.expires_in)
              : null,
            modelName: boot.model_name ?? null,
            ingressLimits: boot.limits ?? null,
            runtimeSurface,
          });
        } catch (e) {
          if (cancelled) return;
          if (isBootstrapAuthRequired(e)) {
            setState({ status: "auth", failed: !!secret });
          } else {
            setState({
              status: "error",
              message: e instanceof Error ? e.message : String(e),
            });
          }
        }
      })();
      return () => {
        cancelled = true;
      };
    },
    [refreshReadyClient],
  );

  useEffect(() => {
    if (state.status !== "ready" || state.tokenExpiresAt === null) return;
    const client = state.client;
    const timer = window.setTimeout(async () => {
      try {
        await refreshReadyClient(client, state.runtimeSurface);
      } catch (e) {
        if (isBootstrapAuthRequired(e)) {
          setState({ status: "auth", failed: !!bootstrapSecretRef.current });
        }
      }
    }, tokenRefreshDelayMs(state.tokenExpiresAt));
    return () => window.clearTimeout(timer);
  }, [refreshReadyClient, state]);

  useEffect(() => {
    const saved = consumeUrlBootstrapSecret() || loadSavedSecret();
    return bootstrapWithSecret(saved);
  }, [bootstrapWithSecret]);

  if (state.status === "loading") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 animate-in fade-in-0 duration-300">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-foreground/60" />
            </span>
            {t("app.loading.connecting")}
          </div>
        </div>
      </div>
    );
  }
  if (state.status === "auth") {
    return (
      <AuthForm
        failed={!!state.failed}
        onSecret={(s) => bootstrapWithSecret(s)}
      />
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center px-4 text-center">
        <div className="flex max-w-md flex-col items-center gap-3">
          <p className="text-lg font-semibold">{t("app.error.title")}</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <p className="text-xs text-muted-foreground">
            {t("app.error.gatewayHint")}
          </p>
        </div>
      </div>
    );
  }

  const handleModelNameChange = (modelName: string | null) => {
    setState((current) =>
      current.status === "ready" ? { ...current, modelName } : current,
    );
  };

  const handleLogout = () => {
    if (state.status === "ready") {
      state.client.close();
    }
    clearSavedSecret();
    setState({ status: "auth" });
  };

  const handleNativeEngineRestart = async (): Promise<string> => {
    const runtimeHost = createRuntimeHost(state.runtimeSurface);
    if (!runtimeHost.restartEngine) {
      throw new Error("native engine restart is unavailable");
    }
    rememberRestartRoute();
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    try {
      await runtimeHost.restartEngine();
      const refreshed = await refreshReadyClient(state.client, state.runtimeSurface);
      return refreshed.token;
    } finally {
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
        window.localStorage.removeItem(RESTART_ROUTE_KEY);
      } catch {
        // ignore storage errors
      }
    }
  };

  return (
    <ClientProvider
      client={state.client}
      token={state.token}
      modelName={state.modelName}
      ingressLimits={state.ingressLimits}
    >
      <Shell
        runtimeSurface={state.runtimeSurface}
        onModelNameChange={handleModelNameChange}
        onLogout={handleLogout}
        onNativeEngineRestart={handleNativeEngineRestart}
      />
    </ClientProvider>
  );
}

function Shell({
  runtimeSurface,
  onModelNameChange,
  onLogout,
  onNativeEngineRestart,
}: {
  runtimeSurface: RuntimeSurface;
  onModelNameChange: (modelName: string | null) => void;
  onLogout: () => void;
  onNativeEngineRestart: () => Promise<string>;
}) {
  const { t, i18n } = useTranslation();
  const { client, getToken } = useClient();
  const { theme, toggle } = useTheme();
  const {
    sessions,
    loading,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  } = useSessions();
  const {
    state: sidebarState,
    loading: sidebarStateLoading,
    update: updateSidebarState,
  } =
    useSidebarState(sessions, !loading);
  const initialRouteRef = useRef<ShellRoute | null>(null);
  if (!initialRouteRef.current) initialRouteRef.current = readShellRoute();
  const [activeKey, setActiveKey] = useState<string | null>(
    initialRouteRef.current.activeKey,
  );
  const [view, setView] = useState<ShellView>(initialRouteRef.current.view);
  const [temporarySessions, setTemporarySessions] = useState<Record<string, ChatSummary>>({});
  const [temporaryChatEnabled, setTemporaryChatEnabled] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] =
    useState<SettingsSectionKey>(initialRouteRef.current.settingsSection);
  const [hostSidebarOpen, setHostSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [hostSidebarPreviewOpen, setHostSidebarPreviewOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const mobileWorkbench = useMediaQuery("(max-width: 767px)");
  const workbenchState = sidebarState.workbench;
  const updateWorkbenchState = useCallback((
    updater: (current: WorkbenchState) => WorkbenchState,
  ) => {
    void updateSidebarState((current) => {
      const next = updater(current.workbench);
      return next === current.workbench ? current : { ...current, workbench: next };
    });
  }, [updateSidebarState]);
  const lastActivePaneByTabRef = useRef(new Map<string, string>());
  const [creatingPane, setCreatingPane] = useState(false);
  const topicSessions = sessions;
  const [pendingDelete, setPendingDelete] = useState<{
    items: SidebarDeleteItem[];
    automations?: SessionAutomationJob[];
  } | null>(null);
  const [pendingRename, setPendingRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [pendingTabRename, setPendingTabRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const [pendingProjectRename, setPendingProjectRename] = useState<{
    key: string;
    label: string;
  } | null>(null);
  const restartSawDisconnectRef = useRef(false);
  const [restartToast, setRestartToast] = useState<string | null>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [pairingRequests, setPairingRequests] = useState<PairingRequestInfo[]>([]);
  const [pairingBusyCode, setPairingBusyCode] = useState<string | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const pairingRefreshRef = useRef<Promise<number> | null>(null);
  const [snoozedPairingCodes, setSnoozedPairingCodes] = useState<Map<string, number>>(
    () => new Map(),
  );
  const [runningChatIds, setRunningChatIds] = useState<Set<string>>(() => new Set());
  const [updatedChatIds, setUpdatedChatIds] = useState<Set<string>>(readSessionUpdateChatIds);
  const [workspaces, setWorkspaces] = useState<WorkspacesPayload | null>(null);
  const skills = useSkills(getToken);
  const pageVisible = usePageVisibility();
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsPayload | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [draftWorkspaceScope, setDraftWorkspaceScope] =
    useState<WorkspaceScopePayload | null>(null);
  const [workspaceOverrides, setWorkspaceOverrides] =
    useState<Record<string, WorkspaceScopePayload>>({});
  const runningChatIdsRef = useRef<Set<string>>(new Set());
  const activeChatIdRef = useRef<string | null>(null);
  const pendingCreatedSessionKeyRef = useRef<string | null>(null);
  const temporarySessionsRef = useRef<Record<string, ChatSummary>>({});
  const hostSidebarPreviewCloseTimerRef = useRef<number | null>(null);
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const showHostChrome = effectiveRuntimeSurface === "native";
  const showMainSidebar = view !== "settings";
  const activeTemporarySession = activeKey ? temporarySessions[activeKey] ?? null : null;
  const temporaryChatId = activeTemporarySession?.chatId ?? null;
  const temporaryChatActive = view === "chat" && temporaryChatId !== null;
  const temporaryChatRequested = temporaryChatActive || temporaryChatEnabled;
  const temporarySessionList = useMemo(
    () => Object.values(temporarySessions).sort((a, b) => (
      Date.parse(b.createdAt ?? "") - Date.parse(a.createdAt ?? "")
    )),
    [temporarySessions],
  );
  const temporaryChatIds = useMemo(
    () => temporarySessionList.map((session) => session.chatId),
    [temporarySessionList],
  );

  const navigate = useCallback(
    (route: ShellRoute, options?: { replace?: boolean }) => {
      setActiveKey(route.activeKey);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      writeShellRoute(route, options?.replace);
    },
    [],
  );

  useEffect(() => {
    const applyRoute = () => {
      const route = readShellRoute();
      setActiveKey(route.activeKey);
      setView(route.view);
      setSettingsInitialSection(route.settingsSection);
      setWorkspaceError(null);
      if (route.view === "chat" && !route.activeKey) {
        setDraftWorkspaceScope(null);
      }
    };
    window.addEventListener("hashchange", applyRoute);
    return () => window.removeEventListener("hashchange", applyRoute);
  }, []);

  useEffect(() => {
    temporarySessionsRef.current = temporarySessions;
  }, [temporarySessions]);

  useEffect(() => {
    if (view === "chat" && !activeKey) return;
    setTemporaryChatEnabled(false);
  }, [activeKey, view]);

  useEffect(() => () => {
    for (const session of Object.values(temporarySessionsRef.current)) {
      client.discardTemporaryChat(session.chatId);
    }
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    fetchSettings(getToken())
      .then((payload) => {
        if (!cancelled) setSettingsSnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) setSettingsSnapshot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        SIDEBAR_STORAGE_KEY,
        hostSidebarOpen ? "1" : "0",
      );
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }, [hostSidebarOpen]);

  useEffect(() => {
    writeSessionUpdateChatIds(updatedChatIds);
  }, [updatedChatIds]);

  const refreshPairingRequests = useCallback((): Promise<number> => {
    if (pairingRefreshRef.current) return pairingRefreshRef.current;

    const request = (async () => {
      try {
        const payload = await fetchPairingRequests(getToken());
        const requests = Array.isArray(payload.requests) ? payload.requests : [];
        setPairingRequests(requests);
        setSnoozedPairingCodes((current) => {
          if (current.size === 0) return current;
          const activeCodes = new Set(requests.map((request) => request.code));
          const now = Date.now();
          const next = new Map(
            Array.from(current).filter(
              ([code, snoozedUntil]) => activeCodes.has(code) && snoozedUntil > now,
            ),
          );
          return next.size === current.size ? current : next;
        });
        return requests.length;
      } catch {
        // Pairing is an opportunistic WebUI affordance. The slash command path
        // remains available if this polling request fails.
        return 0;
      }
    })();
    const clearRequest = () => {
      if (pairingRefreshRef.current === request) pairingRefreshRef.current = null;
    };
    pairingRefreshRef.current = request;
    void request.then(clearRequest, clearRequest);
    return request;
  }, [getToken]);

  useEffect(() => {
    if (!pageVisible) return undefined;

    let disposed = false;
    let timer: number | null = null;
    const poll = async () => {
      const requestCount = await refreshPairingRequests();
      if (disposed) return;
      timer = window.setTimeout(
        () => void poll(),
        requestCount > 0 ? PAIRING_POLL_INTERVAL_MS : PAIRING_IDLE_POLL_INTERVAL_MS,
      );
    };
    void poll();
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [pageVisible, refreshPairingRequests]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    if (temporarySessions[activeKey]) return temporarySessions[activeKey];
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey, temporarySessions]);
  const activeTabMatch = useMemo(() => (
    activeKey && !temporarySessions[activeKey]
      ? workbenchTabForPane(workbenchState, activeKey)
      : null
  ), [activeKey, temporarySessions, workbenchState]);
  const activeTabKey = activeTabMatch?.tabKey ?? null;
  const activeTabState = activeTabMatch?.tab ?? null;
  const activePaneSession = activeSession;
  useEffect(() => {
    if (!activeTabKey || !activeKey || !activeTabState?.paneKeys.includes(activeKey)) return;
    lastActivePaneByTabRef.current.set(activeTabKey, activeKey);
  }, [activeKey, activeTabKey, activeTabState]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const updatedChatIdList = useMemo(() => Array.from(updatedChatIds), [updatedChatIds]);
  const activeChatId = activePaneSession?.chatId ?? null;
  useEffect(() => {
    activeChatIdRef.current = activeChatId;
    if (!activeChatId) return;
    setUpdatedChatIds((current) => {
      if (!current.has(activeChatId)) return current;
      const next = new Set(current);
      next.delete(activeChatId);
      return next;
    });
  }, [activeChatId]);
  const activeWorkspaceScope = useMemo<WorkspaceScopePayload | null>(() => {
    if (temporaryChatRequested) {
      return workspaces?.default_scope
        ? normalizeWorkspaceScope(scopeWithAccessMode(workspaces.default_scope, "restricted"))
        : null;
    }
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activePaneSession?.workspaceScope) {
      return activePaneSession.workspaceScope;
    }
    return draftWorkspaceScope ?? workspaces?.default_scope ?? null;
  }, [
    activeChatId,
    activePaneSession?.workspaceScope,
    draftWorkspaceScope,
    temporaryChatRequested,
    workspaceOverrides,
    workspaces?.default_scope,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(getToken());
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [getToken]);

  useEffect(() => {
    void refreshWorkspaces();
  }, [refreshWorkspaces]);

  useEffect(() => {
    if (loading) return;
    const knownChatIds = new Set(sessions.map((session) => session.chatId));
    setUpdatedChatIds((current) => {
      const next = new Set(
        Array.from(current).filter((chatId) => knownChatIds.has(chatId)),
      );
      return next.size === current.size ? current : next;
    });
    setWorkspaceOverrides((current) => {
      const entries = Object.entries(current).filter(([chatId]) => knownChatIds.has(chatId));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [loading, sessions]);

  useEffect(() => {
    if (loading || sidebarStateLoading) return;
    const validKeys = new Set(sessions.map((session) => session.key));
    updateWorkbenchState((current) => {
      return reconcileWorkbench(current, validKeys);
    });
  }, [
    loading,
    sidebarStateLoading,
    sessions,
    updateWorkbenchState,
  ]);

  useEffect(() => {
    if (loading) return;
    const pendingCreatedKey = pendingCreatedSessionKeyRef.current;
    if (pendingCreatedKey && sessions.some((session) => session.key === pendingCreatedKey)) {
      pendingCreatedSessionKeyRef.current = null;
    }
    if (!activeKey) return;
    const currentRoute = readShellRoute();
    if (currentRoute.temporary) {
      if (temporarySessions[activeKey]) return;
      navigate(defaultShellRoute(), { replace: true });
      return;
    }
    if (sessions.some((session) => session.key === activeKey)) return;
    // WebKit can commit the route before useSessions' optimistic insert.
    // Keep that just-created destination valid until the session list catches up.
    if (pendingCreatedKey === activeKey) return;
    navigate(
      currentRoute.view === "chat"
        ? defaultShellRoute()
        : {
            ...currentRoute,
            activeKey: null,
          },
      { replace: true },
    );
  }, [activeKey, loading, navigate, sessions, temporarySessions]);

  useEffect(() => {
    return client.onSessionUpdate((chatId, scope, workspaceScope) => {
      if (scope === "thread") {
        setUpdatedChatIds((current) => {
          const next = new Set(current);
          if (activeChatIdRef.current === chatId) {
            next.delete(chatId);
          } else {
            next.add(chatId);
          }
          return next.size === current.size && next.has(chatId) === current.has(chatId)
            ? current
            : next;
        });
      }
      if (!workspaceScope) return;
      const next = normalizeWorkspaceScope(workspaceScope);
      setWorkspaceOverrides((current) => ({
        ...current,
        [chatId]: next,
      }));
      setDraftWorkspaceScope(next);
      setWorkspaceError(null);
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces]);

  useEffect(() => {
    return client.onError((error) => {
      if (error.kind !== "workspace_scope_rejected") return;
      if (error.chatId && error.chatId !== activeChatIdRef.current) return;
      setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      void refreshWorkspaces();
    });
  }, [client, refreshWorkspaces, t]);

  useEffect(() => {
    if (loading) return;
    const activeRunIds = sessions
      .filter((session) => typeof session.runStartedAt === "number")
      .map((session) => session.chatId);
    if (activeRunIds.length === 0) return;

    for (const chatId of activeRunIds) {
      client.attach(chatId);
    }
    setRunningChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (!next.has(chatId)) changed = true;
        next.add(chatId);
      }
      if (!changed) return current;
      runningChatIdsRef.current = next;
      return next;
    });
    setUpdatedChatIds((current) => {
      let changed = false;
      const next = new Set(current);
      for (const chatId of activeRunIds) {
        if (next.delete(chatId)) changed = true;
      }
      return changed ? next : current;
    });
  }, [client, loading, sessions]);

  const clearHostSidebarPreviewCloseTimer = useCallback(() => {
    if (hostSidebarPreviewCloseTimerRef.current === null) return;
    window.clearTimeout(hostSidebarPreviewCloseTimerRef.current);
    hostSidebarPreviewCloseTimerRef.current = null;
  }, []);

  const closeHostSidebarPreview = useCallback(() => {
    clearHostSidebarPreviewCloseTimer();
    setHostSidebarPreviewOpen(false);
  }, [clearHostSidebarPreviewCloseTimer]);

  const openHostSidebarPreview = useCallback(() => {
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) return;
    clearHostSidebarPreviewCloseTimer();
    setHostSidebarPreviewOpen(true);
  }, [
    clearHostSidebarPreviewCloseTimer,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  const scheduleHostSidebarPreviewClose = useCallback(() => {
    clearHostSidebarPreviewCloseTimer();
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) {
      setHostSidebarPreviewOpen(false);
      return;
    }
    hostSidebarPreviewCloseTimerRef.current = window.setTimeout(() => {
      setHostSidebarPreviewOpen(false);
      hostSidebarPreviewCloseTimerRef.current = null;
    }, 160);
  }, [
    clearHostSidebarPreviewCloseTimer,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  useEffect(() => {
    return () => clearHostSidebarPreviewCloseTimer();
  }, [clearHostSidebarPreviewCloseTimer]);

  useEffect(() => {
    if (!showHostChrome || !showMainSidebar || hostSidebarOpen) {
      closeHostSidebarPreview();
    }
  }, [
    closeHostSidebarPreview,
    hostSidebarOpen,
    showHostChrome,
    showMainSidebar,
  ]);

  const closeHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen(false);
  }, [closeHostSidebarPreview]);

  const openHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen(true);
  }, [closeHostSidebarPreview]);

  const toggleHostSidebar = useCallback(() => {
    closeHostSidebarPreview();
    setHostSidebarOpen((v) => !v);
  }, [closeHostSidebarPreview]);

  const closeMobileSidebar = useCallback(() => {
    setMobileSidebarOpen(false);
  }, []);

  const toggleSidebar = useCallback(() => {
    const isNativeHost =
      typeof window !== "undefined" &&
      window.matchMedia("(min-width: 1024px)").matches;
    if (isNativeHost) {
      closeHostSidebarPreview();
      setHostSidebarOpen((v) => !v);
    } else {
      setMobileSidebarOpen((v) => !v);
    }
  }, [closeHostSidebarPreview]);

  const applyWorkspaceScope = useCallback(
    (scope: WorkspaceScopePayload) => {
      const next = normalizeWorkspaceScope(scope);
      setWorkspaceError(null);
      if (activeChatId) {
        if (temporaryChatActive) {
          setTemporarySessions((current) => {
            if (!activeKey || !current[activeKey]) return current;
            return {
              ...current,
              [activeKey]: { ...current[activeKey], workspaceScope: next },
            };
          });
        } else if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, activeKey, client, temporaryChatActive],
  );

  const onCreateChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      const chatId = await createChat(scope);
      const key = `websocket:${chatId}`;
      pendingCreatedSessionKeyRef.current = key;
      navigate({
        view: "chat",
        activeKey: key,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
      return chatId;
    } catch (e) {
      console.error("Failed to create chat", e);
      if (e instanceof Error && e.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      }
      return null;
    }
  }, [activeWorkspaceScope, createChat, navigate, t]);

  const onCreateTemporaryChat = useCallback(
    async (
      workspaceScope?: WorkspaceScopePayload | null,
      initialMessage?: string,
    ) => {
      try {
        const chatId = await client.newTemporaryChat();
        const session = createTemporaryChatSession(chatId);
        const restrictedScope = workspaceScope
          ? normalizeWorkspaceScope(scopeWithAccessMode(workspaceScope, "restricted"))
          : null;
        const nextSession: ChatSummary = {
          ...session,
          preview: initialMessage ?? "",
          ...(restrictedScope ? { workspaceScope: restrictedScope } : {}),
        };
        setTemporarySessions((current) => ({
          ...current,
          [nextSession.key]: nextSession,
        }));
        setTemporaryChatEnabled(false);
        setWorkspaceError(null);
        setSessionSearchOpen(false);
        navigate({
          view: "chat",
          activeKey: nextSession.key,
          settingsSection: "overview",
          temporary: true,
        });
        setMobileSidebarOpen(false);
        return nextSession.chatId;
      } catch (error) {
        console.error("Failed to create temporary chat", error);
        return null;
      }
    },
    [client, navigate],
  );

  const onForkChat = useCallback(async (
    sourceChatId: string,
    beforeUserIndex: number,
  ) => {
    try {
      const sourceSession = sessions.find((session) => session.chatId === sourceChatId);
      const sourceTitle = sourceSession
        ? displayTitle(sourceSession, sidebarState.title_overrides, t("chat.newChat"))
        : t("chat.newChat");
      const chatId = await forkChat(
        sourceChatId,
        beforeUserIndex,
        t("chat.forkTitle", { title: sourceTitle }),
      );
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
        settingsSection: "overview",
      });
      setMobileSidebarOpen(false);
      return chatId;
    } catch (e) {
      console.error("Failed to fork chat", e);
      return null;
    }
  }, [forkChat, navigate, sessions, sidebarState.title_overrides, t]);

  const onNewChat = useCallback(() => {
    navigate(defaultShellRoute());
    setTemporaryChatEnabled(false);
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    setSessionSearchOpen(false);
    setMobileSidebarOpen(false);
  }, [navigate]);

  const onTemporaryChatEnabledChange = useCallback((enabled: boolean) => {
    if (view !== "chat" || activeKey) return;
    setTemporaryChatEnabled(enabled);
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
  }, [activeKey, view]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
      setTemporaryChatEnabled(false);
      navigate(defaultShellRoute());
      setDraftWorkspaceScope(normalizeWorkspaceScope({
        project_path: trimmed,
        project_name: projectName || projectNameFromPath(trimmed),
        access_mode: base.access_mode,
        restrict_to_workspace: base.access_mode === "restricted",
      }));
      setWorkspaceError(null);
      setMobileSidebarOpen(false);
    },
    [activeWorkspaceScope, navigate, onNewChat, workspaces?.default_scope],
  );

  const onSelectChat = useCallback(
    (key: string) => {
      const selectedTemporary = temporarySessionsRef.current[key];
      const selected = selectedTemporary
        ?? sessions.find((session) => session.key === key);
      const selectedChatId = selected?.chatId;
      if (selectedChatId) {
        setUpdatedChatIds((current) => {
          if (!current.has(selectedChatId)) return current;
          const next = new Set(current);
          next.delete(selectedChatId);
          return next;
        });
      }
      if (selected?.workspaceScope) {
        setDraftWorkspaceScope(normalizeWorkspaceScope(selected.workspaceScope));
      } else {
        setDraftWorkspaceScope(null);
      }
      setWorkspaceError(null);
      navigate({
        view: "chat",
        activeKey: key,
        settingsSection: "overview",
        ...(selectedTemporary ? { temporary: true } : {}),
      });
      setMobileSidebarOpen(false);
    },
    [navigate, sessions],
  );

  const onCloseTemporaryChat = useCallback((key: string) => {
    const session = temporarySessionsRef.current[key];
    if (!session) return;
    const remaining = temporarySessionList.filter((item) => item.key !== key);
    const nextSessions = Object.fromEntries(remaining.map((item) => [item.key, item]));
    temporarySessionsRef.current = nextSessions;
    setTemporarySessions(nextSessions);
    client.discardTemporaryChat(session.chatId);
    if (activeKey === key) {
      if (remaining.length === 0) setDraftWorkspaceScope(null);
      setWorkspaceError(null);
      navigate({
        view: "chat",
        activeKey: remaining[0]?.key ?? null,
        settingsSection: "overview",
        ...(remaining[0] ? { temporary: true } : {}),
      }, { replace: true });
    }
    setMobileSidebarOpen(false);
  }, [activeKey, client, navigate, temporarySessionList]);

  const onTogglePin = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const pinned = new Set(current.pinned_keys);
        if (pinned.has(key)) {
          pinned.delete(key);
        } else {
          pinned.add(key);
        }
        return {
          ...current,
          pinned_keys: Array.from(pinned),
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRename = useCallback((key: string, label: string) => {
    setPendingRename({ key, label });
  }, []);

  const onConfirmRename = useCallback(
    (title: string) => {
      if (!pendingRename) return;
      const key = pendingRename.key;
      setPendingRename(null);
      void updateSidebarState((current) => {
        const titleOverrides = { ...current.title_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          titleOverrides[key] = cleaned;
        } else {
          delete titleOverrides[key];
        }
        return {
          ...current,
          title_overrides: titleOverrides,
        };
      });
    },
    [pendingRename, updateSidebarState],
  );

  const onRequestRenameTab = useCallback((key: string, label: string) => {
    setPendingTabRename({ key, label });
  }, []);

  const onConfirmTabRename = useCallback((title: string) => {
    if (!pendingTabRename) return;
    updateWorkbenchState((current) => (
      renameWorkbenchTab(current, pendingTabRename.key, title)
    ));
    setPendingTabRename(null);
  }, [pendingTabRename, updateWorkbenchState]);

  const onToggleGroup = useCallback(
    (groupId: string) => {
      void updateSidebarState((current) => {
        const collapsedGroups = { ...current.collapsed_groups };
        if (groupId === "workspace:chats" || groupId === "date:all") {
          if (collapsedGroups[groupId] === false) {
            delete collapsedGroups[groupId];
          } else {
            collapsedGroups[groupId] = false;
          }
          return {
            ...current,
            collapsed_groups: collapsedGroups,
          };
        }
        if (collapsedGroups[groupId]) {
          delete collapsedGroups[groupId];
        } else {
          collapsedGroups[groupId] = true;
        }
        return {
          ...current,
          collapsed_groups: collapsedGroups,
        };
      });
    },
    [updateSidebarState],
  );

  const onRequestRenameProject = useCallback((key: string, label: string) => {
    setPendingProjectRename({ key, label });
  }, []);

  const onConfirmProjectRename = useCallback(
    (title: string) => {
      if (!pendingProjectRename) return;
      const key = pendingProjectRename.key;
      setPendingProjectRename(null);
      void updateSidebarState((current) => {
        const projectNameOverrides = { ...current.project_name_overrides };
        const cleaned = title.trim();
        if (cleaned) {
          projectNameOverrides[key] = cleaned;
        } else {
          delete projectNameOverrides[key];
        }
        return {
          ...current,
          project_name_overrides: projectNameOverrides,
        };
      });
    },
    [pendingProjectRename, updateSidebarState],
  );

  const onToggleArchive = useCallback(
    (key: string) => {
      void updateSidebarState((current) => {
        const archived = new Set(current.archived_keys);
        const pinned = current.pinned_keys.filter((item) => item !== key);
        if (archived.has(key)) {
          archived.delete(key);
        } else {
          archived.add(key);
        }
        return {
          ...current,
          pinned_keys: pinned,
          archived_keys: Array.from(archived),
        };
      });
      if (activeKey === key && !sidebarState.archived_keys.includes(key)) {
        const archived = new Set([...sidebarState.archived_keys, key]);
        const next = topicSessions.find((session) => !archived.has(session.key));
        navigate({
          view: "chat",
          activeKey: next?.key ?? null,
          settingsSection: "overview",
        });
      }
    },
    [activeKey, navigate, sidebarState.archived_keys, topicSessions, updateSidebarState],
  );

  const onToggleArchived = useCallback(() => {
    void updateSidebarState((current) => ({
      ...current,
      view: {
        ...current.view,
        show_archived: !current.view.show_archived,
      },
    }));
  }, [updateSidebarState]);

  const onOpenSessionSearch = useCallback(() => {
    setMobileSidebarOpen(false);
    setSessionSearchOpen(true);
  }, []);

  const onAddPane = useCallback(async () => {
    const tabKey = activeTabKey;
    if (
      !tabKey
      || !activeKey
      || !activeSession
      || creatingPane
      || (activeTabState?.paneKeys.length ?? 0) >= MAX_WORKBENCH_PANES
      || temporarySessionsRef.current[activeKey]
    ) return;
    setMobileSidebarOpen(false);
    setSessionSearchOpen(false);
    setCreatingPane(true);
    try {
      const scope = activeWorkspaceScope;
      const chatId = await createChat(scope);
      const paneKey = `websocket:${chatId}`;
      pendingCreatedSessionKeyRef.current = paneKey;
      updateWorkbenchState((current) => addWorkbenchPane(current, activeKey, paneKey));
      navigate({
        view: "chat",
        activeKey: paneKey,
        settingsSection: "overview",
      });
      if (scope) {
        setWorkspaceOverrides((current) => ({
          ...current,
          [chatId]: normalizeWorkspaceScope(scope),
        }));
      }
    } catch (error) {
      console.error("Failed to create pane", error);
      if (error instanceof Error && error.message.startsWith("workspace_scope_rejected:")) {
        setWorkspaceError(t("errors.workspaceScopeRejected.body"));
      }
    } finally {
      setCreatingPane(false);
    }
  }, [
    activeKey,
    activeSession,
    activeTabKey,
    activeTabState,
    activeWorkspaceScope,
    createChat,
    creatingPane,
    navigate,
    t,
    updateWorkbenchState,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const commandShiftO =
        (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey;
      if (commandShiftO && event.key.toLowerCase() === "o") {
        event.preventDefault();
        onNewChat();
        return;
      }
      const plainCommandK =
        (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
      if (!plainCommandK) return;
      if (event.key.toLowerCase() !== "k") return;
      event.preventDefault();
      onOpenSessionSearch();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onNewChat, onOpenSessionSearch]);

  const onSelectSearchResult = useCallback(
    (key: string) => {
      setSessionSearchOpen(false);
      onSelectChat(key);
    },
    [onSelectChat],
  );

  const onOpenSettings = useCallback((section: SettingsSectionKey = "overview") => {
    setSessionSearchOpen(false);
    navigate({ view: "settings", activeKey, settingsSection: section });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onSettingsIntent = useCallback(() => {
    void loadSettingsView();
  }, []);

  const onOpenModelSettings = useCallback(() => {
    onOpenSettings("models");
  }, [onOpenSettings]);

  const onOpenApps = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "apps", activeKey, settingsSection: "apps" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenAutomations = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "automations", activeKey, settingsSection: "automations" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onOpenSkills = useCallback(() => {
    setSessionSearchOpen(false);
    navigate({ view: "skills", activeKey, settingsSection: "skills" });
    setMobileSidebarOpen(false);
  }, [activeKey, navigate]);

  const onSettingsSectionChange = useCallback(
    (section: SettingsSectionKey) => {
      navigate({
        view: shellViewForSettingsSection(section),
        activeKey,
        settingsSection: section,
      });
    },
    [activeKey, navigate],
  );

  const onBackToChat = useCallback(() => {
    setMobileSidebarOpen(false);
    const nextKey = (() => {
      if (!activeKey) return null;
      if (topicSessions.some((session) => session.key === activeKey)) return activeKey;
      return topicSessions[0]?.key ?? null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      settingsSection: "overview",
    });
  }, [activeKey, navigate, topicSessions]);

  const onRestart = useCallback(() => {
    const chatId = activeSession?.chatId ?? client.defaultChatId;
    if (!chatId) return;
    restartSawDisconnectRef.current = false;
    setIsRestarting(true);
    rememberRestartRoute();
    try {
      window.localStorage.setItem(RESTART_STARTED_KEY, String(Date.now()));
    } catch {
      // ignore storage errors
    }
    void client.sendSystemCommand(chatId, "/restart").catch(() => {});
  }, [activeSession?.chatId, client]);

  useEffect(() => {
    return client.onRuntimeModelUpdate((modelName) => {
      onModelNameChange(modelName);
    });
  }, [client, onModelNameChange]);

  useEffect(() => {
    return client.onRunStatus((chatId, startedAt) => {
      if (startedAt != null) {
        const nextRunning = new Set(runningChatIdsRef.current);
        nextRunning.add(chatId);
        runningChatIdsRef.current = nextRunning;
        setRunningChatIds(nextRunning);
        setUpdatedChatIds((current) => {
          if (!current.has(chatId)) return current;
          const next = new Set(current);
          next.delete(chatId);
          return next;
        });
        return;
      }

      if (!runningChatIdsRef.current.has(chatId)) return;
      const nextRunning = new Set(runningChatIdsRef.current);
      nextRunning.delete(chatId);
      runningChatIdsRef.current = nextRunning;
      setRunningChatIds(nextRunning);
      if (
        Object.values(temporarySessionsRef.current).some(
          (session) => session.chatId === chatId,
        )
      ) return;
      setUpdatedChatIds((current) => {
        const next = new Set(current);
        if (activeChatIdRef.current === chatId) {
          next.delete(chatId);
        } else {
          next.add(chatId);
        }
        return next;
      });
    });
  }, [client]);

  useEffect(() => {
    let wasOpen = client.status === "open";
    return client.onStatus((status) => {
      if (status === "open") {
        wasOpen = true;
        return;
      }
      if (!wasOpen) return;
      wasOpen = false;
      if (Object.keys(temporarySessionsRef.current).length === 0) return;
      temporarySessionsRef.current = {};
      setTemporarySessions({});
      if (readShellRoute().temporary) {
        navigate(defaultShellRoute(), { replace: true });
      }
    });
  }, [client, navigate]);

  useEffect(() => {
    return client.onStatus((status) => {
      const startedAt = (() => {
        try {
          return Number(window.localStorage.getItem(RESTART_STARTED_KEY) ?? "0");
        } catch {
          return 0;
        }
      })();
      if (!startedAt) return;
      if (status !== "open") {
        restartSawDisconnectRef.current = true;
        return;
      }
      const elapsedMs = Date.now() - startedAt;
      if (!restartSawDisconnectRef.current && elapsedMs < 1500) return;
      try {
        window.localStorage.removeItem(RESTART_STARTED_KEY);
        window.localStorage.removeItem(RESTART_ROUTE_KEY);
      } catch {
        // ignore storage errors
      }
      setIsRestarting(false);
      setRestartToast(t("app.restart.completed", { seconds: (elapsedMs / 1000).toFixed(1) }));
      window.setTimeout(() => setRestartToast(null), 3_500);
    });
  }, [client, t]);

  const onTurnEnd = useDeferredTitleRefresh(
    temporaryChatActive ? null : activePaneSession,
    refresh,
  );

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const items = pendingDelete.items;
    const deletingKeys = new Set(items.map((item) => item.key));
    const hasAutomations = (pendingDelete.automations?.length ?? 0) > 0;
    const deletingActive = activeKey !== null && deletingKeys.has(activeKey);
    const currentIndex = topicSessions.findIndex((s) => s.key === activeKey);
    const fallbackKey = deletingActive
      ? (
          topicSessions.slice(currentIndex + 1).find((session) => (
            !deletingKeys.has(session.key)
          ))?.key
          ?? topicSessions.slice(0, Math.max(0, currentIndex)).reverse().find((session) => (
            !deletingKeys.has(session.key)
          ))?.key
          ?? null
        )
      : activeKey;
    try {
      for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        const result = await deleteChat(
          item.key,
          hasAutomations ? { deleteAutomations: true } : undefined,
        );
        if (result.blocked_by_automations) {
          setPendingDelete({
            items: items.slice(index),
            automations: result.automations ?? [],
          });
          return;
        }
      }
      setPendingDelete(null);
      if (deletingActive) {
        navigate({
          view: "chat",
          activeKey: fallbackKey,
          settingsSection: "overview",
        }, { replace: true });
      }
    } catch (e) {
      console.error("Failed to delete session", e);
    }
  }, [pendingDelete, deleteChat, activeKey, navigate, topicSessions]);

  const onRequestDeleteMany = useCallback(async (items: SidebarDeleteItem[]) => {
    const uniqueItems = Array.from(new Map(items.map((item) => [item.key, item])).values());
    if (uniqueItems.length === 0) return;
    const automationResults = await Promise.allSettled(
      uniqueItems.map((item) => getSessionAutomations(item.key)),
    );
    const automations = automationResults.flatMap((result) => (
      result.status === "fulfilled" ? result.value : []
    ));
    setPendingDelete({ items: uniqueItems, automations });
  }, [getSessionAutomations]);

  const onRequestDelete = useCallback((key: string, label: string) => {
    void onRequestDeleteMany([{ key, label }]);
  }, [onRequestDeleteMany]);

  const visiblePairingRequests = useMemo(
    () => {
      const now = Date.now();
      return pairingRequests.filter((request) => {
        const snoozedUntil = snoozedPairingCodes.get(request.code);
        return !snoozedUntil || snoozedUntil <= now;
      });
    },
    [pairingRequests, snoozedPairingCodes],
  );

  const onPairingAction = useCallback(
    async (action: "approve" | "deny", code: string) => {
      setPairingBusyCode(code);
      setPairingError(null);
      try {
        const payload = await runPairingAction(client, action, code);
        setPairingRequests(Array.isArray(payload.requests) ? payload.requests : []);
        setSnoozedPairingCodes((current) => {
          if (!current.has(code)) return current;
          const next = new Map(current);
          next.delete(code);
          return next;
        });
      } catch (e) {
        setPairingError((e as Error).message);
        void refreshPairingRequests();
      } finally {
        setPairingBusyCode(null);
      }
    },
    [client, refreshPairingRequests],
  );

  const onDismissPairingRequest = useCallback((code: string) => {
    setSnoozedPairingCodes((current) => {
      const snoozedUntil = Date.now() + PAIRING_DISMISS_SNOOZE_MS;
      if (current.get(code) === snoozedUntil) return current;
      const next = new Map(current);
      next.set(code, snoozedUntil);
      return next;
    });
  }, []);

  const titleForSession = useCallback((session: ChatSummary) => (
    sidebarState.title_overrides[session.key]
    || session.title
    || deriveTitle(session.preview, t("chat.newChat"))
  ), [sidebarState.title_overrides, t]);

  const automaticSidebarSort = sidebarState.view.sort === "manual"
    ? "updated_desc"
    : sidebarState.view.sort;
  const orderedWorkbenchTabs = useMemo(() => {
    const orderedSessions = sortSessions(
      sessions,
      automaticSidebarSort,
      sidebarState.title_overrides,
      sidebarState.session_order,
    );
    const updatedAtByKey = new Map(sessions.map((session) => [
      session.key,
      session.updatedAt ?? session.createdAt,
    ]));
    return orderWorkbenchTabs(
      workbenchState,
      orderedSessions.map((session) => session.key),
      updatedAtByKey,
    );
  }, [
    automaticSidebarSort,
    sessions,
    sidebarState.session_order,
    sidebarState.title_overrides,
    workbenchState,
  ]);
  const orderedWorkbenchTabsByKey = useMemo(
    () => new Map(orderedWorkbenchTabs.map((tab) => [tab.tabKey, tab])),
    [orderedWorkbenchTabs],
  );
  const sidebarTabPresentations = useMemo(() => {
    const sessionsByKey = new Map(sessions.map((session) => [session.key, session]));
    return orderedWorkbenchTabs.flatMap((tab) => {
      const anchorKey = tab.tab.paneKeys.find((key) => sessionsByKey.has(key))
        ?? tab.paneKeys[0];
      const anchor = sessionsByKey.get(anchorKey);
      if (!anchor) return [];
      const title = tab.tab.title ?? titleForSession(anchor);
      const visible = tab.tab.explicit || tab.paneKeys.length > 1;
      const rowKey = visible ? tab.tabKey : tab.paneKeys[0];
      return [{
        orderedTab: tab,
        rowKey,
        title,
        session: visible
          ? {
              ...anchor,
              key: tab.tabKey,
              chatId: `workbench-tab:${tab.tabKey}`,
              title,
              preview: "",
              updatedAt: tab.updatedAt,
            }
          : anchor,
      }];
    });
  }, [orderedWorkbenchTabs, sessions, titleForSession]);
  const sidebarTopicSessions = useMemo(
    () => sidebarTabPresentations.map((presentation) => presentation.session),
    [sidebarTabPresentations],
  );

  const headerTitle = temporaryChatActive
    ? deriveTemporaryChatTitle(activeSession?.preview, t("temporaryChat.title"))
    : activeSession
    ? titleForSession(activeSession)
    : t("app.brand");
  const workbenchPaneSessions = useMemo(() => {
    if (!activeTabState) return [];
    const byKey = new Map(sessions.map((session) => [session.key, session]));
    const sortedPaneKeys = activeTabKey
      ? orderedWorkbenchTabsByKey.get(activeTabKey)?.paneKeys ?? activeTabState.paneKeys
      : activeTabState.paneKeys;
    const paneKeys = [
      ...activeTabState.layoutPaneKeys.filter((key) => byKey.has(key)),
      ...sortedPaneKeys.filter((key) => !activeTabState.layoutPaneKeys.includes(key)),
    ];
    return paneKeys
      .map((key) => byKey.get(key))
      .filter((session): session is ChatSummary => session !== undefined);
  }, [activeTabKey, activeTabState, orderedWorkbenchTabsByKey, sessions]);
  const paneChromeEnabled = Boolean(
    activeKey && activeSession && !temporaryChatActive && activeTabState,
  );
  const activeTabVisible = Boolean(
    activeTabState
    && (activeTabState.explicit || activeTabState.paneKeys.length > 1),
  );
  const renderedWorkbenchPanes = useMemo(() => {
    if (paneChromeEnabled) {
      return workbenchPaneSessions.map((session) => ({
        key: session.key,
        reactKey: session.key === activeTabState?.paneKeys[0]
          ? "tab-root"
          : `pane:${session.key}`,
        title: titleForSession(session),
      }));
    }
    return [{
      key: activeKey ?? "new-topic",
      reactKey: "tab-root",
      title: headerTitle,
    }];
  }, [
    activeKey,
    activeTabState?.paneKeys,
    headerTitle,
    paneChromeEnabled,
    titleForSession,
    workbenchPaneSessions,
  ]);
  const renderedActivePaneKey = activeKey ?? renderedWorkbenchPanes[0].key;
  const renderedWorkbenchLayout = paneChromeEnabled && activeTabState
    ? activeTabState.layout
    : "columns";
  const renderedWorkbenchSplitRatios = paneChromeEnabled && activeTabState
    ? activeTabState.splitRatios
    : [];
  const sidebarPaneGroups = useMemo(() => {
    const sessionsByKey = new Map(sessions.map((session) => [session.key, session]));
    return Object.fromEntries(sidebarTabPresentations.map((presentation) => {
      const orderedTab = presentation.orderedTab;
      const panes = orderedTab.paneKeys
        .map((key) => sessionsByKey.get(key))
        .filter((session): session is ChatSummary => session !== undefined)
        .map((session) => ({
          key: session.key,
          chatId: session.chatId,
          title: titleForSession(session),
        }));
      return [presentation.rowKey, {
        tabKey: orderedTab.tabKey,
        title: presentation.title,
        activePaneKey: activeKey && orderedTab.paneKeys.includes(activeKey)
          ? activeKey
          : orderedTab.paneKeys[0],
        visible: orderedTab.tab.explicit || orderedTab.paneKeys.length > 1,
        panes,
      }];
    }));
  }, [
    activeKey,
    sessions,
    sidebarTabPresentations,
    titleForSession,
  ]);
  const activePaneLimitReached = Boolean(
    activeTabState && activeTabState.paneKeys.length >= MAX_WORKBENCH_PANES,
  );

  const onActivateWorkbenchPane = useCallback((paneKey: string) => {
    onSelectChat(paneKey);
  }, [onSelectChat]);

  const onSelectSidebarTab = useCallback((tabKey: string) => {
    const tab = workbenchTab(workbenchState, tabKey);
    if (!tab) return;
    const rememberedPaneKey = lastActivePaneByTabRef.current.get(tabKey);
    onSelectChat(
      rememberedPaneKey && tab.paneKeys.includes(rememberedPaneKey)
        ? rememberedPaneKey
        : tab.paneKeys[0],
    );
  }, [onSelectChat, workbenchState]);

  const onSelectSidebarItem = useCallback((key: string) => {
    if (
      temporarySessionsRef.current[key]
      || sessions.some((session) => session.key === key)
    ) {
      onSelectChat(key);
      return;
    }
    onSelectSidebarTab(key);
  }, [onSelectChat, onSelectSidebarTab, sessions]);

  const onSelectSidebarPane = useCallback((_tabKey: string, paneKey: string) => {
    onSelectChat(paneKey);
  }, [onSelectChat]);

  const onDetachWorkbenchPane = useCallback((tabKey: string, paneKey: string) => {
    updateWorkbenchState((current) => detachWorkbenchPane(current, tabKey, paneKey));
  }, [updateWorkbenchState]);

  const onCreateWorkbenchTab = useCallback((paneKey: string) => {
    updateWorkbenchState((current) => createWorkbenchTab(current, paneKey));
  }, [updateWorkbenchState]);

  const onDissolveWorkbenchTab = useCallback((tabKey: string) => {
    updateWorkbenchState((current) => dissolveWorkbenchTab(current, tabKey));
  }, [updateWorkbenchState]);

  const onAttachWorkbenchPane = useCallback((
    paneKey: string,
    tabKey: string,
  ) => {
    updateWorkbenchState((current) => {
      const target = workbenchTab(current, tabKey);
      if (
        !target
        || (!target.explicit && target.paneKeys.length < 2)
        || (!target.paneKeys.includes(paneKey) && target.paneKeys.length >= MAX_WORKBENCH_PANES)
      ) return current;
      return attachWorkbenchPane(current, tabKey, paneKey);
    });
  }, [updateWorkbenchState]);

  useEffect(() => {
    if (view === "settings") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.sidebar.title"),
      });
      return;
    }
    if (view === "apps") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.apps", { defaultValue: "Apps" }),
      });
      return;
    }
    if (view === "automations") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.automations", { defaultValue: "Automations" }),
      });
      return;
    }
    if (view === "skills") {
      document.title = t("app.documentTitle.chat", {
        title: t("settings.nav.skills", { defaultValue: "Skills" }),
      });
      return;
    }
    document.title = activeSession
      ? t("app.documentTitle.chat", { title: headerTitle })
      : t("app.documentTitle.base");
  }, [activeSession, headerTitle, i18n.resolvedLanguage, t, view]);

  const pinnedPaneKeys = useMemo(
    () => new Set(sidebarState.pinned_keys),
    [sidebarState.pinned_keys],
  );
  const archivedPaneKeys = useMemo(
    () => new Set(sidebarState.archived_keys),
    [sidebarState.archived_keys],
  );
  const sidebarPinnedTabKeys = useMemo(() => sidebarTabPresentations
    .filter(({ orderedTab }) => orderedTab.paneKeys.some((key) => pinnedPaneKeys.has(key)))
    .map(({ rowKey }) => rowKey), [pinnedPaneKeys, sidebarTabPresentations]);
  const sidebarArchivedTabKeys = useMemo(() => sidebarTabPresentations
    .filter(({ orderedTab }) => orderedTab.paneKeys.every((key) => archivedPaneKeys.has(key)))
    .map(({ rowKey }) => rowKey), [archivedPaneKeys, sidebarTabPresentations]);
  const activeSidebarKey = activeTabKey
    ? sidebarTabPresentations.find(({ orderedTab }) => (
        orderedTab.tabKey === activeTabKey
      ))?.rowKey ?? activeKey
    : activeKey;

  const sidebarProps = {
    sessions: sidebarTopicSessions,
    temporarySessions: temporarySessionList,
    activeKey: view === "chat"
      ? (temporaryChatActive ? activeKey : activeSidebarKey)
      : null,
    loading,
    newChatActive: view === "chat" && activeKey === null,
    onNewChat,
    onSelect: onSelectSidebarItem,
    onCloseTemporaryChat,
    onRequestDelete,
    onRequestDeleteMany,
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onRequestRenameTab,
    paneGroups: sidebarPaneGroups,
    onSelectPane: onSelectSidebarPane,
    onCreateTab: mobileWorkbench ? undefined : onCreateWorkbenchTab,
    onDetachPane: mobileWorkbench ? undefined : onDetachWorkbenchPane,
    onDissolveTab: mobileWorkbench ? undefined : onDissolveWorkbenchTab,
    onAttachPane: mobileWorkbench ? undefined : onAttachWorkbenchPane,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenSettings,
    onOpenApps,
    onOpenAutomations,
    onOpenSkills,
    onSettingsIntent,
    onOpenSearch: onOpenSessionSearch,
    activeUtility: view === "apps" || view === "automations" || view === "skills" ? view : null,
    onToggleArchived,
    pinnedKeys: sidebarPinnedTabKeys,
    archivedKeys: sidebarArchivedTabKeys,
    pinnedPaneKeys: sidebarState.pinned_keys,
    archivedPaneKeys: sidebarState.archived_keys,
    sessionOrder: sidebarState.session_order,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    updatedChatIds: updatedChatIdList,
    viewState: { ...sidebarState.view, sort: automaticSidebarSort },
    showArchived: sidebarState.view.show_archived,
    archivedCount: sidebarArchivedTabKeys.length,
    defaultWorkspacePath: workspaces?.default_scope.project_path ?? null,
  };
  const hostSidebarCollapsed = showHostChrome && !hostSidebarOpen;
  const showHostSidebarPreview =
    showMainSidebar && hostSidebarCollapsed && hostSidebarPreviewOpen;
  const hostSidebarFlowWidth = showHostChrome
    ? (hostSidebarOpen ? SIDEBAR_WIDTH : 0)
    : (hostSidebarOpen ? SIDEBAR_WIDTH : SIDEBAR_RAIL_WIDTH);
  const renderHostSidebarFlowContent = !showHostChrome || hostSidebarOpen;

  useEffect(() => {
    document.documentElement.classList.toggle("native-host", showHostChrome);
    return () => {
      document.documentElement.classList.remove("native-host");
    };
  }, [showHostChrome]);

  return (
    <ThemeProvider theme={theme}>
      <div
        className={cn(
          "relative h-full w-full overflow-hidden",
          showHostChrome && "host-window-shell",
        )}
      >
        {showHostChrome ? (
          <HostChrome
            onToggleSidebar={showMainSidebar ? toggleHostSidebar : undefined}
            onSidebarPreviewEnter={openHostSidebarPreview}
            onSidebarPreviewLeave={scheduleHostSidebarPreviewClose}
            sidebarOpen={hostSidebarOpen}
            rightAction={
              view === "chat" ? undefined : (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("thread.header.toggleTheme")}
                  onClick={toggle}
                  className="h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
                >
                  {theme === "dark" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </Button>
              )
            }
          />
        ) : null}
        <div
          className={cn(
            "relative flex h-full w-full overflow-hidden",
          )}
        >
          {/* Host sidebar: in normal flow, so the thread area width stays honest. */}
          {showMainSidebar ? (
            <aside
              data-testid="host-sidebar-flow"
              className={cn(
                "relative z-20 hidden shrink-0 overflow-hidden lg:block",
                "transition-[width] duration-300 ease-out",
              )}
              style={{
                width: hostSidebarFlowWidth,
              }}
            >
              {renderHostSidebarFlowContent ? (
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 h-full w-full overflow-hidden",
                    showHostChrome
                      ? "host-sidebar-glass"
                      : "bg-sidebar",
                  )}
                >
                  <Sidebar
                    {...sidebarProps}
                    collapsed={!showHostChrome && !hostSidebarOpen}
                    hostChromeInset={showHostChrome}
                    onCollapse={closeHostSidebar}
                    onExpand={openHostSidebar}
                  />
                </div>
              ) : null}
            </aside>
          ) : null}

          {showHostSidebarPreview ? (
            <aside
              data-testid="host-sidebar-preview"
              className="absolute inset-y-0 left-0 z-30 hidden overflow-hidden lg:block animate-in fade-in-0 slide-in-from-left-2 duration-150"
              style={{ width: SIDEBAR_WIDTH }}
              onMouseEnter={openHostSidebarPreview}
              onMouseLeave={scheduleHostSidebarPreviewClose}
            >
              <div className="h-full w-full overflow-hidden host-sidebar-glass shadow-2xl">
                <Sidebar
                  {...sidebarProps}
                  hostChromeInset={showHostChrome}
                  onCollapse={closeHostSidebar}
                  onExpand={openHostSidebar}
                />
              </div>
            </aside>
          ) : null}

          {showMainSidebar ? (
            <Sheet
              open={mobileSidebarOpen}
              onOpenChange={(open) => setMobileSidebarOpen(open)}
            >
              <SheetContent
                side="left"
                showCloseButton={false}
                aria-describedby={undefined}
                className="p-0 lg:hidden"
                style={{ width: MOBILE_SIDEBAR_WIDTH, maxWidth: MOBILE_SIDEBAR_WIDTH }}
              >
                <SheetTitle className="sr-only">{t("sidebar.navigation")}</SheetTitle>
                <Sidebar
                  {...sidebarProps}
                  onCollapse={closeMobileSidebar}
                  containActionMenus
                />
              </SheetContent>
            </Sheet>
          ) : null}

          {sessionSearchOpen ? (
            <Suspense fallback={null}>
              <SessionSearchDialog
                open
                onOpenChange={setSessionSearchOpen}
                sessions={topicSessions}
                activeKey={activeKey}
                loading={loading}
                titleOverrides={sidebarState.title_overrides}
                onSelect={onSelectSearchResult}
              />
            </Suspense>
          ) : null}
        <main
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
          )}
        >
            <div
              className={cn(
                "absolute inset-0 flex flex-col",
                view !== "chat" && "hidden",
              )}
            >
              <PaneWorkbench
                panes={renderedWorkbenchPanes}
                activePaneKey={renderedActivePaneKey}
                layout={renderedWorkbenchLayout}
                splitRatios={renderedWorkbenchSplitRatios}
                chrome={paneChromeEnabled}
                showLayoutControl={activeTabVisible}
                addPaneDisabled={creatingPane || activePaneLimitReached}
                addPaneDisabledLabel={activePaneLimitReached
                  ? t("workbench.paneLimit", {
                      defaultValue: "Maximum {{count}} panes",
                      count: MAX_WORKBENCH_PANES,
                    })
                  : undefined}
                onActivatePane={onActivateWorkbenchPane}
                onAddPane={onAddPane}
                onLayoutChange={(layout) => {
                  if (!activeTabKey) return;
                  updateWorkbenchState((current) => (
                    setWorkbenchLayout(current, activeTabKey, layout)
                  ));
                }}
                onPaneOrderChange={(paneKeys) => {
                  if (!activeTabKey) return;
                  updateWorkbenchState((current) => (
                    setWorkbenchPaneLayoutOrder(current, activeTabKey, paneKeys)
                  ));
                }}
                onSplitRatiosChange={(splitRatios) => {
                  if (!activeTabKey) return;
                  updateWorkbenchState((current) => (
                    setWorkbenchSplitRatios(current, activeTabKey, splitRatios)
                  ));
                }}
                renderPane={(pane, context) => {
                  if (!paneChromeEnabled) {
                    return (
                      <ThreadShell
                        session={activeSession}
                        sessions={sessions}
                        title={headerTitle}
                        temporary={temporaryChatRequested}
                        temporaryChatIds={temporaryChatIds}
                        temporaryChatEnabled={temporaryChatEnabled}
                        onTemporaryChatEnabledChange={
                          !activeKey ? onTemporaryChatEnabledChange : undefined
                        }
                        onToggleSidebar={toggleSidebar}
                        onNewChat={onNewChat}
                        onCreateChat={
                          temporaryChatEnabled ? onCreateTemporaryChat : onCreateChat
                        }
                        onForkChat={temporaryChatActive ? undefined : onForkChat}
                        onTurnEnd={onTurnEnd}
                        theme={theme}
                        onToggleTheme={toggle}
                        hideSidebarToggleForHostChrome
                        hostChromeTitleInset={hostSidebarCollapsed}
                        hideHeader={false}
                        workspaceScope={activeWorkspaceScope}
                        workspaceDefaultScope={workspaces?.default_scope ?? null}
                        workspaceControls={workspaces?.controls ?? null}
                        workspaceScopeDisabled={activeChatRunning}
                        workspaceError={workspaceError}
                        onWorkspaceScopeChange={applyWorkspaceScope}
                        settingsSnapshot={settingsSnapshot}
                        onOpenModelSettings={onOpenModelSettings}
                        skills={skills}
                      />
                    );
                  }

                  const paneSession = workbenchPaneSessions.find(
                    (session) => session.key === pane.key,
                  );
                  if (!paneSession) return null;
                  const paneScope = workspaceOverrides[paneSession.chatId]
                    ?? paneSession.workspaceScope
                    ?? workspaces?.default_scope
                    ?? null;
                  const paneRunning = runningChatIds.has(paneSession.chatId);
                  return (
                    <ThreadShell
                      session={paneSession}
                      sessions={sessions}
                      title={pane.title}
                      onToggleSidebar={toggleSidebar}
                      onNewChat={onNewChat}
                      onCreateChat={onCreateChat}
                      onForkChat={onForkChat}
                      onTurnEnd={context.active ? onTurnEnd : () => void refresh()}
                      theme={theme}
                      onToggleTheme={toggle}
                      hideSidebarToggle={!context.active}
                      hideSidebarToggleForHostChrome={context.active}
                      hostChromeTitleInset={hostSidebarCollapsed}
                      hideThemeButton={!context.active}
                      hideHeaderTitle
                      headerActions={context.headerActions}
                      headerPortalTarget={context.headerPortalTarget}
                      headerActive={context.active}
                      composerPortalTarget={context.composerPortalTarget}
                      composerActive={context.active}
                      composerInputAriaLabel={t("workbench.composerAria", {
                        defaultValue: "Message {{title}}",
                        title: pane.title,
                      })}
                      emptyComposerVariant="thread"
                      workspaceScope={paneScope}
                      workspaceDefaultScope={workspaces?.default_scope ?? null}
                      workspaceControls={workspaces?.controls ?? null}
                      workspaceScopeDisabled={paneRunning}
                      workspaceError={context.active ? workspaceError : null}
                      onWorkspaceScopeChange={(scope) => {
                        if (paneRunning) return;
                        const next = normalizeWorkspaceScope(scope);
                        setWorkspaceError(null);
                        setWorkspaceOverrides((current) => ({
                          ...current,
                          [paneSession.chatId]: next,
                        }));
                        client.setWorkspaceScope(paneSession.chatId, next);
                      }}
                      settingsSnapshot={settingsSnapshot}
                      onOpenModelSettings={onOpenModelSettings}
                      skills={skills}
                    />
                  );
                }}
              />
            </div>
            {view !== "chat" && (
              <div className="absolute inset-0 flex flex-col">
                <Suspense fallback={<SurfaceLoadingFallback />}>
                  <SettingsView
                    theme={theme}
                    initialSection={settingsInitialSection}
                    initialSettings={settingsSnapshot}
                    showSidebar={view === "settings"}
                    onToggleTheme={toggle}
                    onBackToChat={onBackToChat}
                    onModelNameChange={onModelNameChange}
                    onSettingsChange={setSettingsSnapshot}
                    skills={skills}
                    onSectionChange={onSettingsSectionChange}
                    onLogout={onLogout}
                    onRestart={onRestart}
                    onNativeEngineRestart={onNativeEngineRestart}
                    isRestarting={isRestarting}
                    hostChromeInset={showHostChrome}
                  />
                </Suspense>
              </div>
            )}
          </main>
        </div>

        {pendingDelete ? (
          <Suspense fallback={null}>
            <DeleteConfirm
              open
              title={pendingDelete.items[0]?.label ?? ""}
              count={pendingDelete.items.length}
              automations={pendingDelete.automations}
              onCancel={() => setPendingDelete(null)}
              onConfirm={onConfirmDelete}
            />
          </Suspense>
        ) : null}
        {pendingRename ? (
          <Suspense fallback={null}>
            <RenameChatDialog
              open
              title={pendingRename.label}
              onCancel={() => setPendingRename(null)}
              onConfirm={onConfirmRename}
            />
          </Suspense>
        ) : null}
        {pendingTabRename ? (
          <Suspense fallback={null}>
            <RenameChatDialog
              open
              title={pendingTabRename.label}
              dialogTitle={t("workbench.renameTabTitle")}
              description={t("workbench.renameTabDescription")}
              placeholder={t("workbench.renameTabPlaceholder")}
              onCancel={() => setPendingTabRename(null)}
              onConfirm={onConfirmTabRename}
            />
          </Suspense>
        ) : null}
        {pendingProjectRename ? (
          <Suspense fallback={null}>
            <RenameChatDialog
              open
              title={pendingProjectRename.label}
              dialogTitle={t("chat.renameProjectTitle")}
              description={t("chat.renameProjectDescription")}
              placeholder={t("chat.renameProjectPlaceholder")}
              onCancel={() => setPendingProjectRename(null)}
              onConfirm={onConfirmProjectRename}
            />
          </Suspense>
        ) : null}
        {restartToast ? (
          <div className="fixed left-1/2 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 flex w-[min(32rem,calc(100vw-1rem))] -translate-x-1/2 flex-col items-center gap-2">
            <div
              role="status"
              className={cn(
                floatingSurfaceElevationClassName,
                "max-w-full rounded-full px-4 py-2 text-sm font-medium",
              )}
            >
              {restartToast}
            </div>
          </div>
        ) : null}
        <PairingCodePopup
          requests={visiblePairingRequests}
          total={visiblePairingRequests.length}
          busyCode={pairingBusyCode}
          error={pairingError}
          onApprove={(code) => void onPairingAction("approve", code)}
          onDismiss={onDismissPairingRequest}
        />
      </div>
    </ThemeProvider>
  );
}
