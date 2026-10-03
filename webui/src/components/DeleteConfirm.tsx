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
  count?: number;
  automations?: SessionAutomationJob[];
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteConfirm({
  open,
  title,
  count = 1,
  automations = [],
  onCancel,
  onConfirm,
}: DeleteConfirmProps) {
  const { t } = useTranslation();
  const locale = currentLocale();
  const hasAutomations = automations.length > 0;
  const multiple = count > 1;
  const visibleAutomations = automations.slice(0, 4);
  const hiddenCount = Math.max(0, automations.length - visibleAutomations.length);
  return (
    <AlertDialog open={open} onOpenChange={(o) => (!o ? onCancel() : undefined)}>
      <AlertDialogContent
        className="w-[min(calc(100vw-2rem),24rem)] gap-0 p-5 text-center"
      >
        <AlertDialogHeader className="items-center space-y-0 text-center">
          <Trash2
            className="mb-4 h-6 w-6 text-destructive"
            strokeWidth={1.8}
            aria-hidden
          />
          <AlertDialogTitle className="text-center text-[20px] font-semibold leading-tight tracking-[-0.02em] text-foreground">
            {multiple
              ? t("deleteConfirm.titleMany", {
                  defaultValue: "Delete {{count}} conversations?",
                  count,
                })
              : t("deleteConfirm.title", { title })}
          </AlertDialogTitle>
          <AlertDialogDescription className="mt-3 max-w-[17rem] text-center text-[14px] leading-6 text-muted-foreground">
            {hasAutomations
              ? multiple
                ? t("deleteConfirm.automationsDescriptionMany", {
                    defaultValue: "Linked automations will also be deleted.",
                  })
                : t("deleteConfirm.automationsDescription")
              : multiple
                ? t("deleteConfirm.descriptionMany", {
                    defaultValue: "This action cannot be undone.",
                  })
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
        <AlertDialogFooter className="mt-6 !grid grid-cols-1 gap-2 sm:grid-cols-2">
          <AlertDialogCancel
            onClick={onCancel}
            className="mt-0 w-full min-w-0"
          >
            {t("deleteConfirm.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="w-full min-w-0 !whitespace-normal bg-destructive text-center text-destructive-foreground hover:bg-destructive/90"
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
  if (job.schedule.kind === "local" || job.payload.kind === "local_trigger") {
    return t("deleteConfirm.schedule.local", { defaultValue: "Local trigger" });
  }
  return t("deleteConfirm.schedule.unknown");
}

function formatAutomationNextRun(
  job: SessionAutomationJob,
  t: TFunction,
  locale: string,
): string {
  if (!job.enabled) return t("deleteConfirm.next.disabled");
  if (job.schedule.kind === "local" || job.payload.kind === "local_trigger") {
    return t("deleteConfirm.next.local", { defaultValue: "Waiting for trigger" });
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
