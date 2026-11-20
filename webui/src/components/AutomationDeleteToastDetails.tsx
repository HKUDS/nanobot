import type { TFunction } from "i18next";
import { MessageSquare } from "lucide-react";
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
    <div className="max-h-64 divide-y divide-border/60 overflow-y-auto overscroll-contain">
      {groups.map(({ item, jobs }) => (
        <section key={item.key} className="px-3.5 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <MessageSquare
                aria-hidden="true"
                className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80"
                strokeWidth={1.8}
              />
              <span className="min-w-0 truncate text-[13px] font-medium leading-5 text-foreground">
                {item.label}
              </span>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={t("toast.excludeSessionAria", { title: item.label })}
              onClick={() => onExcludeSession(item.key)}
              className="h-6 shrink-0 rounded-full border border-border/70 bg-background/70 px-2.5 text-[11.5px] font-medium leading-4 text-muted-foreground transition-colors hover:border-border hover:bg-muted/75 hover:text-foreground"
            >
              {t("toast.excludeSession")}
            </Button>
          </div>
          <ul className="mt-1.5 space-y-0.5 pl-[1.375rem]">
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
                  className="flex items-center justify-between gap-3 rounded-lg px-2 py-1 text-[12.5px] leading-5 transition-colors hover:bg-muted/45"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusDotClass)}
                    />
                    <span className="min-w-0 truncate text-foreground/90">
                      {job.name || job.id}
                    </span>
                  </div>
                  {!job.enabled ? (
                    <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium leading-4 text-muted-foreground">
                      {t("settings.automations.status.paused")}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11.5px] leading-4 tabular-nums text-muted-foreground">
                      {formatCompactSchedule(job, locale, t)}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
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
