import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Moon, PanelLeft, ShieldCheck, Sun, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DeleteConfirm } from "@/components/DeleteConfirm";
import { RenameChatDialog } from "@/components/RenameChatDialog";
import { Sidebar } from "@/components/Sidebar";
import { SessionSearchDialog } from "@/components/SessionSearchDialog";
import { SettingsView, type SettingsSectionKey } from "@/components/settings/SettingsView";
import { ThreadShell } from "@/components/thread/ThreadShell";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

import { useSessions } from "@/hooks/useSessions";
import { useDeferredTitleRefresh } from "@/hooks/useDeferredTitleRefresh";
import { useSidebarState } from "@/hooks/useSidebarState";
import { useSkills } from "@/hooks/useSkills";
import { useLogoFallback } from "@/hooks/useLogoFallback";
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
import { displayTitle } from "@/lib/chat-groups";
import { deriveTitle } from "@/lib/format";
import { NanobotClient } from "@/lib/nanobot-client";
import { ClientProvider, useClient } from "@/providers/ClientProvider";
import type {
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
import { projectNameFromPath } from "@/lib/workspace";

type BootState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "auth"; failed?: boolean }
  | {
      status: "ready";
      client: NanobotClient;
      token: string;
      tokenExpiresAt: number;
      modelName: string | null;
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
const PAIRING_DISMISS_SNOOZE_MS = 30_000;
type ShellView = "chat" | "settings" | "apps" | "automations" | "skills";
type ShellRoute = {
  view: ShellView;
  activeKey: string | null;
  settingsSection: SettingsSectionKey;
};

type PairingChannelPresentation = {
  label: string;
  initials: string;
  color: string;
  logoUrl?: string;
};

const PAIRING_CHANNEL_PRESENTATION: Record<string, PairingChannelPresentation> = {
  dingtalk: {
    label: "DingTalk",
    initials: "DT",
    color: "#FF6A00",
    logoUrl: "https://www.dingtalk.com/favicon.ico",
  },
  discord: {
    label: "Discord",
    initials: "DC",
    color: "#5865F2",
    logoUrl: "https://discord.com/favicon.ico",
  },
  email: {
    label: "Email",
    initials: "EM",
    color: "#EA4335",
    logoUrl: "https://gmail.com/favicon.ico",
  },
  feishu: {
    label: "Feishu",
    initials: "FS",
    color: "#3370FF",
    logoUrl: "https://www.feishu.cn/favicon.ico",
  },
  lark: {
    label: "Lark",
    initials: "LK",
    color: "#3370FF",
    logoUrl: "https://www.larksuite.com/favicon.ico",
  },
  matrix: {
    label: "Matrix",
    initials: "M",
    color: "#111827",
    logoUrl: "https://matrix.org/favicon.ico",
  },
  msteams: {
    label: "Microsoft Teams",
    initials: "MT",
    color: "#6264A7",
    logoUrl: "https://www.microsoft.com/favicon.ico",
  },
  napcat: {
    label: "NapCat",
    initials: "NC",
    color: "#7C3AED",
    logoUrl: "https://napneko.github.io/favicon.ico",
  },
  qq: {
    label: "QQ",
    initials: "QQ",
    color: "#12B7F5",
    logoUrl: "https://im.qq.com/favicon.ico",
  },
  signal: {
    label: "Signal",
    initials: "SG",
    color: "#3A76F0",
    logoUrl: "https://signal.org/favicon.ico",
  },
  slack: {
    label: "Slack",
    initials: "SL",
    color: "#611F69",
    logoUrl: "https://slack.com/favicon.ico",
  },
  telegram: {
    label: "Telegram",
    initials: "TG",
    color: "#229ED9",
    logoUrl: "https://telegram.org/favicon.ico",
  },
  wecom: {
    label: "WeCom",
    initials: "WC",
    color: "#2F7DFF",
    logoUrl: "https://work.weixin.qq.com/favicon.ico",
  },
  weixin: {
    label: "WeChat",
    initials: "WX",
    color: "#07C160",
    logoUrl: "https://weixin.qq.com/favicon.ico",
  },
  whatsapp: {
    label: "WhatsApp",
    initials: "WA",
    color: "#25D366",
    logoUrl: "https://www.whatsapp.com/favicon.ico",
  },
};

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
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const secret = value.trim();
    if (!secret) return;
    setSubmitting(true);
    onSecret(secret);
  };

  return (
    <div className="flex h-full w-full items-center justify-center px-6">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-4"
      >
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="text-lg font-semibold">{t("app.auth.title")}</p>
          <p className="text-sm text-muted-foreground">{t("app.auth.hint")}</p>
        </div>
        {failed && (
          <p className="text-center text-sm text-destructive">
            {t("app.auth.invalid")}
          </p>
        )}
        <Input
          type="password"
          placeholder={t("app.auth.placeholder")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={submitting}
          autoFocus
        />
        <Button
          type="submit"
          className="w-full"
          disabled={!value.trim() || submitting}
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
        "border border-border/70 bg-popover/95 p-4 text-popover-foreground",
        "shadow-[0_24px_70px_rgba(15,23,42,0.20)] backdrop-blur-xl",
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
  const key = pairingChannelKey(channel);
  const presentation = PAIRING_CHANNEL_PRESENTATION[key];
  const label = presentation?.label ?? channelLabel(channel);
  const initials = presentation?.initials ?? label.slice(0, 2).toUpperCase();
  const color = presentation?.color ?? "#10B981";
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
  const key = pairingChannelKey(channel);
  return PAIRING_CHANNEL_PRESENTATION[key]?.label ?? channel;
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
      const tokenExpiresAt = bootstrapTokenExpiresAt(boot.expires_in);
      if (runtimeHost.socketFactory) {
        client.updateUrl(url, runtimeHost.socketFactory);
      } else {
        client.updateUrl(url);
      }
      setState((current) =>
        current.status === "ready" && current.client === client
          ? {
              ...current,
              token: boot.api_token,
              tokenExpiresAt,
              modelName: boot.model_name ?? current.modelName,
              runtimeSurface,
            }
          : current,
      );
      return { token: boot.api_token, url };
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
            token: boot.api_token,
            tokenExpiresAt: bootstrapTokenExpiresAt(boot.expires_in),
            modelName: boot.model_name ?? null,
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
    if (state.status !== "ready") return;
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
  const { client, token } = useClient();
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
  const { state: sidebarState, update: updateSidebarState } =
    useSidebarState(sessions, !loading);
  const initialRouteRef = useRef<ShellRoute | null>(null);
  if (!initialRouteRef.current) initialRouteRef.current = readShellRoute();
  const [activeKey, setActiveKey] = useState<string | null>(
    initialRouteRef.current.activeKey,
  );
  const [view, setView] = useState<ShellView>(initialRouteRef.current.view);
  const [settingsInitialSection, setSettingsInitialSection] =
    useState<SettingsSectionKey>(initialRouteRef.current.settingsSection);
  const [hostSidebarOpen, setHostSidebarOpen] =
    useState<boolean>(readSidebarOpen);
  const [hostSidebarPreviewOpen, setHostSidebarPreviewOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sessionSearchOpen, setSessionSearchOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{
    key: string;
    label: string;
    automations?: SessionAutomationJob[];
  } | null>(null);
  const [pendingRename, setPendingRename] = useState<{
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
  const [snoozedPairingCodes, setSnoozedPairingCodes] = useState<Map<string, number>>(
    () => new Map(),
  );
  const [runningChatIds, setRunningChatIds] = useState<Set<string>>(() => new Set());
  const [updatedChatIds, setUpdatedChatIds] = useState<Set<string>>(readSessionUpdateChatIds);
  const [workspaces, setWorkspaces] = useState<WorkspacesPayload | null>(null);
  const skills = useSkills(token);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsPayload | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [draftWorkspaceScope, setDraftWorkspaceScope] =
    useState<WorkspaceScopePayload | null>(null);
  const [workspaceOverrides, setWorkspaceOverrides] =
    useState<Record<string, WorkspaceScopePayload>>({});
  const runningChatIdsRef = useRef<Set<string>>(new Set());
  const activeChatIdRef = useRef<string | null>(null);
  const hostSidebarPreviewCloseTimerRef = useRef<number | null>(null);
  const effectiveRuntimeSurface =
    settingsSnapshot?.surface ?? settingsSnapshot?.runtime_surface ?? runtimeSurface;
  const showHostChrome = effectiveRuntimeSurface === "native";
  const showMainSidebar = view !== "settings";

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
    let cancelled = false;
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) setSettingsSnapshot(payload);
      })
      .catch(() => {
        if (!cancelled) setSettingsSnapshot(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

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

  const refreshPairingRequests = useCallback(async () => {
    try {
      const payload = await fetchPairingRequests(token);
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
    } catch {
      // Pairing is an opportunistic WebUI affordance. The slash command path
      // remains available if this polling request fails.
    }
  }, [token]);

  useEffect(() => {
    void refreshPairingRequests();
    const timer = window.setInterval(() => {
      void refreshPairingRequests();
    }, PAIRING_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refreshPairingRequests]);

  const activeSession = useMemo<ChatSummary | null>(() => {
    if (!activeKey) return null;
    return sessions.find((s) => s.key === activeKey) ?? null;
  }, [sessions, activeKey]);
  const runningChatIdList = useMemo(() => Array.from(runningChatIds), [runningChatIds]);
  const updatedChatIdList = useMemo(() => Array.from(updatedChatIds), [updatedChatIds]);
  const activeChatId = activeSession?.chatId ?? null;
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
    if (activeChatId && workspaceOverrides[activeChatId]) {
      return workspaceOverrides[activeChatId];
    }
    if (activeSession?.workspaceScope) {
      return activeSession.workspaceScope;
    }
    return draftWorkspaceScope ?? workspaces?.default_scope ?? null;
  }, [
    activeChatId,
    activeSession?.workspaceScope,
    draftWorkspaceScope,
    workspaceOverrides,
    workspaces?.default_scope,
  ]);
  const activeChatRunning = activeChatId ? runningChatIds.has(activeChatId) : false;

  const refreshWorkspaces = useCallback(async () => {
    try {
      const payload = await fetchWorkspaces(token);
      setWorkspaces(payload);
    } catch {
      setWorkspaces(null);
    }
  }, [token]);

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
    if (loading || !activeKey) return;
    if (sessions.some((session) => session.key === activeKey)) return;
    const currentRoute = readShellRoute();
    navigate(
      currentRoute.view === "chat"
        ? defaultShellRoute()
        : {
            ...currentRoute,
            activeKey: null,
          },
      { replace: true },
    );
  }, [activeKey, loading, navigate, sessions]);

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
        if (!activeChatRunning) {
          client.setWorkspaceScope(activeChatId, next);
        }
        return;
      }
      setDraftWorkspaceScope(next);
    },
    [activeChatId, activeChatRunning, client],
  );

  const onCreateChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null) => {
    try {
      const scope = workspaceScope ?? activeWorkspaceScope;
      const chatId = await createChat(scope);
      navigate({
        view: "chat",
        activeKey: `websocket:${chatId}`,
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
    setDraftWorkspaceScope(null);
    setWorkspaceError(null);
    setSessionSearchOpen(false);
    setMobileSidebarOpen(false);
  }, [navigate]);

  const onNewChatInProject = useCallback(
    (projectPath: string, projectName: string) => {
      const base = workspaces?.default_scope ?? activeWorkspaceScope;
      const trimmed = projectPath.trim();
      if (!base || !trimmed) {
        onNewChat();
        return;
      }
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
      const selected = sessions.find((session) => session.key === key);
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
      navigate({ view: "chat", activeKey: key, settingsSection: "overview" });
      setMobileSidebarOpen(false);
    },
    [navigate, sessions],
  );

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
        const next = sessions.find((session) => !archived.has(session.key));
        navigate({
          view: "chat",
          activeKey: next?.key ?? null,
          settingsSection: "overview",
        });
      }
    },
    [activeKey, navigate, sessions, sidebarState.archived_keys, updateSidebarState],
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
      if (sessions.some((session) => session.key === activeKey)) return activeKey;
      return sessions[0]?.key ?? null;
    })();
    navigate({
      view: "chat",
      activeKey: nextKey,
      settingsSection: "overview",
    });
  }, [activeKey, navigate, sessions]);

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
    client.sendMessage(chatId, "/restart");
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

  const onTurnEnd = useDeferredTitleRefresh(activeSession, refresh);

  const onConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const key = pendingDelete.key;
    const hasAutomations = (pendingDelete.automations?.length ?? 0) > 0;
    const deletingActive = activeKey === key;
    const currentIndex = sessions.findIndex((s) => s.key === key);
    const fallbackKey = deletingActive
      ? (sessions[currentIndex + 1]?.key ?? sessions[currentIndex - 1]?.key ?? null)
      : activeKey;
    try {
      const result = await deleteChat(
        key,
        hasAutomations ? { deleteAutomations: true } : undefined,
      );
      if (result.blocked_by_automations) {
        setPendingDelete({
          ...pendingDelete,
          automations: result.automations ?? [],
        });
        return;
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
  }, [pendingDelete, deleteChat, activeKey, navigate, sessions]);

  const onRequestDelete = useCallback(async (key: string, label: string) => {
    let automations: SessionAutomationJob[] = [];
    try {
      automations = await getSessionAutomations(key);
    } catch {
      // Delete remains protected by the backend block; prefetch only improves the first prompt.
    }
    setPendingDelete({ key, label, automations });
  }, [getSessionAutomations]);

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
        const payload = await runPairingAction(token, action, code);
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
    [refreshPairingRequests, token],
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

  const headerTitle = activeSession
    ? sidebarState.title_overrides[activeSession.key] ||
      activeSession.title ||
      deriveTitle(activeSession.preview, t("chat.newChat"))
    : t("app.brand");

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

  const sidebarProps = {
    sessions,
    activeKey,
    loading,
    onNewChat,
    onSelect: onSelectChat,
    onRequestDelete,
    onTogglePin,
    onRequestRename,
    onToggleArchive,
    onToggleGroup,
    onRequestRenameProject,
    onNewChatInProject,
    onOpenSettings,
    onOpenApps,
    onOpenAutomations,
    onOpenSkills,
    onOpenSearch: onOpenSessionSearch,
    activeUtility: view === "apps" || view === "automations" || view === "skills" ? view : null,
    onToggleArchived,
    pinnedKeys: sidebarState.pinned_keys,
    archivedKeys: sidebarState.archived_keys,
    titleOverrides: sidebarState.title_overrides,
    projectNameOverrides: sidebarState.project_name_overrides,
    collapsedGroups: sidebarState.collapsed_groups,
    runningChatIds: runningChatIdList,
    updatedChatIds: updatedChatIdList,
    viewState: sidebarState.view,
    showArchived: sidebarState.view.show_archived,
    archivedCount: sidebarState.archived_keys.length,
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
                      : "bg-sidebar shadow-inner-right",
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

          <SessionSearchDialog
            open={sessionSearchOpen}
            onOpenChange={setSessionSearchOpen}
            sessions={sessions}
            activeKey={activeKey}
            loading={loading}
            titleOverrides={sidebarState.title_overrides}
            onSelect={onSelectSearchResult}
          />
        <main
          className={cn(
            "relative flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background",
            showHostChrome && hostSidebarOpen && "border-l border-border/55",
          )}
        >
            <div
              className={cn(
                "absolute inset-0 flex flex-col",
                view !== "chat" && "invisible pointer-events-none",
              )}
            >
              <ThreadShell
                session={activeSession}
                title={headerTitle}
                onToggleSidebar={toggleSidebar}
                onNewChat={onNewChat}
                onCreateChat={onCreateChat}
                onForkChat={onForkChat}
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
            </div>
            {view !== "chat" && (
              <div className="absolute inset-0 flex flex-col">
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
                  onWorkspaceSettingsChange={refreshWorkspaces}
                  onSectionChange={onSettingsSectionChange}
                  onLogout={onLogout}
                  onRestart={onRestart}
                  onNativeEngineRestart={onNativeEngineRestart}
                  isRestarting={isRestarting}
                  hostChromeInset={showHostChrome}
                />
              </div>
            )}
          </main>
        </div>

        <DeleteConfirm
          open={!!pendingDelete}
          title={pendingDelete?.label ?? ""}
          automations={pendingDelete?.automations}
          onCancel={() => setPendingDelete(null)}
          onConfirm={onConfirmDelete}
        />
        <RenameChatDialog
          open={!!pendingRename}
          title={pendingRename?.label ?? ""}
          onCancel={() => setPendingRename(null)}
          onConfirm={onConfirmRename}
        />
        <RenameChatDialog
          open={!!pendingProjectRename}
          title={pendingProjectRename?.label ?? ""}
          dialogTitle={t("chat.renameProjectTitle")}
          description={t("chat.renameProjectDescription")}
          placeholder={t("chat.renameProjectPlaceholder")}
          onCancel={() => setPendingProjectRename(null)}
          onConfirm={onConfirmProjectRename}
        />
        {restartToast ? (
          <div
            role="status"
            className="fixed left-1/2 top-[calc(0.75rem+env(safe-area-inset-top))] z-50 max-w-[calc(100vw-1rem)] -translate-x-1/2 rounded-full border border-border/70 bg-popover px-4 py-2 text-sm font-medium text-popover-foreground shadow-lg"
          >
            {restartToast}
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
