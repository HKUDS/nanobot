import { useEffect, useId, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { BellRing, Loader2 } from "lucide-react";
import { SettingsRow } from "@/components/settings/shared/SettingsControls";
import { ToggleButton } from "@/components/ui/toggle-button";
import { Button } from "@/components/ui/button";
import { HoverHint } from "@/components/ui/tooltip";
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
  }, []);
  useEffect(() => () => { operation.current++; }, []);

  const granted = typeof Notification !== "undefined" && Notification.permission === "granted";
  const enabled = localPrefs.browserNotifications && granted;
  const revoked = feedback === "revoked" && typeof Notification !== "undefined" && !granted;
  const detail = revoked ? "revoked" : problem || (feedback === "revoked" ? null : feedback) || workerProblem;
  const message = busy || checking ? t("settings.notifications.waiting")
    : detail && detail !== "skipped" ? t(`settings.notifications.${detail}`) : null;
  const canRetry = !!(problem || workerProblem || revoked || feedback === "workerUnavailable");

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
    setFeedback(lastNotificationProblem() ?? result);
  }
  return <div>
    <SettingsRow title={t("settings.rows.browserNotifications")}
      description={t("settings.help.browserNotifications")}>
      <>
        {enabled && <HoverHint content={t("settings.notifications.test")}>
          <Button type="button" variant="ghost" size="icon" aria-label={t("settings.notifications.test")}
            className="-my-1 me-3 h-11 w-11 shrink-0 text-muted-foreground sm:my-0 sm:h-9 sm:w-9"
            disabled={busy || checking || !!problem || !!workerProblem} onClick={() => void test()}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden /> : <BellRing className="h-4 w-4" aria-hidden />}
          </Button>
        </HoverHint>}
        <ToggleButton checked={enabled} disabled={busy || (!!problem && !localPrefs.browserNotifications)}
          onChange={(value) => void toggle(value)}
          ariaLabel={t("settings.rows.browserNotifications")} aria-describedby={message ? hintId : undefined}
          label={t(enabled ? "settings.values.on" : "settings.values.off")} />
      </>
    </SettingsRow>
    <div className={message || canRetry ? "settings-list-inset pb-3 text-[12px] leading-5 text-muted-foreground" : undefined}>
      <p id={hintId} role="status" aria-live="polite" aria-atomic="true">{message}</p>
      {canRetry && <Button type="button" variant="ghost" size="sm" disabled={busy || checking}
        className="-ms-2 mt-1 h-8 rounded-full px-2 text-[12px] text-muted-foreground"
        onClick={() => { setFeedback(null); refreshRef.current(); }}>{t("settings.notifications.retry")}</Button>}
    </div>
  </div>;
}
