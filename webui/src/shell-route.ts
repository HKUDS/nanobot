import { isAppsSection, type SettingsFocusTarget } from "@/components/settings/contracts";
import type { SettingsSectionKey } from "@/components/settings/SettingsView";

export const RESTART_STARTED_KEY = "nanobot-webui.restartStartedAt";
export const RESTART_ROUTE_KEY = "nanobot-webui.restartRoute";
const RESTART_ROUTE_TTL_MS = 5 * 60 * 1000;

export type ShellView = "chat" | "settings" | "apps" | "automations" | "remote";
export type ShellRoute = {
  view: ShellView;
  activeKey: string | null;
  settingsSection: SettingsSectionKey;
  settingsFocus?: SettingsFocusTarget;
  temporary?: boolean;
};

const SETTINGS_SECTION_KEYS: SettingsSectionKey[] = [
  "capabilities",
  "overview",
  "about",
  "appearance",
  "notifications",
  "models",
  "image",
  "voice",
  "browser",
  "channels",
  "apps",
  "automations",
  "memory",
  "skills",
  "runtime",
  "advanced",
];

function isSettingsSectionKey(value: string | null): value is SettingsSectionKey {
  return SETTINGS_SECTION_KEYS.includes(value as SettingsSectionKey);
}

export function defaultShellRoute(): ShellRoute {
  return { view: "chat", activeKey: null, settingsSection: "overview" };
}

export function shellViewForSettingsSection(section: SettingsSectionKey): ShellView {
  if (isAppsSection(section)) return "apps";
  if (section === "automations") return "automations";
  return "settings";
}

export function changesSettingsSurface(current: ShellRoute, next: ShellRoute): boolean {
  return current.view !== "chat" && current.view !== "remote" &&
    (current.view !== next.view || current.settingsSection !== next.settingsSection);
}

function fallbackRestartHash(hash: string): boolean {
  return !hash || hash === "/" || hash === "/new";
}

export function rememberRestartRoute(): void {
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

export function readShellRoute(): ShellRoute {
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
  const saved: unknown = window.history.state?.nanobotReturnChat;
  const returnChat = saved && typeof saved === "object" && "hash" in saved
    && saved.hash === window.location.hash ? saved : null;
  const activeKey = params.get("chat")?.trim()
    || (returnChat && "key" in returnChat && typeof returnChat.key === "string"
      ? returnChat.key : null);
  const temporary = Boolean(returnChat && "temporary" in returnChat && returnChat.temporary === true);

  if (path === "/settings") {
    const focus = params.get("focus");
    return {
      view: shellViewForSettingsSection(settingsSection),
      activeKey,
      temporary,
      settingsSection,
      settingsFocus: settingsSection === "advanced" && (focus === "sandbox" || focus === "sandbox-launcher")
        ? focus
        : settingsSection === "models" && focus?.startsWith("image-input:")
          ? `image-input:${focus.slice("image-input:".length)}`
          : undefined,
    };
  }
  if (path === "/apps") {
    return { view: "apps", activeKey, temporary, settingsSection: isAppsSection(settingsSection) ? settingsSection : "apps" };
  }
  if (path === "/automations") {
    return { view: "automations", activeKey, temporary, settingsSection: "automations" };
  }
  if (path === "/channels") {
    return { view: "apps", activeKey, temporary, settingsSection: "channels" };
  }
  if (path === "/remote") {
    return { view: "remote", activeKey, temporary, settingsSection: "overview" };
  }
  if (path === "/skills") {
    return { view: "apps", activeKey, temporary, settingsSection: "skills" };
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

export function shellRouteHash(route: ShellRoute): string {
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
  if (route.view === "settings" && route.settingsSection !== "overview") {
    params.set("section", route.settingsSection);
    if (route.settingsFocus) params.set("focus", route.settingsFocus);
  }
  if (route.view === "apps" && route.settingsSection !== "apps") {
    params.set("section", route.settingsSection);
  }
  const query = params.toString();
  return `#/${route.view}${query ? `?${query}` : ""}`;
}

export function writeShellRoute(route: ShellRoute, replace = false): void {
  if (typeof window === "undefined") return;
  const nextHash = shellRouteHash(route);
  const state = {
    ...window.history.state,
    nanobotReturnChat: route.view === "chat" ? null : {
      hash: nextHash,
      key: route.activeKey,
      temporary: route.temporary === true,
    },
  };
  const url = `${window.location.pathname}${window.location.search}${nextHash}`;
  if (replace || window.location.hash === nextHash) {
    window.history.replaceState(state, "", url);
  } else {
    window.history.pushState(state, "", url);
  }
}
