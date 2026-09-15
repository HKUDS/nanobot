import { useRef, useState } from "react";
import {
  CalendarClock,
  ChevronRight,
  CircleAlert,
  RefreshCcw,
} from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import {
  AutomationDeleteDialog,
  AutomationDetailDialog,
  AutomationEditDialog,
} from "@/components/settings/system/AutomationsSettings";
import type { AutomationAction } from "@/components/settings/system/AutomationsSettings";
import { Button } from "@/components/ui/button";
import { formControlFocusClassName } from "@/components/ui/form-control";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useSessionAutomationJobs } from "@/hooks/useSessionAutomationJobs";
import { currentLocale } from "@/i18n";
import { runAutomationAction, updateAutomation } from "@/lib/api";
import type { WebUIMutationTransport } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type {
  AutomationUpdatePayload,
  SessionAutomationJob,
} from "@/lib/types";
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
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  title: string;
}

export function SessionInfoPopover({ client, sessionKey, token, title }: SessionInfoPopoverProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [inspectedJob, setInspectedJob] = useState<SessionAutomationJob | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingEdit, setPendingEdit] = useState<SessionAutomationJob | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SessionAutomationJob | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const afterDetailClose = useRef<(() => void) | null>(null);
  const surfacesOpen = open || detailOpen || Boolean(pendingEdit) || Boolean(pendingDelete);
  const { jobs, loading, loadFailed, now } = useSessionAutomationJobs(
    surfacesOpen,
    token,
    sessionKey,
  );
  const selectedJob = inspectedJob;

  const inspectJob = (job: SessionAutomationJob) => {
    setActionError(null);
    setInspectedJob(job);
    setOpen(false);
    setDetailOpen(true);
  };
  const handOffDetail = (next: () => void) => {
    afterDetailClose.current = next;
    setDetailOpen(false);
  };
  const updateInspectedJob = (nextJobs: SessionAutomationJob[], id: string) => {
    const nextJob = nextJobs.find((job) => job.id === id);
    if (nextJob) setInspectedJob(nextJob);
  };
  const handleAction = async (action: AutomationAction, job: SessionAutomationJob) => {
    const key = `${action}:${job.id}`;
    setActionKey(key);
    setActionError(null);
    try {
      const payload = await runAutomationAction(client, action, job.id);
      if (action === "delete") {
        setPendingDelete(null);
        setInspectedJob(null);
      } else {
        updateInspectedJob(payload.jobs, job.id);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setActionKey(null);
    }
  };
  const handleEdit = async (job: SessionAutomationJob, values: AutomationUpdatePayload) => {
    const key = `update:${job.id}`;
    setActionKey(key);
    setActionError(null);
    try {
      const payload = await updateAutomation(client, job.id, values);
      updateInspectedJob(payload.jobs, job.id);
      setPendingEdit(null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setActionKey(null);
    }
  };
  const automationContent = loading ? (
    <div className="mx-2 flex items-center gap-2 rounded-floating bg-muted/45 px-3 py-3 text-[12.5px] text-muted-foreground">
      <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
      {t("thread.sessionInfo.loading")}
    </div>
  ) : loadFailed ? (
    <div className="mx-2 flex items-center gap-2 rounded-floating bg-destructive/10 px-3 py-3 text-[12.5px] text-destructive">
      <CircleAlert className="h-3.5 w-3.5" />
      {t("thread.sessionInfo.loadFailed")}
    </div>
  ) : jobs.length ? (
    <div className="space-y-1 px-2">
      {jobs.map((job) => (
        <AutomationRow key={job.id} job={job} now={now} onSelect={inspectJob} />
      ))}
    </div>
  ) : (
    <div className="mx-2 rounded-floating bg-muted/35 px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
      {t("thread.sessionInfo.empty")}
    </div>
  );

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            ref={triggerRef}
            variant="ghost"
            size="icon"
            aria-label={t("thread.header.sessionInfo")}
            className={cn(
              "host-no-drag h-8 w-8 rounded-full text-muted-foreground/85",
              "hover:bg-accent/40 hover:text-foreground",
            )}
          >
            <CalendarClock className="h-4 w-4 stroke-[1.75]" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          sideOffset={8}
          className="w-[min(23rem,calc(100vw-1.5rem))] overflow-hidden p-0"
          onCloseAutoFocus={(event) => {
            if (detailOpen) event.preventDefault();
          }}
        >
          <div className="flex max-h-[min(var(--radix-popover-content-available-height),32rem)] flex-col">
            <div className="px-4 pb-3 pt-3.5">
              <div className="min-w-0">
                <div className="text-[12px] font-normal text-muted-foreground/75">
                  {t("thread.sessionInfo.title")}
                </div>
                <div className="mt-0.5 truncate text-[14px] font-medium text-foreground">
                  {title || t("thread.sessionInfo.untitled")}
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/45 pt-3">
                <span className="truncate text-[13px] font-medium text-foreground">
                  {t("thread.sessionInfo.automations")}
                </span>
                <span className="rounded-full bg-muted/70 px-2 py-0.5 text-[11px] tabular-nums text-muted-foreground">
                  {t("thread.sessionInfo.count", { count: jobs.length })}
                </span>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-2">
              {automationContent}
            </div>

            <div className="border-t border-border/45 p-2">
              <Button asChild variant="ghost" size="sm" className="w-full justify-between px-2 text-[12px] text-muted-foreground">
                <a href="#/automations">
                  {t("thread.sessionInfo.openCalendar")}
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                </a>
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>

      <AutomationDetailDialog
        job={selectedJob}
        open={detailOpen}
        locale={currentLocale()}
        actionKey={actionKey}
        error={actionError}
        onOpenChange={setDetailOpen}
        onAction={handleAction}
        onRequestEdit={(job) => handOffDetail(() => setPendingEdit(job))}
        onRequestDelete={(job) => handOffDetail(() => setPendingDelete(job))}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (detailOpen) return;
          setInspectedJob(null);
          triggerRef.current?.focus({ preventScroll: true });
          const next = afterDetailClose.current;
          afterDetailClose.current = null;
          next?.();
        }}
      />
      <AutomationEditDialog
        job={pendingEdit}
        saving={actionKey === `update:${pendingEdit?.id ?? ""}`}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setPendingEdit(null);
        }}
        onCancel={(job) => {
          setInspectedJob(job);
          setDetailOpen(true);
        }}
        onSave={handleEdit}
      />
      <AutomationDeleteDialog
        job={pendingDelete}
        deleting={actionKey === `delete:${pendingDelete?.id ?? ""}`}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setPendingDelete(null);
        }}
        onConfirm={(job) => handleAction("delete", job)}
      />
    </>
  );
}

