import { readLocalPreferences } from "./local-preferences";
import type { TaskNotice } from "./nanobot-client";

export type NotificationProblem = "insecure" | "unsupported" | "denied" | "dismissed" | "permissionFailed" | "workerUnavailable" | "displayFailed";
export type NotificationResult = "submitted" | "skipped" | NotificationProblem;
const TIMEOUT_MS = 5_000;
export const NOTIFICATION_STATUS_EVENT = "nanobot:notification-status";
export const NOTIFICATION_OPEN_EVENT = "nanobot:notification-open";
let lastProblem: NotificationProblem | null = null;
export function lastNotificationProblem() { return lastProblem; }

// Do not infer browser support from its user agent (including embedded browsers).
export function notificationProblem(): NotificationProblem | null {
  if (!window.isSecureContext) return "insecure";
  if (typeof Notification === "undefined" || !("serviceWorker" in navigator)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return null;
}

function bounded<T>(operation: Promise<T>, timeoutMs = TIMEOUT_MS): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("Notification timeout")), timeoutMs);
    operation.then(resolve, reject).finally(() => window.clearTimeout(timer));
  });
}

async function activeWorker(): Promise<ServiceWorker | null> {
  // `ready` can wait forever when registration is blocked. An absent or still
  // installing worker is retryable; it must not leave the settings switch busy.
  const registration = await bounded(navigator.serviceWorker.getRegistration());
  return registration?.active ?? null;
}

export async function enableBrowserNotifications(): Promise<NotificationProblem | null> {
  const problem = notificationProblem();
  if (problem) return problem;
  // Request permission before the first await to preserve the user gesture.
  try {
    const permission = Notification.permission === "granted"
      ? "granted" : await bounded(Notification.requestPermission(), 60_000);
    if (permission !== "granted") return permission === "denied" ? "denied" : "dismissed";
  } catch { return "permissionFailed"; }
  try { return await activeWorker() ? null : "workerUnavailable"; }
  catch { return "workerUnavailable"; }
}

export function taskNoticeKey(notice: TaskNotice): string | null {
  const event = notice.event;
  if (event.event === "turn_end") {
    if (event.outcome === "cancelled") return null;
    return event.turn_id ? JSON.stringify([event.chat_id, event.turn_id, "end"]) : null;
  }
  return ["awaiting_user", "failed"].includes(event.status)
    ? JSON.stringify([event.chat_id, event.recovery_id, event.status]) : null;
}

export function notificationChatUrl(chatId: string, temporary: boolean): string {
  // The page origin identifies the gateway, including isolated remote views.
  // Never copy the page's query, fragment, userinfo, or any auth token.
  return `${window.location.origin}/${temporary ? "#/temporary/" : "#/chat/"}${encodeURIComponent(temporary ? chatId : `websocket:${chatId}`)}`;
}

export async function showBrowserNotification(body: string, options: {
  key: string;
  url: string;
  test?: boolean;
}): Promise<NotificationResult> {
  const result = await submitNotification(body, options).catch(() => "displayFailed" as const);
  if (result !== "skipped") {
    lastProblem = result === "submitted" ? null : result;
    window.dispatchEvent(new Event(NOTIFICATION_STATUS_EVENT));
  }
  return result;
}

async function submitNotification(body: string, options: { key: string; url: string; test?: boolean }): Promise<NotificationResult> {
  const eligible = () => options.test || (readLocalPreferences().browserNotifications && document.visibilityState !== "visible");
  if (!eligible()) return "skipped";
  const problem = notificationProblem();
  if (problem) return problem;
  if (Notification.permission !== "granted") return "dismissed";
  let worker: ServiceWorker | null;
  try { worker = await activeWorker(); }
  catch { return "workerUnavailable"; }
  if (!worker) return "workerUnavailable";
  if (!eligible()) return "skipped";
  const channel = new MessageChannel();
  try {
    return await bounded(new Promise<NotificationResult>((resolve) => {
      channel.port1.onmessage = ({ data }: MessageEvent<unknown>) => {
        resolve(data === "submitted" || data === "skipped" ? data : "displayFailed");
      };
      worker.postMessage({ type: "nanobot:notify", body, ...options }, [channel.port2]);
    }));
  } catch { return "displayFailed"; }
  finally { channel.port1.close(); }
}
