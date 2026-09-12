import { CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { SessionAutomationJob } from "@/lib/types";
import { fetchAutomationRunResult } from "@/lib/api";
import { cn } from "@/lib/utils";

export type AutomationRunRecord = NonNullable<SessionAutomationJob["state"]["run_history"]>[number];

export function AutomationRunDialog({ token = "", job, run, locale, open, onOpenChange, onCloseAutoFocus }: {
  token?: string;
  job: SessionAutomationJob;
  run: AutomationRunRecord;
  locale: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus: (event: Event) => void;
}) {
  const { t } = useTranslation();
  const [attempt, setAttempt] = useState(0);
  const kind = job.kind === "local_trigger" ? "local_trigger" : "cron";
  const resultKey = JSON.stringify([token, kind, job.id, run.run_at_ms, attempt]);
  const [result, setResult] = useState<{
    key: string; status: "loading" | "loaded" | "error"; response: string | null;
  } | null>(null);
  useEffect(() => {
    if (!open) return;
    if (!token) {
      setResult({ key: resultKey, status: "loaded", response: null });
      return;
    }
    const controller = new AbortController();
    setResult({ key: resultKey, status: "loading", response: null });
    void fetchAutomationRunResult(token, job.id, run.run_at_ms, kind, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setResult({ key: resultKey, status: "loaded", response: payload.response });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setResult({ key: resultKey, status: "error", response: null });
        }
      });
    return () => controller.abort();
  }, [job.id, kind, open, resultKey, run.run_at_ms, token]);
  const currentResult = result?.key === resultKey ? result : null;
  const failed = run.status === "error";
  const status = run.status === "ok"
    ? t("settings.automations.status.completed")
    : failed ? t("settings.automations.status.failed")
      : run.status === "skipped" ? t("settings.automations.skipped")
        : t("settings.automations.calendar.recorded");
  const duration = run.duration_ms;
  const chatHref = job.origin?.channel === "websocket" && job.origin.session_key
    ? `#/chat/${encodeURIComponent(job.origin.session_key)}` : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        {...(!open ? { inert: "", "aria-hidden": true } : {})}
        className="flex max-h-[calc(100dvh-2rem)] max-w-[520px] flex-col gap-0 p-0 text-sm font-normal leading-normal text-foreground"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader className="shrink-0 px-6 pb-4 pr-14 pt-5 text-left">
          <DialogTitle className="min-w-0 break-words text-lg font-medium leading-snug tracking-normal text-balance">
            {job.name || job.id}
          </DialogTitle>
          <DialogDescription className="text-sm font-normal text-muted-foreground">
            <time dateTime={new Date(run.run_at_ms).toISOString()}>
              {new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(run.run_at_ms)}
            </time>
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-6 pb-6">
          <dl className="space-y-3">
            <div className="flex items-start justify-between gap-4">
              <dt className="text-muted-foreground">{t("settings.automations.runDetails.result")}</dt>
              <dd className={cn("flex items-center gap-1.5 text-end", failed && "text-destructive")}>
                {failed ? <CircleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={1.5} aria-hidden /> : null}
                {status}
              </dd>
            </div>
            {duration != null && Number.isFinite(duration) && duration >= 0 ? (
              <div className="flex items-start justify-between gap-4">
                <dt className="text-muted-foreground">{t("settings.automations.runDetails.duration")}</dt>
                <dd className="text-end tabular-nums">{new Intl.NumberFormat(locale, {
                  style: "unit", unit: "second", unitDisplay: "short",
                  maximumFractionDigits: duration < 1000 ? 3 : 1,
                }).format(duration / 1000)}</dd>
              </div>
            ) : null}
          </dl>
          {run.error ? <p className={cn("whitespace-pre-wrap break-words [overflow-wrap:anywhere]", failed && "text-destructive")}>{run.error}</p> : null}
          {!currentResult || currentResult.status === "loading" ? (
            <p role="status" className="text-muted-foreground">{t("settings.automations.runDetails.loading")}</p>
          ) : currentResult.status === "error" ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p role="alert" className="text-muted-foreground">{t("settings.automations.runDetails.loadError")}</p>
              <Button variant="ghost" size="sm" onClick={() => setAttempt((value) => value + 1)}>
                {t("settings.automations.runDetails.retry")}
              </Button>
            </div>
          ) : currentResult.response?.trim() ? (
            <MarkdownText className="min-w-0 text-sm [overflow-wrap:anywhere]">{currentResult.response}</MarkdownText>
          ) : (
            <p className="text-muted-foreground">{t(currentResult.response === null
              ? "settings.automations.runDetails.noOutput"
              : "settings.automations.runDetails.emptyOutput")}</p>
          )}
        </div>
        {chatHref ? (
          <div className="flex shrink-0 justify-end border-t border-border/45 px-6 py-3">
            <Button asChild variant="ghost" size="sm" className="font-normal text-muted-foreground">
              <a href={chatHref}>{t("settings.automations.emptyAction")}</a>
            </Button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