function AutomationRow({
  job,
  now,
  onSelect,
}: {
  job: SessionAutomationJob;
  now: number;
  onSelect: (job: SessionAutomationJob) => void;
}) {
  const { t } = useTranslation("common");
  const nextRun = formatNextRun(job, t, now);
  const needsAttention = job.state.last_status === "error" || Boolean(job.state.last_error);
  const summary = needsAttention
    ? t("settings.automations.filters.failed", { defaultValue: "Needs attention" })
    : nextRun.label;
  const statusClass = job.enabled
    ? needsAttention
      ? "bg-destructive"
      : "bg-emerald-500"
    : "bg-muted-foreground/35";

  return (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-label={`${job.name || job.id}, ${summary}`}
      onClick={() => onSelect(job)}
      className={cn(
        "grid min-h-12 w-full grid-cols-[0.375rem_minmax(0,1fr)_1rem] items-center gap-2.5 rounded-control px-3 py-2 text-left",
        "transition-colors duration-150 settings-hover",
        formControlFocusClassName,
      )}
    >
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusClass)} aria-hidden />
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium leading-5 text-foreground">
          {job.name || job.id}
        </span>
        <span
          className={cn(
            "block truncate text-[11.5px] leading-4 text-muted-foreground",
            needsAttention && "text-destructive",
          )}
          title={needsAttention ? summary : nextRun.title}
        >
          {summary}
        </span>
      </span>
      <ChevronRight className="h-4 w-4 text-muted-foreground/65" aria-hidden />
    </button>
  );
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
