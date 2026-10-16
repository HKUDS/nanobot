import { useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import { Button } from "@/components/ui/button";
import { enableBrowserNotifications, lastNotificationProblem, NOTIFICATION_STATUS_EVENT, notificationProblem, notificationWorkerProblem, showBrowserNotification, type NotificationResult } from "@/lib/browser-notifications";
import type { LocalPreferences } from "@/lib/local-preferences";

export function BrowserNotificationSettings({ localPrefs, onChangeLocalPrefs }: {
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const hintId = useId();
  const [problem, setProblem] = useState(notificationProblem);
  const [workerProblem, setWorkerProblem] = useState<"workerUnavailable" | null>(null);
  const [revoked, setRevoked] = useState(false);
  const [feedback, setFeedback] = useState<NotificationResult | null>(lastNotificationProblem);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const operation = useRef(0);
  const workerCheck = useRef(0);
  const refreshRef = useRef(() => {});

  useEffect(() => {
    const refresh = () => {
      const next = notificationProblem();
      setProblem(next);
      if (localPrefs.browserNotifications && (typeof Notification === "undefined" || Notification.permission !== "granted")) {
        setRevoked(typeof Notification !== "undefined");
        onChangeLocalPrefs((previous) => ({ ...previous, browserNotifications: false }));
      }
      const id = ++workerCheck.current;
      setChecking(!next);
      if (!next) {
        void notificationWorkerProblem().then((value) => {
          if (id === workerCheck.current) {
            setWorkerProblem(value);
            setChecking(false);
          }
        });
      }
    };
    refreshRef.current = refresh;
    const deliveryStatus = () => { setFeedback(lastNotificationProblem()); refresh(); };
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener(NOTIFICATION_STATUS_EVENT, deliveryStatus);
    document.addEventListener("visibilitychange", refresh);
    navigator.serviceWorker?.addEventListener("controllerchange", refresh);
    return () => {
      workerCheck.current++;
      window.removeEventListener("focus", refresh);
      window.removeEventListener(NOTIFICATION_STATUS_EVENT, deliveryStatus);
      document.removeEventListener("visibilitychange", refresh);
      navigator.serviceWorker?.removeEventListener("controllerchange", refresh);
    };
  }, [localPrefs.browserNotifications, onChangeLocalPrefs]);
  useEffect(() => () => { operation.current++; }, []);

  const granted = typeof Notification !== "undefined" && Notification.permission === "granted";
  const enabled = localPrefs.browserNotifications && granted;
  const detail = revoked && !granted ? "revoked" : problem || feedback || workerProblem;
  const status = busy || checking ? "statusBusy"
    : revoked && !granted ? "statusRevoked"
    : problem === "denied" ? "statusBlocked"
    : problem === "unsupported" || problem === "insecure" ? "statusUnavailable"
    : problem === "workerUnavailable" || workerProblem || feedback === "workerUnavailable" ? "statusWorker"
    : feedback === "displayFailed" || feedback === "permissionFailed" ? "statusError"
    : enabled ? "statusOn" : granted ? "statusOff" : "statusPermission";

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
    setWorkerProblem(result === "workerUnavailable" ? result : null);
    setFeedback(result);
    if (!result) {
      setRevoked(false);
      onChangeLocalPrefs((previous) => ({ ...previous, browserNotifications: true }));
    }
  }
  async function test() {
    const id = ++operation.current;
    setBusy(true);
    const result = await showBrowserNotification(t("settings.notifications.testBody"), {
      key: `test:${crypto.randomUUID()}`, url: `${window.location.origin}/#/settings?section=notifications`, test: true,
    });
    if (id !== operation.current) return;
    setBusy(false);
    setProblem(notificationProblem());
    setFeedback(result);
  }
  return <div>
    <SettingsRow title={t("settings.rows.browserNotifications")}>
      <>
        <span className="me-3 rounded-full bg-muted px-2 py-0.5 text-[11px] leading-5 text-muted-foreground">{t(`settings.notifications.${status}`)}</span>
        <ToggleButton checked={enabled} disabled={busy || (!!problem && !localPrefs.browserNotifications)}
          onChange={(value) => void toggle(value)}
          ariaLabel={t("settings.rows.browserNotifications")} aria-describedby={hintId}
          label={t(enabled ? "settings.values.on" : "settings.values.off")} />
      </>
    </SettingsRow>
    <div id={hintId} className="settings-list-inset pb-4 text-[12px] leading-5 text-muted-foreground">
      <p>{t("settings.help.browserNotifications")}</p>
      <p role="status" aria-live="polite" className="mt-1">{busy || checking ? t("settings.notifications.waiting") : detail && detail !== "skipped" ? t(`settings.notifications.${detail}`) : null}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={busy || checking || !enabled || !!problem || !!workerProblem} onClick={() => void test()}>{t("settings.notifications.test")}</Button>
        {(problem || workerProblem || revoked || feedback === "workerUnavailable") && <Button variant="ghost" size="sm" disabled={busy || checking} onClick={() => { setFeedback(null); refreshRef.current(); }}>{t("settings.notifications.retry")}</Button>}
      </div>
    </div>
  </div>;
}
