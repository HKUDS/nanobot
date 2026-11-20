import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { currentLocale } from "@/i18n";
import { fmtDateTime } from "@/lib/format-time";
import type { SessionAutomationJob } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { SidebarDeleteItem } from "@/components/ChatList";

export interface AutomationDeleteSessionGroup {
  item: SidebarDeleteItem;
  jobs: SessionAutomationJob[];
}

export function AutomationDeleteToastDetails({
  groups,
  onExcludeSession,
}: {
  groups: AutomationDeleteSessionGroup[];
  onExcludeSession: (key: string) => void;
}) {
  const { t } = useTranslation();
  const locale = currentLocale();

  return (
    <div className="max-h-64 divide-y divide-border/50 overflow-y-auto overscroll-contain">
      {groups.map(({ item, jobs }) => (
        <div key={item.key} className="px-1.5 py-2 first:pt-1 last:pb-1">
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-[12.5px] font-medium text-foreground">
              {item.label}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={t("toast.excludeSessionAria", { title: item.label })}
              onClick={() => onExcludeSession(item.key)}
              className="h-6 shrink-0 px-2 text-[11.5px] font-medium text-muted-foreground hover:text-foreground"
            >
              {t("toast.excludeSession")}
            </Button>
          </div>
          <ul className="mt-1.5 space-y-1">
            {jobs.map((job) => {
              const needsAttention = job.state.last_status === "error" || Boolean(job.state.last_error);
              const statusDotClass = job.enabled
                ? needsAttention
                  ? "bg-destructive"
                  : "bg-emerald-500"
                : "bg-muted-foreground/35";
              return (
                <li
                  key={job.id}
                  className="flex items-center gap-2 rounded-control bg-muted/45 px-2 py-1.5 text-[12px]"
                >
                  <span aria-hidden="true" className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusDotClass)} />
                  <span className="min-w-0 flex-1 truncate text-foreground">
                    {job.name || job.id}
                  </span>
                  {!job.enabled ? (
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10.5px] leading-tight text-muted-foreground">
                      {t("settings.automations.status.paused")}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {formatCompactSchedule(job, locale, t)}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function formatCompactSchedule(
  job: SessionAutomationJob,
  locale: string,
  t: TFunction,
): string {
  if (job.schedule.kind === "at" && job.schedule.at_ms) {
    return t("settings.automations.schedule.at", { time: fmtDateTime(job.schedule.at_ms, locale) });
  }
  if (job.schedule.kind === "every" && job.schedule.every_ms) {
    return t("settings.automations.schedule.every", {
      duration: formatDuration(job.schedule.every_ms, locale),
    });
  }
  if (job.schedule.kind === "cron" && job.schedule.expr) {
    return job.schedule.expr;
  }
  if (job.kind === "local_trigger" || job.schedule.kind === "local" || job.payload.kind === "local_trigger") {
    return t("settings.automations.commandCondition");
  }
  return t("settings.automations.schedule.custom");
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
