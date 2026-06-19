import type { CliAppInfo, CliAppsPayload } from "@/lib/types";

export const CLI_APPS_CHANGED_EVENT = "nanobot:cli-apps-changed";

export function isCliAppsPayload(value: unknown): value is CliAppsPayload {
  return (
    !!value &&
    typeof value === "object" &&
    Array.isArray((value as { apps?: unknown }).apps)
  );
}

export function installedCliAppsFromPayload(payload: CliAppsPayload): CliAppInfo[] {
  return payload.apps.filter((app) => app.installed);
}

export function notifyCliAppsChanged(payload: CliAppsPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<CliAppsPayload>(CLI_APPS_CHANGED_EVENT, {
    detail: payload,
  }));
}
