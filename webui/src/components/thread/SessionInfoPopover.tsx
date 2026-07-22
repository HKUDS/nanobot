import { useState } from "react";
import {
  CalendarClock,
  CircleAlert,
  ListTodo,
  RefreshCcw,
} from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSessionAutomationJobs } from "@/hooks/useSessionAutomationJobs";
import { currentLocale } from "@/i18n";
import { fmtDateTime } from "@/lib/format";
import type { SessionAutomationJob } from "@/lib/types";
import { cn } from "@/lib/utils";

const RELATIVE_THRESHOLDS: [number, Intl.RelativeTimeFormatUnit][] = [
  [60, "second"],
  [60, "minute"],
  [24, "hour"],
  [7, "day"],
  [4.345, "week"],
  [12, "month"],
  [Number.POSITIVE_INFINITY, "year"],
];

interface SessionInfoPopoverProps {
  sessionKey: string;
  token: string;
  title: string;
}

export function SessionInfoPopover({ sessionKey, token, title }: SessionInfoPopoverProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const { jobs, loading, loadFailed, now } = useSessionAutomationJobs(open, token, sessionKey);
  const automationContent = loading ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-muted/45 px-3 py-3 text-[12.5px] text-muted-foreground">
      <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
      {t("thread.sessionInfo.loading")}
    </div>
  ) : loadFailed ? (
    <div className="flex items-center gap-2 rounded-[16px] bg-destructive/10 px-3 py-3 text-[12.5px] text-destructive">
      <CircleAlert className="h-3.5 w-3.5" />
      {t("thread.sessionInfo.loadFailed")}
    </div>
  ) : jobs.length ? (
    <div className="space-y-1.5">
      {jobs.map((job) => (
        <AutomationRow key={job.id} job={job} now={now} />
      ))}
    </div>
  ) : (
    <div className="rounded-[16px] bg-muted/35 px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      {t("thread.sessionInfo.empty")}
    </div>
  );

  return (
    <DropdownMenu modal={false} open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.sessionInfo")}
          className={cn(
            "host-no-drag h-8 w-8 rounded-full text-muted-foreground/85",
            "hover:bg-accent/40 hover:text-foreground",
          )}
        >
          <ListTodo className="h-4 w-4 stroke-[1.75]" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={8}
        className="w-[min(23rem,calc(100vw-1.5rem))] rounded-[24px] p-0"
      >
        <div className="space-y-3 px-4 py-3.5">
          <div className="min-w-0">
            <div className="text-[12px] font-normal text-muted-foreground/75">
              {t("thread.sessionInfo.title")}
            </div>
            <div className="mt-0.5 truncate text-[14px] font-medium text-foreground">
              {title || t("thread.sessionInfo.untitled")}
            </div>
          </div>

          <div className="h-px bg-border/45" />

          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <CalendarClock className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80" />
              <span className="truncate text-[13px] font-medium text-foreground">
                {t("thread.sessionInfo.automations")}
              </span>
            </div>
            <span className="rounded-full bg-muted/70 px-2 py-0.5 text-[11px] text-muted-foreground">
              {t("thread.sessionInfo.count", { count: jobs.length })}
            </span>
          </div>

          {automationContent}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function AutomationRow({ job, now }: { job: SessionAutomationJob; now: number }) {
  const { t } = useTranslation("common");
  const schedule = formatSchedule(job, t);
  const nextRun = formatNextRun(job, t, now);
  const statusClass = job.enabled
    ? job.state.last_status === "error"
      ? "bg-destructive"
      : "bg-emerald-500"
    : "bg-muted-foreground/35";

  return (
    <div className="rounded-[16px] px-3 py-2.5 transition-colors hover:bg-muted/40">
      <div className="flex items-start gap-2.5">
        <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", statusClass)} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[13px] font-medium text-foreground">{job.name}</span>
            {!job.enabled ? (
              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                {t("thread.sessionInfo.disabled")}
              </span>
            ) : null}
          </div>
          <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-muted-foreground">
            {job.payload.message}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground/80">
            <span>{schedule}</span>
            <span aria-hidden>·</span>
            <span title={nextRun.title}>{nextRun.label}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatSchedule(job: SessionAutomationJob, t: TFunction) {
  const locale = currentLocale();
  if (isLocalTriggerAutomation(job)) {
    return t("thread.sessionInfo.schedule.local");
  }
  if (job.schedule.kind === "at" && job.schedule.at_ms) {
    return t("thread.sessionInfo.schedule.at", { time: fmtDateTime(job.schedule.at_ms, locale) });
  }
  if (job.schedule.kind === "every" && job.schedule.every_ms) {
    return t("thread.sessionInfo.schedule.every", {
      duration: formatDuration(job.schedule.every_ms, locale),
    });
  }
  if (job.schedule.kind === "cron" && job.schedule.expr) {
    return job.schedule.tz
      ? t("thread.sessionInfo.schedule.cronWithTz", {
          expr: job.schedule.expr,
          tz: job.schedule.tz,
        })
      : t("thread.sessionInfo.schedule.cron", { expr: job.schedule.expr });
  }
  return t("thread.sessionInfo.schedule.unknown");
}

function formatNextRun(job: SessionAutomationJob, t: TFunction, now: number) {
  const locale = currentLocale();
  if (!job.enabled) {
    return { label: t("thread.sessionInfo.next.disabled"), title: "" };
  }
  if (job.state.pending) {
    return { label: t("thread.sessionInfo.next.pending"), title: "" };
  }
  if (isLocalTriggerAutomation(job)) {
    return { label: t("thread.sessionInfo.next.local"), title: "" };
  }
  const next = job.state.next_run_at_ms;
  if (!next) {
    return { label: t("thread.sessionInfo.next.none"), title: "" };
  }
  return {
    label: t("thread.sessionInfo.next.label", { time: relativeTimeFrom(next, now, locale) }),
    title: fmtDateTime(next, locale),
  };
}

function isLocalTriggerAutomation(job: SessionAutomationJob): boolean {
  return job.kind === "local_trigger"
    || job.payload.kind === "local_trigger"
    || job.schedule.kind === "local";
}

function relativeTimeFrom(value: number, now: number, locale: string): string {
  let delta = (value - now) / 1000;
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [step, unit] of RELATIVE_THRESHOLDS) {
    if (Math.abs(delta) < step) {
      return formatter.format(Math.round(delta), unit);
    }
    delta /= step;
  }
  return formatter.format(Math.round(delta), "year");
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
