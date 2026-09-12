import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type { TFunction } from "i18next";
import {
  Check,
  Info,
  CircleAlert,
  Clipboard,
  ListFilter,
  Loader2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { channelUiOwner, channelUiPresentation } from "@/channel-plugins/registry";
import { AutomationCalendar } from "@/components/settings/system/AutomationCalendar";
import { AutomationRunAtPicker, parseAutomationRunAt } from "@/components/settings/system/AutomationRunAtPicker";
import {
  modelPresetOptionsFromSettings,
  toModelBadgeInfo,
} from "@/components/thread/model-preset";
import { ThreadComposer } from "@/components/thread/ThreadComposer";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ExpandableText } from "@/components/ui/expandable-text";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { displayTitle } from "@/lib/chat-groups";
import { copyTextToClipboard } from "@/lib/clipboard";
import { fmtDateTime, relativeTime } from "@/lib/format";
import type { SendAttachment, SendOptions } from "@/hooks/useNanobotStream";
import type {
  AutomationsPayload,
  AutomationUpdatePayload,
  SessionAutomationJob,
  SettingsPayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export type AutomationFilter = "all" | "active" | "paused" | "failed" | "system";
export type AutomationAction = "enable" | "disable" | "delete" | "run";

const EMPTY_TITLE_OVERRIDES: Record<string, string> = {};

export function AutomationsSettings({
  token = "",
  payload, loading, filter, actionKey, error,
  titleOverrides = EMPTY_TITLE_OVERRIDES,
  settingsSnapshot = null,
  onFilterChange, onAction,
  onRequestEdit, onRequestDelete, onStartChat, onManageModels,
  returnToDetailJob = null, onReturnToDetailHandled,
}: {
  token?: string;
  payload: AutomationsPayload | null;
  titleOverrides?: Record<string, string>;
  settingsSnapshot?: SettingsPayload | null;
  loading: boolean;
  filter: AutomationFilter;
  actionKey: string | null;
  error: string | null;
  onFilterChange: (value: AutomationFilter) => void;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
  onStartChat?: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
    modelPreset?: string | null,
  ) => boolean | void | Promise<boolean | void>;
  onManageModels?: () => void;
  returnToDetailJob?: SessionAutomationJob | null;
  onReturnToDetailHandled?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const jobs = useMemo(() => (payload?.jobs ?? []).map((job) => {
    const origin = job.origin;
    if (origin?.channel !== "websocket") return job;
    // Resolve UI-only titles from live sidebar state without changing task bindings.
    const title = displayTitle({
      key: origin.session_key ?? "", title: origin.title, preview: origin.preview ?? "",
    }, titleOverrides, t("chat.newChat"));
    return title === origin.title ? job : { ...job, origin: { ...origin, title } };
  }), [payload, titleOverrides, t]);
  const locale = i18n.resolvedLanguage || i18n.language;
  const [inspectedJob, setInspectedJob] = useState<SessionAutomationJob | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [localModelPreset, setLocalModelPreset] = useState<string | null>(null);
  const [view, setView] = useState<"tasks" | "calendar">("calendar");
  const [month, setMonth] = useState(() => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1);
  });
  const pageTitle = useRef<HTMLHeadingElement | null>(null);
  const selectedTrigger = useRef<HTMLElement | null>(null);
  const afterDetailClose = useRef<((job: SessionAutomationJob) => void) | null>(null);
  const visibleJobs = useMemo(() => jobs.filter((job) => !job.protected), [jobs]);
  const filtered = useMemo(() => visibleJobs.filter((job) => automationMatchesFilter(job, filter)), [filter, visibleJobs]);
  // Keep an inspected task open when an action moves it outside the current filter.
  const liveSelectedJob = jobs.find((job) => job.id === inspectedJob?.id);
  // Retain the last detail through its exit, even if a one-shot task disappears.
  const selectedJob = liveSelectedJob ?? inspectedJob;
  const summaryOptions: Array<{ value: AutomationFilter; label: string; count: number }> = [
    { value: "all", label: tx("settings.automations.filters.all", "All"), count: visibleJobs.length },
    { value: "active", label: tx("settings.automations.filters.active", "Active"),
      count: visibleJobs.filter((job) => automationMatchesFilter(job, "active")).length },
    { value: "paused", label: tx("settings.automations.filters.paused", "Disabled"),
      count: visibleJobs.filter((job) => automationMatchesFilter(job, "paused")).length },
    { value: "failed", label: tx("settings.automations.filters.failed", "Needs attention"),
      count: visibleJobs.filter(automationNeedsAttention).length },
  ];
  const configuredPresetNames = useMemo(
    () => new Set(settingsSnapshot?.model_presets?.map((preset) => preset.name) ?? []),
    [settingsSnapshot],
  );
  const activeModelPreset = (
    (localModelPreset && (!settingsSnapshot || configuredPresetNames.has(localModelPreset))
      ? localModelPreset
      : null)
    || settingsSnapshot?.agent.model_preset
    || "default"
  );
  const modelPresetOptions = useMemo(
    () => modelPresetOptionsFromSettings(settingsSnapshot),
    [settingsSnapshot],
  );
  const modelBadge = useMemo(
    () => toModelBadgeInfo(settingsSnapshot?.agent.model ?? null, settingsSnapshot, activeModelPreset),
    [activeModelPreset, settingsSnapshot],
  );
  const modelBadgeLabel = modelBadge.needsSetup
    ? tx("thread.composer.chooseAI", "Choose your AI")
    : modelBadge.label;

  useEffect(() => {
    if (liveSelectedJob) setInspectedJob(liveSelectedJob);
    else setDetailOpen(false);
  }, [liveSelectedJob]);

  useEffect(() => {
    if (!returnToDetailJob) return;
    const currentJob = jobs.find((job) => job.id === returnToDetailJob.id) ?? returnToDetailJob;
    setInspectedJob(currentJob);
    setDetailOpen(true);
    onReturnToDetailHandled?.();
  }, [jobs, onReturnToDetailHandled, returnToDetailJob]);

  const inspectJob = (job: SessionAutomationJob, trigger: HTMLElement) => {
    selectedTrigger.current = trigger;
    setInspectedJob(job);
    setDetailOpen(true);
  };
  const handOff = (callback: (job: SessionAutomationJob) => void) => {
    // Restore the row before opening the next dialog, so it has a mounted
    // element to return focus to when editing or confirmation finishes.
    afterDetailClose.current = callback;
    setDetailOpen(false);
  };
  const startAutomationChat = (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
  ) => onStartChat?.(
    tx(
      "settings.automations.createRequest",
      "Create an automation for this request:\n\n{{request}}",
      { request: content.trim() },
    ),
    images,
    options,
    activeModelPreset,
  );
  const filterLabel = filter === "all" ? tx("settings.automations.filter", "Filter") : tx("settings.automations.filteredBy", "Filter: {{status}}", {
    status: summaryOptions.find((option) => option.value === filter)?.label,
  });
  const filters = visibleJobs.length ? (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={filterLabel} title={filterLabel}
          className={cn("h-8 text-[12px]", filter === "all" ? "w-8 p-0 text-muted-foreground" : "gap-1.5 bg-background text-foreground")}>
          <ListFilter className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          {filter !== "all" ? filterLabel : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" aria-label={tx("settings.automations.filter", "Filter")}>
        <DropdownMenuRadioGroup value={filter} onValueChange={(value) => {
          const option = summaryOptions.find((item) => item.value === value);
          if (option) onFilterChange(option.value);
        }}>
          {summaryOptions.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value} className="gap-6">
              <span>{option.label}</span>
              <span className="ms-auto tabular-nums text-muted-foreground">{option.count}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  ) : null;

  return (
    <div className="automations-page">
      <header className="settings-feature-header mb-7">
        <h1 ref={pageTitle} tabIndex={-1} className="text-[24px] font-normal leading-tight tracking-normal text-foreground outline-none sm:text-[28px]">
          {tx("settings.nav.automations", "Automations")}
        </h1>
      </header>

      <div className="settings-stack">
        {onStartChat ? (
          <div
            className="automation-create-composer"
            aria-label={tx("settings.automations.create", "Create automation")}
          >
            <ThreadComposer
              onSend={startAutomationChat}
              inputAriaLabel={tx("settings.automations.createInput", "Describe an automation")}
              placeholder={tx(
                "settings.automations.createPrompt",
                "What would you like nanobot to automate?",
              )}
              variant="thread"
              compactWhenIdle
              modelLabel={modelBadgeLabel}
              modelDetail={modelBadge.model}
              modelPreset={activeModelPreset}
              modelPresets={modelPresetOptions}
              onModelPresetChange={setLocalModelPreset}
              modelProvider={modelBadge.provider}
              modelProviderLabel={modelBadge.providerLabel}
              modelNeedsSetup={modelBadge.needsSetup}
              onModelBadgeClick={modelBadge.needsSetup ? onManageModels : undefined}
              onManageModels={onManageModels}
            />
          </div>
        ) : null}

        {error ? <AutomationError message={error} /> : null}
        <div className="automation-panel overflow-hidden rounded-panel bg-[hsl(var(--settings-surface))]">
          <div className="automation-panel-toolbar bg-foreground/[0.025]">
            <div className="automation-view-switch" role="group" aria-label={tx("settings.automations.views.label", "Automation view")}>
              <SegmentedControl
                value={view}
                className="rounded-[var(--radius-panel)] bg-[var(--automation-view-track)]"
                itemClassName="min-h-8 rounded-[calc(var(--radius-panel)-0.25rem)]"
                options={[
                  { value: "tasks", label: tx("settings.automations.views.tasks", "Tasks") },
                  { value: "calendar", label: tx("settings.automations.views.calendar", "Calendar") },
                ]}
                onChange={setView}
              />
            </div>
            {view === "calendar" ? (
              <h2 className="shrink-0 text-[13px] font-normal text-muted-foreground">
                {new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(month)}
              </h2>
            ) : null}
            {filters ? <div className="automation-panel-filters min-w-0">{filters}</div> : null}
            {view === "calendar" ? (
              <div className="automation-calendar-navigation flex shrink-0 items-center gap-1">
                <Button type="button" variant="ghost" size="sm" className="h-8 rounded-full bg-background/60 px-3 text-[12px] text-foreground"
                  onClick={() => { const today = new Date(); setMonth(new Date(today.getFullYear(), today.getMonth(), 1)); }}>
                  {tx("settings.automations.calendar.today", "Today")}
                </Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground"
                  aria-label={tx("settings.automations.calendar.previousMonth", "Previous month")}
                  onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() - 1, 1))}>
                  <span className="text-lg leading-none" aria-hidden>‹</span>
                </Button>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground"
                  aria-label={tx("settings.automations.calendar.nextMonth", "Next month")}
                  onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() + 1, 1))}>
                  <span className="text-lg leading-none" aria-hidden>›</span>
                </Button>
              </div>
            ) : null}
          </div>
          {loading && !payload ? (
            <div role="status" className="flex h-44 items-center justify-center rounded-panel border border-border/70 bg-[hsl(var(--settings-surface))] text-[13px] text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
              {tx("settings.automations.loading", "Loading automations...")}
            </div>
          ) : view === "tasks" ? (
            <section className="p-1" aria-label={tx("settings.automations.views.tasks", "Tasks")}>
              {filtered.length ? (
                <ul className="space-y-1">
                  {filtered.map((job) => {
                    const status = automationStatusKey(job);
                    const emphasizedStatus = status === "running" || status === "failed" || status === "paused";
                    return (
                      <li key={job.id}>
                        <button
                          type="button"
                          aria-haspopup="dialog"
                          onClick={(event) => inspectJob(job, event.currentTarget)}
                          className={cn("flex w-full min-w-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-control px-3 py-3 text-start transition-colors hover:bg-foreground/[0.045] motion-reduce:transition-none", formControlFocusClassName)}
                        >
                          <span className="min-w-0 flex-1 basis-48">
                            <span className="block truncate text-[14px] font-medium text-foreground">{job.name || job.id}</span>
                            <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[12px] leading-5 text-muted-foreground">
                              <span>{formatAutomationSchedule(job, locale, tx)}</span>
                              {job.protected ? <span>{tx("settings.automations.filters.system", "System")}</span> : null}
                            </span>
                          </span>
                          {emphasizedStatus ? (
                            <span className={cn("inline-flex items-center gap-1.5 text-[12px]", status === "failed" ? "text-destructive" : "text-muted-foreground")}>
                              {status === "running" ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
                              {status === "failed" ? <CircleAlert className="h-3.5 w-3.5" aria-hidden /> : null}
                              {tx(`settings.automations.status.${status}`, status === "paused" ? "Disabled" : status === "running" ? "Running" : "Failed")}
                            </span>
                          ) : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="px-3 py-10 text-center text-[13px] text-muted-foreground">
                  {visibleJobs.length ? tx("settings.automations.noMatches", "No automations match this view.") : tx("settings.automations.empty", "No automations yet.")}
                </p>
              )}
            </section>
          ) : (
            <AutomationCalendar
              token={token}
              jobs={filtered}
              month={month}
              locale={locale}
              copy={{
                planned: tx("settings.automations.calendar.planned", "Planned"),
                recorded: tx("settings.automations.calendar.recorded", "Recorded"),
                running: tx("settings.automations.status.running", "Running"),
                failed: tx("settings.automations.status.failed", "Failed"),
                more: (count) => tx("settings.automations.calendar.more", "+{{count}} more", { count }),
                close: tx("common.close", "Close"),
                system: tx("settings.automations.filters.system", "System"),
                noEntries: filtered.length
                  ? tx("settings.automations.calendar.noEntries", "No runs in this month.")
                  : visibleJobs.length
                    ? tx("settings.automations.noMatches", "No automations match this view.")
                    : tx("settings.automations.empty", "No automations yet."),
                completed: tx("settings.automations.status.completed", "Completed"),
                skipped: tx("settings.automations.skipped", "Skipped"),
              }}
              onInspect={inspectJob}
            />
          )}
        </div>

      </div>

      <AutomationDetailDialog
        job={selectedJob}
        open={detailOpen}
        locale={locale}
        actionKey={actionKey}
        error={error}
        onOpenChange={setDetailOpen}
        onAction={onAction}
        onRequestEdit={() => handOff(onRequestEdit)}
        onRequestDelete={() => handOff(onRequestDelete)}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (detailOpen) return;
          setInspectedJob(null);
          const target = selectedTrigger.current?.isConnected
            ? selectedTrigger.current : pageTitle.current;
          target?.focus({ preventScroll: true });
          const next = afterDetailClose.current;
          afterDetailClose.current = null;
          if (liveSelectedJob) next?.(liveSelectedJob);
        }}
      />
    </div>
  );
}

export function AutomationDetailDialog({
  job,
  open,
  locale,
  actionKey,
  error,
  onOpenChange,
  onAction,
  onRequestEdit,
  onRequestDelete,
  onCloseAutoFocus,
}: {
  job: SessionAutomationJob | null;
  open: boolean;
  locale: string;
  actionKey: string | null;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {job ? (
        <DialogContent
          aria-describedby={undefined}
          {...(!open ? { inert: "", "aria-hidden": true } : {})}
          className={cn(
            "flex max-h-[calc(100dvh-2rem)] max-w-[520px] flex-col gap-0 p-0 text-sm font-normal leading-normal text-foreground",
            job.protected && "max-w-[440px]",
          )}
          onCloseAutoFocus={onCloseAutoFocus}
        >
          <AutomationDetailPanel
            key={job.id}
            job={job}
            locale={locale}
            actionKey={actionKey}
            error={error}
            onAction={onAction}
            onRequestEdit={onRequestEdit}
            onRequestDelete={onRequestDelete}
          />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}


function AutomationDetailPanel({
  job, locale, actionKey, error, onAction, onRequestEdit, onRequestDelete,
}: {
  job: SessionAutomationJob;
  locale: string;
  actionKey: string | null;
  error: string | null;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const originHref = job.origin?.channel === "websocket" && job.origin.session_key
    ? `#/chat/${encodeURIComponent(job.origin.session_key)}` : null;
  const localTrigger = isLocalTriggerAutomation(job);
  const command = automationTriggerCommand(job);
  const message = localTrigger ? command : job.payload.message || "";
  const timezone = job.schedule.kind === "cron" ? job.schedule.tz?.trim() || null : null;
  const [messageExpanded, setMessageExpanded] = useState(false);
  const messageId = useId();
  const [commandCopied, setCommandCopied] = useState(false);
  const messageNeedsExpansion = automationMessageNeedsExpansion(message);
  const busy = Boolean(actionKey);
  const canManage = !job.protected;
  const canToggle = canManage && (job.enabled || Boolean(job.origin));
  const canRun = canManage && Boolean(job.origin) && job.enabled && !job.state.pending && !localTrigger;
  const lastStatus = job.state.last_status === "ok"
    ? tx("settings.automations.status.completed", "Completed")
    : job.state.last_status === "error"
      ? tx("settings.automations.status.failed", "Failed")
      : job.state.last_status === "skipped"
        ? tx("settings.automations.skipped", "Skipped")
        : job.state.last_status;

  return (
    <>
      <div className="absolute right-11 top-2.5">
        <Popover>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 rounded-full text-muted-foreground"
                    aria-label={tx("settings.automations.taskInfo", "Task information")}>
                    <Info className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
                  </Button>
                </PopoverTrigger>
              </TooltipTrigger>
              <TooltipContent>{tx("settings.automations.taskInfo", "Task information")}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <PopoverContent side="bottom" align="end" collisionPadding={16}
            aria-label={tx("settings.automations.taskInfo", "Task information")}
            className="w-80 max-w-[calc(100vw-2rem)] p-4 text-sm font-normal">
            <dl>
              <AutomationDetail label={tx("settings.automations.labels.schedule", "Schedule")}>
                {formatAutomationSchedule(job, locale, tx)}
              </AutomationDetail>
              {!localTrigger ? (
                <AutomationDetail label={tx("settings.automations.sort.next", "Next run")} title={formatAutomationNextTitle(job, locale, tx)}>
                  {formatAutomationNext(job, tx)}
                </AutomationDetail>
              ) : null}
              <AutomationDetail label={tx("settings.automations.sort.last", "Last run")} title={job.state.last_run_at_ms ? fmtDateTime(job.state.last_run_at_ms, locale) : undefined}>
                {job.state.last_run_at_ms
                  ? <span className="flex flex-wrap gap-x-3 gap-y-1">
                      {lastStatus ? <span>{lastStatus}</span> : null}
                      <span>{relativeTime(job.state.last_run_at_ms)}</span>
                    </span>
                  : lastStatus || tx("settings.automations.neverRun", "Not run yet")}
              </AutomationDetail>
              {timezone ? (
                <AutomationDetail label={tx("settings.automations.fields.timezone", "Timezone")}>{timezone}</AutomationDetail>
              ) : null}
              {job.delete_after_run ? <AutomationDetail label={tx("settings.automations.oneShot", "One-time")}>{tx("settings.automations.oneShotHint", "Removed after running")}</AutomationDetail> : null}
              {job.created_at_ms ? <AutomationDetail label={tx("settings.automations.labels.created", "Created")}>{fmtDateTime(job.created_at_ms, locale)}</AutomationDetail> : null}
              {job.updated_at_ms ? <AutomationDetail label={tx("settings.automations.labels.updated", "Updated")}>{fmtDateTime(job.updated_at_ms, locale)}</AutomationDetail> : null}
              <AutomationDetail label="ID"><span className="break-all font-mono">{job.id}</span></AutomationDetail>
            </dl>
          </PopoverContent>
        </Popover>
      </div>
      <DialogHeader className="shrink-0 px-6 pb-3 pr-24 pt-5 text-left">
        <DialogTitle className="min-w-0 break-words text-lg font-medium leading-snug tracking-normal text-balance">{job.name || job.id}</DialogTitle>
      </DialogHeader>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-6 pb-3">
        {canManage && message.trim() ? <section className="pb-4">
          {localTrigger && command ? (
            <div className="mb-2 flex items-center justify-between gap-3 text-sm text-muted-foreground">
              <span>{tx("settings.automations.fields.command", "Command")}</span>
              <Button variant="ghost" size="sm" className="font-normal text-muted-foreground" onClick={() => {
                void copyTextToClipboard(command).then((ok) => { if (ok) setCommandCopied(true); });
              }}>
                {commandCopied ? <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden /> : <Clipboard className="mr-1.5 h-3.5 w-3.5" aria-hidden />}
                {commandCopied ? tx("settings.automations.commandCopied", "Copied") : tx("settings.automations.copyCommand", "Copy")}
              </Button>
            </div>
          ) : null}
          <div>
            <ExpandableText id={messageId} expanded={messageExpanded || !messageNeedsExpansion} lines={6} className={cn("whitespace-pre-wrap break-words text-sm leading-normal text-foreground [overflow-wrap:anywhere]", localTrigger && "font-mono")}>
              {message}
            </ExpandableText>
          </div>
          {messageNeedsExpansion ? (
            <button type="button" aria-expanded={messageExpanded} aria-controls={messageId} onClick={() => setMessageExpanded((value) => !value)} className="mt-2 rounded-sm text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {messageExpanded ? tx("settings.automations.message.showLess", "Show less") : tx("settings.automations.message.showMore", "Show full message")}
            </button>
          ) : null}
        </section> : null}
        {job.state.last_error ? <AutomationError message={job.state.last_error} /> : null}
        {error ? <AutomationError message={error} /> : null}
        <dl>
          {!job.protected && job.origin?.channel && job.origin.channel !== "websocket" ? (
            <AutomationDetail label={tx("settings.automations.labels.origin", "Linked chat")}>
              {automationChannelLabel(job.origin.channel, t)}
            </AutomationDetail>
          ) : null}
        </dl>
      </div>
      {canManage ? (
        <div className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-t border-border/45 px-6 py-3">
          <div className="flex max-w-full flex-wrap gap-2">
            <Button variant="ghost" size="sm" className="font-normal text-muted-foreground" disabled={busy || !canToggle}
              onClick={() => void onAction(job.enabled ? "disable" : "enable", job)}>
              {actionKey === `enable:${job.id}` || actionKey === `disable:${job.id}`
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
              {job.enabled ? tx("settings.automations.pause", "Disable") : tx("settings.automations.resume", "Enable")}
            </Button>
            {!localTrigger ? (
              <Button variant="ghost" size="sm" className="font-normal text-muted-foreground" disabled={!canRun || busy} onClick={() => void onAction("run", job)}>
                {actionKey === `run:${job.id}` ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                {tx("settings.automations.runNow", "Run now")}
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              className="font-normal text-muted-foreground hover:bg-destructive/10 hover:text-destructive focus-visible:text-destructive"
              disabled={busy}
              onClick={() => onRequestDelete(job)}
            >
              {tx("settings.automations.delete", "Delete")}
            </Button>
          </div>
          <div className="ms-auto flex max-w-full flex-wrap justify-end gap-2">
            <Button variant="ghost" size="sm" className="font-normal text-muted-foreground" disabled={busy} onClick={() => onRequestEdit(job)}>
              {tx("settings.automations.edit", "Edit")}
            </Button>
            {originHref ? <Button asChild variant="ghost" size="sm" className="font-normal text-muted-foreground"><a href={originHref}>{tx("settings.automations.emptyAction", "Open a chat")}</a></Button> : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

function AutomationError({ message }: { message: string }) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg bg-destructive/5 px-3 py-2.5 text-[13px] leading-5 text-destructive">
    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
    <span className="min-w-0 break-words [overflow-wrap:anywhere]">
      {localizedAutomationError(message, tx)}
    </span>
  </div>;
}

const LEGACY_AUTOMATION_DESTINATION_ERROR = "legacy cron payload is missing channel/to";

function localizedAutomationError(
  message: string,
  tx: (key: string, fallback: string) => string,
): string {
  if (message.toLowerCase().includes(LEGACY_AUTOMATION_DESTINATION_ERROR)) {
    return tx(
      "settings.automations.errors.legacyMissingDestination",
      "This older automation is missing its delivery destination. Recreate it from the linked chat to continue.",
    );
  }
  return message;
}

function automationMessageNeedsExpansion(message: string): boolean {
  return message.length > 360 || message.split(/\r?\n/).length > 6;
}

function AutomationDetail({ label, title, children }: { label: ReactNode; title?: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[minmax(6.5rem,0.75fr)_minmax(0,1.75fr)] items-start gap-4 py-2.5 text-sm leading-normal">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-start text-foreground [overflow-wrap:anywhere]" title={title}>{children}</dd>
    </div>
  );
}

type AutomationEveryUnit = "second" | "minute" | "hour" | "day";

// These dialogs are opened programmatically, without a mounted DialogTrigger.
function useAutomationDialogFocus() {
  const previousFocus = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: (event: Event) => {
      previousFocus.current = document.activeElement instanceof HTMLElement
        ? document.activeElement : null;
      event.preventDefault();
      if (event.target instanceof HTMLElement) event.target.focus({ preventScroll: true });
    },
    onCloseAutoFocus: (event: Event) => {
      event.preventDefault();
      previousFocus.current?.focus({ preventScroll: true });
    },
  };
}

type AutomationEditDraft = {
  name: string;
  message: string;
  scheduleKind: "at" | "every" | "cron";
  everyValue: string;
  everyUnit: AutomationEveryUnit;
  cronExpr: string;
  tz: string;
  atLocal: string;
};
type AutomationScheduleUpdate = NonNullable<AutomationUpdatePayload["schedule"]>;

const AUTOMATION_EVERY_UNITS: Array<{ value: AutomationEveryUnit; ms: number }> = [
  { value: "second", ms: 1000 },
  { value: "minute", ms: 60_000 },
  { value: "hour", ms: 3_600_000 },
  { value: "day", ms: 86_400_000 },
];

export function AutomationEditDialog({
  job,
  saving,
  onOpenChange,
  onCancel,
  onSave,
}: {
  job: SessionAutomationJob | null;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onCancel?: (job: SessionAutomationJob) => void;
  onSave: (job: SessionAutomationJob, values: AutomationUpdatePayload) => void | Promise<void>;
}) {
  const dialogFocus = useAutomationDialogFocus();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const [draft, setDraft] = useState<AutomationEditDraft>(() => automationDraftFromJob(null));
  const validationId = useId();
  const localTrigger = isLocalTriggerAutomation(job);

  useEffect(() => {
    setDraft(automationDraftFromJob(job));
  }, [job]);

  const validation = automationEditDraftError(draft, job, tx);
  const scheduleOptions = [
    { value: "every", label: tx("settings.automations.scheduleTypes.every", "Interval") },
    { value: "cron", label: tx("settings.automations.scheduleTypes.cron", "Cron") },
    { value: "at", label: tx("settings.automations.scheduleTypes.at", "Once") },
  ];
  const unitLabels: Record<AutomationEveryUnit, string> = {
    second: tx("settings.automations.everyUnits.second", "Seconds"),
    minute: tx("settings.automations.everyUnits.minute", "Minutes"),
    hour: tx("settings.automations.everyUnits.hour", "Hours"),
    day: tx("settings.automations.everyUnits.day", "Days"),
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = automationUpdatePayloadFromDraft(draft, job);
    if (!job || typeof payload === "string") return;
    void onSave(job, payload);
  };
  const changeOpen = (open: boolean) => {
    onOpenChange(open);
    if (!open && job) onCancel?.(job);
  };

  return (
    <Dialog
      open={Boolean(job)}
      onOpenChange={changeOpen}
    >
      {job ? (
        <DialogContent
          {...dialogFocus}
          aria-describedby={undefined}
          className="w-[min(calc(100vw-2rem),34rem)]"
          onEscapeKeyDown={(event) => {
            // Escape in the nested date calendar must not cancel the editor.
            if (event.target instanceof Element && event.target.closest("[data-automation-date-calendar]")) {
              event.preventDefault();
            }
          }}
        >
          <form className="space-y-5" onSubmit={submit}>
            <DialogHeader>
              <DialogTitle>{tx("settings.automations.editTitle", "Edit automation")}</DialogTitle>
            </DialogHeader>

            <div className="space-y-4">
              <label className="block space-y-1.5">
                <span className="text-[12px] font-medium text-muted-foreground">
                  {tx("settings.automations.fields.name", "Name")}
                </span>
                <Input
                  value={draft.name}
                  onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                />
              </label>

              {!localTrigger ? (
                <label className="block space-y-1.5">
                  <span className="text-[12px] font-medium text-muted-foreground">
                    {tx("settings.automations.fields.message", "Message")}
                  </span>
                  <Textarea
                    value={draft.message}
                    onChange={(event) => setDraft((prev) => ({ ...prev, message: event.target.value }))}
                    className="min-h-[160px] resize-none text-[13px] leading-5"
                  />
                </label>
              ) : null}

              {!localTrigger ? (
                <div className="space-y-2">
                  <span className="text-[12px] font-medium text-muted-foreground">
                    {tx("settings.automations.fields.scheduleType", "Schedule type")}
                  </span>
                  <SegmentedControl
                    value={draft.scheduleKind}
                    options={scheduleOptions}
                    onChange={(value) =>
                      setDraft((prev) => ({
                        ...prev,
                        scheduleKind: value as AutomationEditDraft["scheduleKind"],
                      }))
                    }
                  />
                </div>
              ) : null}

              {!localTrigger && draft.scheduleKind === "every" ? (
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_10rem]">
                  <label className="block space-y-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
                      {tx("settings.automations.fields.every", "Every")}
                    </span>
                    <Input
                      type="number"
                      min={1}
                      step={1}
                      value={draft.everyValue}
                      onChange={(event) =>
                        setDraft((prev) => ({ ...prev, everyValue: event.target.value }))
                      }
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
                      {tx("settings.automations.fields.unit", "Unit")}
                    </span>
                    <select
                      value={draft.everyUnit}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          everyUnit: event.target.value as AutomationEveryUnit,
                        }))
                      }
                      className={cn(
                        "h-10 w-full rounded-control border border-input bg-background px-3 text-[13px] text-foreground transition-colors",
                        formControlFocusClassName,
                      )}
                    >
                      {AUTOMATION_EVERY_UNITS.map((unit) => (
                        <option key={unit.value} value={unit.value}>
                          {unitLabels[unit.value]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : null}

              {!localTrigger && draft.scheduleKind === "cron" ? (
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
                  <label className="block space-y-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
                      {tx("settings.automations.fields.cronExpression", "Cron expression")}
                    </span>
                    <Input
                      value={draft.cronExpr}
                      onChange={(event) => setDraft((prev) => ({ ...prev, cronExpr: event.target.value }))}
                      placeholder="0 9 * * *"
                      className="font-mono text-[13px]"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-[12px] font-medium text-muted-foreground">
                      {tx("settings.automations.fields.timezone", "Timezone")}
                    </span>
                    <Input
                      value={draft.tz}
                      onChange={(event) => setDraft((prev) => ({ ...prev, tz: event.target.value }))}
                      placeholder="Asia/Shanghai"
                      className="text-[13px]"
                    />
                  </label>
                </div>
              ) : null}

              {!localTrigger && draft.scheduleKind === "at" ? (
                <AutomationRunAtPicker
                  value={draft.atLocal}
                  onChange={(atLocal) => setDraft((prev) => ({ ...prev, atLocal }))}
                  disabled={saving}
                  errorId={validation ? validationId : undefined}
                />
              ) : null}

              {validation ? (
                <div id={validationId} className="rounded-control bg-destructive/8 px-3 py-2 text-[12px] text-destructive">
                  {validation}
                </div>
              ) : null}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => changeOpen(false)}
                disabled={saving}
              >
                {tx("settings.automations.cancel", "Cancel")}
              </Button>
              <Button type="submit" disabled={Boolean(validation) || saving}>
                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
                {tx("settings.automations.save", "Save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export function AutomationDeleteDialog({
  job,
  deleting,
  onOpenChange,
  onConfirm,
}: {
  job: SessionAutomationJob | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (job: SessionAutomationJob) => void | Promise<void>;
}) {
  const dialogFocus = useAutomationDialogFocus();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  return (
    <Dialog open={Boolean(job)} onOpenChange={onOpenChange}>
      <DialogContent {...dialogFocus} className="w-[min(calc(100vw-2rem),26rem)]">
        <DialogHeader>
          <DialogTitle>{tx("settings.automations.deleteTitle", "Delete automation")}</DialogTitle>
          <DialogDescription>
            {tx(
              "settings.automations.deleteDescription",
              "This removes {{name}} from automations. Past chat messages stay in the session.",
              { name: job?.name || job?.id || "" },
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={deleting}
          >
            {tx("settings.automations.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => job && void onConfirm(job)}
            disabled={!job || deleting}
          >
            {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
            {tx("settings.automations.delete", "Delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function isLocalTriggerAutomation(job: SessionAutomationJob | null): boolean {
  if (!job) return false;
  return job.kind === "local_trigger"
    || job.payload.kind === "local_trigger"
    || job.schedule.kind === "local";
}

function automationTriggerCommand(job: SessionAutomationJob): string {
  return job.trigger?.command || job.payload.command || job.payload.message || "";
}


function automationNeedsAttention(job: SessionAutomationJob): boolean {
  return job.state.last_status === "error";
}

function automationStatusKey(
  job: SessionAutomationJob,
): "active" | "running" | "paused" | "failed" | "system" | "completed" | "idle" {
  if (job.state.pending) return "running";
  if (!job.enabled) return "paused";
  if (job.state.last_status === "error") return "failed";
  if (isLocalTriggerAutomation(job)) return "active";
  if (job.delete_after_run && !job.state.next_run_at_ms && job.state.last_status === "ok") {
    return "completed";
  }
  if (!job.state.next_run_at_ms) return "idle";
  return "active";
}

function automationDraftFromJob(job: SessionAutomationJob | null): AutomationEditDraft {
  const every = automationIntervalDraft(job?.schedule.every_ms ?? 3_600_000);
  const scheduleKind = job?.schedule.kind === "at" || job?.schedule.kind === "cron"
    ? job.schedule.kind
    : "every";
  return {
    name: job?.name ?? "",
    message: job?.payload.message ?? "",
    scheduleKind,
    everyValue: every.value,
    everyUnit: every.unit,
    cronExpr: job?.schedule.expr ?? "0 9 * * *",
    tz: job?.schedule.tz ?? "",
    atLocal: formatLocalDateTimeInput(job?.schedule.at_ms ?? Date.now() + 3_600_000),
  };
}

function automationIntervalDraft(ms: number): { value: string; unit: AutomationEveryUnit } {
  for (const unit of [...AUTOMATION_EVERY_UNITS].reverse()) {
    if (ms >= unit.ms && ms % unit.ms === 0) {
      return { value: String(ms / unit.ms), unit: unit.value };
    }
  }
  return { value: String(Math.max(1, Math.round(ms / 60_000))), unit: "minute" };
}

function formatLocalDateTimeInput(ms: number): string {
  const date = new Date(ms);
  if (!Number.isFinite(date.getTime())) return "";
  const local = new Date(ms - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function automationEditDraftError(
  draft: AutomationEditDraft,
  job: SessionAutomationJob | null,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string | null {
  if (!draft.name.trim()) return tx("settings.automations.validation.nameRequired", "Enter a task name.");
  if (isLocalTriggerAutomation(job)) return null;
  if (!draft.message.trim()) {
    return tx("settings.automations.validation.messageRequired", "Enter a task message.");
  }
  if (draft.scheduleKind === "every") {
    const value = Number(draft.everyValue);
    if (!Number.isInteger(value) || value <= 0) {
      return tx("settings.automations.validation.intervalRequired", "Enter a positive whole number for the interval.");
    }
  }
  if (draft.scheduleKind === "cron" && !draft.cronExpr.trim()) {
    return tx("settings.automations.validation.cronRequired", "Enter a Cron expression.");
  }
  if (draft.scheduleKind === "at") {
    const atMs = parseAutomationRunAt(draft.atLocal)?.getTime() ?? NaN;
    if (!Number.isFinite(atMs)) {
      return tx("settings.automations.validation.timeRequired", "Choose a run time.");
    }
    if (atMs <= Date.now() && automationScheduleChanged(draft, job)) {
      return tx("settings.automations.validation.futureRequired", "Choose a time in the future.");
    }
  }
  return null;
}

function automationUpdatePayloadFromDraft(
  draft: AutomationEditDraft,
  job: SessionAutomationJob | null,
): AutomationUpdatePayload | string {
  const name = draft.name.trim();
  if (isLocalTriggerAutomation(job)) {
    if (!name) return "invalid";
    return { name };
  }
  const message = draft.message.trim();
  if (!name || !message) return "invalid";
  const payload: AutomationUpdatePayload = { name, message };
  const schedule = automationSchedulePayloadFromDraft(draft);
  if (typeof schedule === "string") return schedule;
  if (automationScheduleChanged(draft, job, schedule)) {
    payload.schedule = schedule;
  }
  return payload;
}

function automationSchedulePayloadFromDraft(draft: AutomationEditDraft): AutomationScheduleUpdate | string {
  if (draft.scheduleKind === "every") {
    const unit = AUTOMATION_EVERY_UNITS.find((candidate) => candidate.value === draft.everyUnit);
    const value = Number(draft.everyValue);
    if (!unit || !Number.isInteger(value) || value <= 0) return "invalid";
    return { kind: "every", every_ms: value * unit.ms };
  } else if (draft.scheduleKind === "cron") {
    const expr = draft.cronExpr.trim();
    if (!expr) return "invalid";
    return { kind: "cron", expr, ...(draft.tz.trim() ? { tz: draft.tz.trim() } : {}) };
  } else {
    const atMs = parseAutomationRunAt(draft.atLocal)?.getTime() ?? NaN;
    if (!Number.isFinite(atMs)) return "invalid";
    return { kind: "at", at_ms: atMs };
  }
}

function automationScheduleChanged(
  draft: AutomationEditDraft,
  job: SessionAutomationJob | null,
  schedule: AutomationScheduleUpdate | string = automationSchedulePayloadFromDraft(draft),
): boolean {
  if (!job || typeof schedule === "string") return true;
  if (schedule.kind !== job.schedule.kind) return true;
  if (schedule.kind === "every") return schedule.every_ms !== job.schedule.every_ms;
  if (schedule.kind === "cron") {
    return schedule.expr !== (job.schedule.expr ?? "") || (schedule.tz ?? null) !== (job.schedule.tz ?? null);
  }
  return draft.atLocal !== formatLocalDateTimeInput(job.schedule.at_ms ?? NaN);
}

function automationMatchesFilter(job: SessionAutomationJob, filter: AutomationFilter): boolean {
  const status = automationStatusKey(job);
  if (filter === "active") return status === "active" || status === "running";
  if (filter === "paused") return status === "paused";
  if (filter === "failed") return automationNeedsAttention(job);
  if (filter === "system") return Boolean(job.protected);
  return true;
}

const HOST_AUTOMATION_CHANNEL_LABELS: Record<string, string> = {
  api: "API",
  cli: "CLI",
};

function automationChannelLabel(channel: string, t: TFunction): string {
  const key = channel.trim().toLowerCase();
  const presentation = channelUiPresentation(key);
  if (presentation) {
    return channelTranslator(t, channelUiOwner(key))("displayName", presentation.displayName);
  }
  const displayName = HOST_AUTOMATION_CHANNEL_LABELS[key];
  return displayName
    ? t(`settings.automations.channels.${key}`, { defaultValue: displayName })
    : channel;
}

function formatAutomationSchedule(
  job: SessionAutomationJob,
  locale: string,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (job.schedule.kind === "at" && job.schedule.at_ms) {
    return tx("settings.automations.schedule.at", "At {{time}}", {
      time: fmtDateTime(job.schedule.at_ms, locale),
    });
  }
  if (job.schedule.kind === "every" && job.schedule.every_ms) {
    return tx("settings.automations.schedule.every", "Every {{duration}}", {
      duration: formatAutomationInterval(job.schedule.every_ms, locale),
    });
  }
  if (job.schedule.kind === "cron" && job.schedule.expr) {
    const summary = formatCronScheduleSummary(job.schedule.expr, locale, tx);
    if (summary) return summary;
    return tx("settings.automations.schedule.custom", "Custom schedule");
  }
  if (isLocalTriggerAutomation(job)) {
    return tx("settings.automations.commandCondition", "Triggered by command");
  }
  return tx("settings.automations.schedule.custom", "Custom schedule");
}

function formatCronScheduleSummary(
  expr: string,
  locale: string,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  const numericMinute = cronNumericToken(minute, 59);
  const numericHour = cronNumericToken(hour, 23);
  const everyDay = dayOfMonth === "*" && month === "*" && dayOfWeek === "*";
  const workdays = dayOfMonth === "*" && month === "*" && ["1-5", "MON-FRI", "mon-fri"].includes(dayOfWeek);

  if (numericMinute !== null && numericHour !== null) {
    const time = `${String(numericHour).padStart(2, "0")}:${String(numericMinute).padStart(2, "0")}`;
    if (everyDay) return tx("settings.automations.schedule.dailyAt", "Daily at {{time}}", { time });
    if (workdays) return tx("settings.automations.schedule.weekdaysAt", "Weekdays at {{time}}", { time });
    const weekday = /^\d$/.test(dayOfWeek) ? Number(dayOfWeek) : ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"].indexOf(dayOfWeek.toUpperCase());
    if (dayOfMonth === "*" && month === "*" && weekday >= 0 && weekday <= 7) {
      return tx("settings.automations.schedule.weeklyAt", "Every {{day}} at {{time}}", {
        day: new Intl.DateTimeFormat(locale, { weekday: "long" }).format(new Date(2024, 0, 7 + weekday % 7)),
        time,
      });
    }
    const day = cronNumericToken(dayOfMonth, 31);
    if (day !== null && day > 0 && month === "*" && dayOfWeek === "*") {
      return tx("settings.automations.schedule.monthlyAt", "Monthly on day {{day}} at {{time}}", { day, time });
    }
  }

  if (everyDay && numericMinute !== null && hour === "*") {
    return tx("settings.automations.schedule.hourlyAt", "Hourly at :{{minute}}", {
      minute: String(numericMinute).padStart(2, "0"),
    });
  }

  const range = /^(\d{1,2})-(\d{1,2})$/.exec(hour);
  if (everyDay && numericMinute !== null && range) {
    const start = Number(range[1]);
    const end = Number(range[2]);
    if (start > 23 || end > 23) return null;
    return tx("settings.automations.schedule.hourlyWindow", "Hourly {{start}}-{{end}} at :{{minute}}", {
      start: String(start).padStart(2, "0"),
      end: String(end).padStart(2, "0"),
      minute: String(numericMinute).padStart(2, "0"),
    });
  }

  return null;
}

function cronNumericToken(value: string, max: number): number | null {
  if (!/^\d{1,2}$/.test(value)) return null;
  const parsed = Number(value);
  return parsed <= max ? parsed : null;
}

function formatAutomationNext(
  job: SessionAutomationJob,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (!job.enabled) return tx("settings.automations.next.paused", "Disabled");
  if (job.state.pending) return tx("settings.automations.next.pending", "Running now");
  if (isLocalTriggerAutomation(job)) {
    return tx("settings.automations.next.local", "Waiting for trigger");
  }
  if (automationStatusKey(job) === "completed") {
    return tx("settings.automations.status.completed", "Completed");
  }
  if (!job.state.next_run_at_ms) return tx("settings.automations.next.none", "No next run");
  return relativeTime(job.state.next_run_at_ms);
}

function formatAutomationNextTitle(
  job: SessionAutomationJob,
  locale: string,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (!job.state.next_run_at_ms) return formatAutomationNext(job, tx);
  return fmtDateTime(job.state.next_run_at_ms, locale);
}

function formatAutomationUnit(
  value: number,
  unit: Intl.NumberFormatOptions["unit"],
  locale: string,
  maximumFractionDigits = 0,
): string {
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit,
    unitDisplay: "long",
    maximumFractionDigits,
  }).format(value);
}

function formatAutomationInterval(ms: number, locale: string): string {
  const units: Array<[Intl.NumberFormatOptions["unit"], number]> = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
    ["second", 1000],
  ];
  for (const [unit, size] of units) {
    if (ms >= size && ms % size === 0) return formatAutomationUnit(ms / size, unit, locale);
  }
  const fallbackUnit = ms < 60_000 ? "second" : "minute";
  const fallbackSize = fallbackUnit === "second" ? 1000 : 60_000;
  return formatAutomationUnit(ms / fallbackSize, fallbackUnit, locale, 1);
}
