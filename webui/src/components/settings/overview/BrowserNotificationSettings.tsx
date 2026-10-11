import { useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import { Button } from "@/components/ui/button";
import { enableBrowserNotifications, lastNotificationProblem, NOTIFICATION_STATUS_EVENT, notificationProblem, showBrowserNotification, type NotificationResult } from "@/lib/browser-notifications";
import type { LocalPreferences } from "@/lib/local-preferences";

export function BrowserNotificationSettings({ localPrefs, onChangeLocalPrefs }: {
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const hintId = useId();
  const [problem, setProblem] = useState(notificationProblem);
  const [feedback, setFeedback] = useState<NotificationResult | null>(lastNotificationProblem);
  const [busy, setBusy] = useState(false);
  const operation = useRef(0);
  useEffect(() => {
    const refresh = () => {
      setProblem(notificationProblem());
      setFeedback((current) => current === "submitted" || current === "displayFailed" || current === "workerUnavailable" ? current : null);
    };
    const deliveryStatus = () => setFeedback(lastNotificationProblem());
    window.addEventListener("focus", refresh);
    window.addEventListener(NOTIFICATION_STATUS_EVENT, deliveryStatus);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      operation.current++;
      window.removeEventListener("focus", refresh);
      window.removeEventListener(NOTIFICATION_STATUS_EVENT, deliveryStatus);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  const enabled = localPrefs.browserNotifications && !problem && Notification.permission === "granted";
  const status = problem || feedback || (localPrefs.browserNotifications && !enabled ? "dismissed" : null);
  async function toggle(value: boolean) {
    const id = ++operation.current;
    setFeedback(null);
    if (!value) {
      onChangeLocalPrefs((previous) => ({ ...previous, browserNotifications: false }));
      return;
    }
    setBusy(true);
    const result = await enableBrowserNotifications();
    if (id !== operation.current) return;
    setBusy(false);
    setProblem(notificationProblem());
    setFeedback(result);
    if (!result) onChangeLocalPrefs((previous) => ({ ...previous, browserNotifications: true }));
  }
  async function test() {
    const id = ++operation.current;
    setBusy(true);
    const result = await showBrowserNotification(t("settings.notifications.testBody"), {
      key: `test:${crypto.randomUUID()}`, url: `${window.location.origin}/#/settings?section=appearance`, test: true,
    });
    if (id !== operation.current) return;
    setBusy(false);
    setProblem(notificationProblem());
    setFeedback(result);
  }
  return <div>
    <SettingsRow title={t("settings.rows.browserNotifications")}>
      <ToggleButton checked={localPrefs.browserNotifications} disabled={busy || (!!problem && !localPrefs.browserNotifications)}
        onChange={(value) => void toggle(value)}
        ariaLabel={t("settings.rows.browserNotifications")} aria-describedby={hintId}
        label={t(localPrefs.browserNotifications ? "settings.values.on" : "settings.values.off")} />
    </SettingsRow>
    <div id={hintId} className="px-[var(--settings-inset,16px)] pb-4 text-[12px] leading-5 text-muted-foreground">
      <p>{t("settings.help.browserNotifications")}</p>
      <p role="status" aria-live="polite">{busy ? t("settings.notifications.waiting") : status && status !== "skipped" ? t(`settings.notifications.${status}`) : null}</p>
      {enabled && <Button variant="ghost" size="sm" className="mt-1 h-8 px-2 text-xs" disabled={busy} onClick={() => void test()}>{t("settings.notifications.test")}</Button>}
    </div>
  </div>;
}
