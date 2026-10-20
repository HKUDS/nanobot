import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { NOTIFICATION_OPEN_EVENT, notificationChatUrl, reconcileNotificationPermission, showBrowserNotification, taskNoticeKey } from "@/lib/browser-notifications";
import type { NanobotClient } from "@/lib/nanobot-client";

export function BrowserNotifications({ client }: { client: Pick<NanobotClient, "onTaskNotice"> }) {
  const { t } = useTranslation();
  useEffect(() => client.onTaskNotice((notice) => {
    const key = taskNoticeKey(notice);
    if (!key) return;
    const event = notice.event;
    const outcome = event.event === "turn_end"
      ? event.outcome === "failed" ? "failed" : event.outcome === "interrupted" ? "interrupted" : "completed"
      : event.status === "failed" ? "failed" : "interrupted";
    // Never expose conversation text, titles, model errors, or paths on a lock screen.
    void showBrowserNotification(t(`settings.notifications.${outcome}`), {
      key, url: notificationChatUrl(event.chat_id, notice.temporary),
    });
  }), [client, t]);
  return null;
}

// Permission and click ownership survives authentication and route transitions.
export function useBrowserNotificationLifecycle() {
  useEffect(() => {
    reconcileNotificationPermission();
    window.addEventListener("focus", reconcileNotificationPermission);
    document.addEventListener("visibilitychange", reconcileNotificationPermission);
    return () => {
      window.removeEventListener("focus", reconcileNotificationPermission);
      document.removeEventListener("visibilitychange", reconcileNotificationPermission);
    };
  }, []);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const navigate = (event: MessageEvent<unknown>) => {
      const data = event.data as { type?: string; url?: unknown } | null;
      if (event.source !== navigator.serviceWorker.controller || data?.type !== "nanobot:notification-click" || typeof data.url !== "string") return;
      let url: URL;
      try { url = new URL(data.url); } catch { return; }
      if (url.origin !== window.location.origin || url.username || url.password || url.search || url.pathname !== "/") return;
      if (!/^#\/(?:chat|temporary)\/[^?]+$/.test(url.hash)
        && url.hash !== "#/settings?section=notifications"
        && url.hash !== "#/settings?section=appearance") return;
      window.location.hash = url.hash;
      window.dispatchEvent(new Event(NOTIFICATION_OPEN_EVENT));
    };
    navigator.serviceWorker.addEventListener("message", navigate);
    return () => navigator.serviceWorker.removeEventListener("message", navigate);
  }, []);
}
