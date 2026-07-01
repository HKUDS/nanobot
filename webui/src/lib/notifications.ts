const TURN_NOTIFICATIONS_KEY = "nanobot-webui.turn-notifications.v1";

export type BrowserNotificationPermission = NotificationPermission | "unsupported";

export function getTurnNotificationsEnabled(): boolean {
  try {
    return window.localStorage.getItem(TURN_NOTIFICATIONS_KEY) === "1";
  } catch {
    return false;
  }
}

export function setTurnNotificationsEnabled(enabled: boolean): void {
  try {
    if (enabled) {
      window.localStorage.setItem(TURN_NOTIFICATIONS_KEY, "1");
    } else {
      window.localStorage.removeItem(TURN_NOTIFICATIONS_KEY);
    }
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

export function getBrowserNotificationPermission(): BrowserNotificationPermission {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return window.Notification.permission;
}

export async function requestTurnNotificationsPermission(): Promise<BrowserNotificationPermission> {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  if (window.Notification.permission !== "default") return window.Notification.permission;
  return window.Notification.requestPermission();
}

export function showTurnCompleteNotification({
  chatId,
  title,
  body,
}: {
  chatId: string;
  title: string;
  body: string;
}): boolean {
  if (!getTurnNotificationsEnabled()) return false;
  if (getBrowserNotificationPermission() !== "granted") return false;
  try {
    const options: NotificationOptions & { renotify?: boolean } = {
      body,
      icon: "/brand/nanobot_icon.png",
      renotify: true,
      tag: `nanobot-turn-${chatId}`,
    };
    new window.Notification(title, options);
    return true;
  } catch {
    return false;
  }
}

export function showTestNotification(title: string, body: string): boolean {
  if (getBrowserNotificationPermission() !== "granted") return false;
  try {
    new window.Notification(title, {
      body,
      icon: "/brand/nanobot_icon.png",
      tag: "nanobot-test-notification",
    });
    return true;
  } catch {
    return false;
  }
}
