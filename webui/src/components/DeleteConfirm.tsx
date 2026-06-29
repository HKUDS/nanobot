import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { TFunction } from "i18next";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { currentLocale } from "@/i18n";
import { fmtDateTime } from "@/lib/format";
import type { SessionAutomationJob } from "@/lib/types";

interface DeleteConfirmProps {
  open: boolean;
  title: string;
  automations?: SessionAutomationJob[];
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteConfirm({
  open,
  title,
  automations = [],
  onCancel,
  onConfirm,
}: DeleteConfirmProps) {
  const { t } = useTranslation();
  const locale = currentLocale();
  const hasAutomations = automations.length > 0;
  const visibleAutomations = automations.slice(0, 4);
  const hiddenCount = Math.max(0, automations.length - visibleAutomations.length);
  return (
    <AlertDialog open={open} onOpenChange={(o) => (!o ? onCancel() : undefined)}>
      <AlertDialogContent
        className="w-[min(calc(100vw-2rem),24rem)] gap-0 rounded-[28px] border border-white/70 bg-card/95 p-5 text-center shadow-[0_24px_80px_rgba(15,23,42,0.20)] backdrop-blur-xl data-[state=open]:zoom-in-95 sm:rounded-[28px]"
      >
        <AlertDialogHeader className="items-center space-y-0 text-center">
          <div className="mb-5 grid h-16 w-16 place-items-center rounded-full bg-destructive/10 text-destructive">
            <div className="grid h-9 w-9 place-items-center rounded-full border border-destructive/20 bg-destructive/5">
              <Trash2 className="h-5 w-5" strokeWidth={2.4} aria-hidden />
            </div>
          </div>
          <AlertDialogTitle className="text-center text-[20px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
            {t("deleteConfirm.title", { title })}
          </AlertDialogTitle>
          <AlertDialogDescription className="mt-3 max-w-[17rem] text-center text-[14px] leading-6 text-muted-foreground">
            {hasAutomations
              ? t("deleteConfirm.automationsDescription")
              : t("deleteConfirm.description")}
          </AlertDialogDescription>
          {hasAutomations ? (
            <div className="mt-4 max-h-40 w-full overflow-y-auto rounded-2xl bg-muted/55 px-3 py-2 text-left">
              {visibleAutomations.map((job) => (
                <div key={job.id} className="min-w-0 py-1.5">
                  <div className="truncate text-[13px] font-medium leading-5 text-foreground">
                    {job.name || job.id}
                  </div>
                  <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] leading-5 text-muted-foreground">
                    <span className="truncate">
                      {formatAutomationSchedule(job, t, locale)}
                    </span>
                    <span aria-hidden>·</span>
                    <span className="truncate">{formatAutomationNextRun(job, t, locale)}</span>
                  </div>
                </div>
              ))}
              {hiddenCount > 0 ? (
                <div className="text-[13px] leading-6 text-muted-foreground">
                  {t("deleteConfirm.moreAutomations", {
                    count: hiddenCount,
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter className="mt-7 !grid grid-cols-1 gap-3 space-x-0 sm:grid-cols-2 sm:space-x-0">
          <AlertDialogCancel
            onClick={onCancel}
            className="mt-0 h-11 w-full min-w-0 rounded-full border-0 bg-muted/70 px-5 text-[15px] font-semibold text-foreground shadow-none hover:bg-muted"
          >
            {t("deleteConfirm.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="h-11 w-full min-w-0 !whitespace-normal rounded-full bg-destructive px-5 text-center text-[15px] font-semibold text-destructive-foreground shadow-[0_10px_25px_rgba(239,68,68,0.28)] hover:bg-destructive/90"
          >
            {hasAutomations
              ? t("deleteConfirm.confirmWithAutomations")
              : t("deleteConfirm.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function formatAutomationSchedule(
  job: SessionAutomationJob,
  t: TFunction,
  locale: string,
): string {
  if (job.schedule.kind === "at" && job.schedule.at_ms) {
    return t("deleteConfirm.schedule.at", { time: fmtDateTime(job.schedule.at_ms, locale) });
  }
  if (job.schedule.kind === "every" && job.schedule.every_ms) {
    return t("deleteConfirm.schedule.every", {
      duration: formatDuration(job.schedule.every_ms, locale),
    });
  }
  if (job.schedule.kind === "cron" && job.schedule.expr) {
    return job.schedule.tz
      ? t("deleteConfirm.schedule.cronWithTz", {
          expr: job.schedule.expr,
          tz: job.schedule.tz,
        })
      : t("deleteConfirm.schedule.cron", { expr: job.schedule.expr });
  }
  if (job.schedule.kind === "external" || job.payload.kind === "external_trigger") {
    return t("deleteConfirm.schedule.external", { defaultValue: "External trigger" });
  }
  return t("deleteConfirm.schedule.unknown");
}

function formatAutomationNextRun(
  job: SessionAutomationJob,
  t: TFunction,
  locale: string,
): string {
  if (!job.enabled) return t("deleteConfirm.next.disabled");
  if (job.schedule.kind === "external" || job.payload.kind === "external_trigger") {
    return t("deleteConfirm.next.external", { defaultValue: "Waiting for trigger" });
  }
  const next = job.state.next_run_at_ms;
  if (!next) return t("deleteConfirm.next.none");
  return t("deleteConfirm.next.label", { time: fmtDateTime(next, locale) });
}

function formatDuration(ms: number, locale: string): string {
  const units: Array<[Intl.NumberFormatOptions["unit"], number]> = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
    ["second", 1000],
  ];
  for (const [unit, size] of units) {
    if (ms >= size && ms % size === 0) {
      return new Intl.NumberFormat(locale, {
        style: "unit",
        unit,
        unitDisplay: "long",
        maximumFractionDigits: 0,
      }).format(ms / size);
    }
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "minute",
    unitDisplay: "long",
    maximumFractionDigits: 1,
  }).format(ms / 60_000);
}
