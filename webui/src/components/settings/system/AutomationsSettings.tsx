import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type { TFunction } from "i18next";
import {
  ArrowUpDown,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clipboard,
  Loader2,
  MoreHorizontal,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelTranslator } from "@/channel-plugins/i18n";
import { channelUiOwner, channelUiPresentation } from "@/channel-plugins/registry";
import { SETTINGS_SEARCH_INPUT_CLASS, SettingsGroup } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { Disclosure, DisclosureContent } from "@/components/ui/disclosure";
import { ExpandableText } from "@/components/ui/expandable-text";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { displayTitle } from "@/lib/chat-groups";
import { copyTextToClipboard } from "@/lib/clipboard";
import { fmtDateTime, relativeTime } from "@/lib/format";
import type { AutomationsPayload, AutomationUpdatePayload, SessionAutomationJob } from "@/lib/types";
import { cn } from "@/lib/utils";

export type AutomationFilter = "all" | "active" | "paused" | "failed" | "system";
export type AutomationSort = "next" | "last" | "updated" | "name";
export type AutomationAction = "enable" | "disable" | "delete" | "run";

const EMPTY_TITLE_OVERRIDES: Record<string, string> = {};
const SYSTEM_TASKS_OPEN_STORAGE_KEY = "nanobot-webui.automation-system-tasks-open";

export function AutomationsSettings({
  payload, loading, query, filter, sort, actionKey, error,
  titleOverrides = EMPTY_TITLE_OVERRIDES,
  onQueryChange, onFilterChange, onSortChange, onAction,
  onRequestEdit, onRequestDelete,
}: {
  payload: AutomationsPayload | null;
  titleOverrides?: Record<string, string>;
  loading: boolean;
  query: string;
  filter: AutomationFilter;
  sort: AutomationSort;
  actionKey: string | null;
  error: string | null;
  onQueryChange: (value: string) => void;
  onFilterChange: (value: AutomationFilter) => void;
  onSortChange: (value: AutomationSort) => void;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
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
  const [toolsOpen, setToolsOpen] = useState(Boolean(query) || filter !== "all" || sort !== "next");
  const [sortMenuOpen, setSortMenuOpen] = useState(false);
  const [systemOpen, setSystemOpen] = useState(() => {
    try {
      return window.localStorage.getItem(SYSTEM_TASKS_OPEN_STORAGE_KEY) !== "false";
    } catch {
      return true;
    }
  });
  const searchInput = useRef<HTMLInputElement | null>(null);
  const toolsToggle = useRef<HTMLButtonElement | null>(null);
  const pageTitle = useRef<HTMLHeadingElement | null>(null);
  const selectedTrigger = useRef<HTMLButtonElement | null>(null);
  const afterDetailClose = useRef<((job: SessionAutomationJob) => void) | null>(null);
  const toolsActive = Boolean(query) || filter !== "all" || sort !== "next";
  const filtered = useMemo(() => {
    const searchTokens = parseAutomationSearchQuery(query);
    return sortAutomationJobs(jobs, sort)
      .filter((job) => automationMatchesFilter(job, filter))
      .filter((job) => !searchTokens.length || automationMatchesSearch(job, searchTokens));
  }, [filter, jobs, query, sort]);
  const personalJobs = jobs.filter((job) => !job.protected);
  const personal = filtered.filter((job) => !job.protected);
  const system = filtered.filter((job) => job.protected);
  // Keep an inspected task open when an action moves it outside the current filter.
  const liveSelectedJob = jobs.find((job) => job.id === inspectedJob?.id);
  // Retain the last detail through its exit, even if a one-shot task disappears.
  const selectedJob = liveSelectedJob ?? inspectedJob;
  const summaryOptions: Array<{ value: AutomationFilter; label: string; count: number }> = [
    { value: "all", label: tx("settings.automations.filters.all", "All"), count: personalJobs.length },
    { value: "active", label: tx("settings.automations.filters.active", "Active"),
      count: personalJobs.filter((job) => automationMatchesFilter(job, "active")).length },
    { value: "paused", label: tx("settings.automations.filters.paused", "Paused"),
      count: personalJobs.filter((job) => automationMatchesFilter(job, "paused")).length },
    { value: "failed", label: tx("settings.automations.filters.failed", "Needs attention"),
      count: personalJobs.filter(automationNeedsAttention).length },
  ];
  const sortLabel = {
    next: tx("settings.automations.sort.next", "Next run"),
    last: tx("settings.automations.sort.last", "Last run"),
    updated: tx("settings.automations.sort.updated", "Updated"),
    name: tx("settings.automations.sort.name", "Name"),
  } satisfies Record<AutomationSort, string>;

  useEffect(() => {
    if (liveSelectedJob) setInspectedJob(liveSelectedJob);
    else setDetailOpen(false);
  }, [liveSelectedJob]);

  useEffect(() => {
    if (query) setSystemOpen(true);
  }, [query]);

  useEffect(() => {
    if (toolsOpen) searchInput.current?.focus({ preventScroll: true });
  }, [toolsOpen]);

  const renderJob = (job: SessionAutomationJob) => (
    <AutomationListItem
      key={job.id}
      job={job}
      locale={locale}
      disabled={Boolean(job.protected) && !systemOpen}
      onSelect={(button) => {
        selectedTrigger.current = button;
        setInspectedJob(job);
        setDetailOpen(true);
      }}
    />
  );
  const handOff = (callback: (job: SessionAutomationJob) => void) => {
    // Restore the row before opening the next dialog, so it has a mounted
    // element to return focus to when editing or confirmation finishes.
    afterDetailClose.current = callback;
    setDetailOpen(false);
  };

  return (
    <div className="automations-page">
      <header className="mb-6 flex items-center justify-between gap-4 sm:mb-8">
        <h1 ref={pageTitle} tabIndex={-1} className="text-[26px] font-semibold leading-tight tracking-[-0.025em] text-foreground outline-none sm:text-[30px]">
          {tx("settings.nav.automations", "Automations")}
        </h1>
        {jobs.length ? (
          <Button
            ref={toolsToggle}
            variant="ghost"
            size="icon"
            aria-label={tx("settings.automations.viewOptions", "Search and filter")}
            title={tx("settings.automations.viewOptions", "Search and filter")}
            aria-expanded={toolsOpen}
            aria-controls="automation-view-options"
            className={cn("h-9 w-9 shrink-0 rounded-full text-muted-foreground", toolsActive && "bg-muted text-foreground")}
            onClick={() => {
              setSortMenuOpen(false);
              setToolsOpen((value) => !value);
            }}
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        ) : null}
      </header>

      {jobs.length ? (
        <DisclosureContent
          id="automation-view-options"
          open={toolsOpen}
          className="space-y-3 pb-5 pt-1"
          onKeyDown={(event) => {
            if (event.key !== "Escape" || event.defaultPrevented || event.nativeEvent.isComposing || sortMenuOpen) return;
            event.preventDefault();
            event.stopPropagation();
            toolsToggle.current?.focus({ preventScroll: true });
            setToolsOpen(false);
          }}
        >
              <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                <div className="relative min-w-0">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <Input
                    ref={searchInput}
                    disabled={!toolsOpen}
                    value={query}
                    onChange={(event) => onQueryChange(event.target.value)}
                    aria-label={tx("settings.automations.search", "Search task, message, linked chat, or schedule")}
                    placeholder={tx("settings.automations.search", "Search task, message, linked chat, or schedule")}
                    className={cn("h-9 w-full rounded-full pl-9 text-[13px]", SETTINGS_SEARCH_INPUT_CLASS)}
                  />
                </div>
                <DropdownMenu open={toolsOpen && sortMenuOpen} onOpenChange={setSortMenuOpen}>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" disabled={!toolsOpen} className="h-9 gap-2 rounded-full text-[12px] text-muted-foreground">
                      <ArrowUpDown className="h-3.5 w-3.5" aria-hidden />
                      {sortLabel[sort]}
                      <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {(Object.keys(sortLabel) as AutomationSort[]).map((value) => (
                      <DropdownMenuItem key={value} onClick={() => onSortChange(value)}>
                        <span>{sortLabel[value]}</span>
                        {sort === value ? <Check className="ml-auto h-3.5 w-3.5" aria-hidden /> : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <div role="group" aria-label={tx("settings.nav.automations", "Automations")} className="flex flex-wrap gap-1">
                {summaryOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    disabled={!toolsOpen}
                    aria-pressed={filter === option.value}
                    onClick={() => onFilterChange(option.value)}
                    className={cn(
                      "touch-target inline-flex min-h-8 max-w-full items-center gap-2 rounded-full px-3 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground",
                      filter === option.value && "bg-muted text-foreground",
                    )}
                  >
                    <span className="min-w-0 [overflow-wrap:anywhere]">{option.label}</span>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{option.count}</span>
                  </button>
                ))}
              </div>
        </DisclosureContent>
      ) : null}

      {error ? <AutomationError message={error} /> : null}
      {loading && !payload ? (
        <div role="status" className="flex h-44 items-center justify-center text-[13px] text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          {tx("settings.automations.loading", "Loading automations...")}
        </div>
      ) : (
        <>
          {personal.length ? (
            <ul aria-label={tx("settings.automations.yourTasks", "Your automations")} className="divide-y divide-border/45">
              {personal.map(renderJob)}
            </ul>
          ) : !personalJobs.length && !query && filter === "all" ? (
            <div className="py-12 text-center sm:py-16">
              <p className="text-[17px] font-medium text-foreground">
                {tx("settings.automations.empty", "No automations yet.")}
              </p>
              <p className="mx-auto mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground">
                {tx("settings.automations.emptyHint", "Tell nanobot in a chat what you'd like it to do on a schedule.")}
              </p>
            </div>
          ) : !filtered.length ? (
            <div className="py-12 text-center text-[13px] text-muted-foreground">
              <p>{tx("settings.automations.noMatches", "No automations match this view.")}</p>
              <Button variant="outline" className="mt-4 rounded-full" onClick={() => {
                onQueryChange("");
                onFilterChange("all");
              }}>
                {tx("settings.automations.clearFilters", "Clear filters")}
              </Button>
            </div>
          ) : null}
          {system.length ? (
            <section className="mt-8 border-t border-border/45 pt-2">
              <button
                type="button"
                aria-expanded={systemOpen}
                aria-controls="automation-system-tasks"
                onClick={() => {
                  const open = !systemOpen;
                  setSystemOpen(open);
                  try {
                    // Persist only the user's choice, not automatic search expansion.
                    window.localStorage.setItem(SYSTEM_TASKS_OPEN_STORAGE_KEY, String(open));
                  } catch {
                    // Unavailable storage must not prevent expanding or collapsing.
                  }
                }}
                className={cn("flex min-h-16 w-full items-center gap-3 rounded-lg py-4 text-left text-[14px] font-medium", formControlFocusClassName)}
              >
                <span>{tx("settings.automations.systemTasks", "System tasks")}</span>
                <span className="text-[12px] font-normal tabular-nums text-muted-foreground">{system.length}</span>
                {system.some(automationNeedsAttention) ? (
                  <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] font-normal text-amber-700 dark:text-amber-400">
                    <CircleAlert className="h-3.5 w-3.5" aria-hidden />
                    {tx("settings.automations.filters.failed", "Needs attention")}
                  </span>
                ) : null}
                <ChevronRight className={cn("ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", systemOpen && "rotate-90")} aria-hidden />
              </button>
              <DisclosureContent
                id="automation-system-tasks"
                open={systemOpen}
              >
                <SettingsGroup>
                  <ul aria-label={tx("settings.automations.systemTasks", "System tasks")} className="divide-y divide-border/45">
                    {system.map(renderJob)}
                  </ul>
                </SettingsGroup>
              </DisclosureContent>
            </section>
          ) : null}
        </>
      )}

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        {selectedJob ? (
          <DialogContent
            {...(selectedJob.protected ? { "aria-describedby": undefined } : {})}
            {...(!detailOpen ? { inert: "", "aria-hidden": true } : {})}
            showCloseButton={false}
            overlayClassName="bg-black/15 backdrop-blur-none"
            className={cn(
              "flex max-h-[calc(100dvh-2rem)] max-w-[520px] flex-col gap-0 overflow-hidden rounded-[20px] p-0",
              selectedJob.protected && "max-w-[440px]",
            )}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              if (detailOpen) return;
              setInspectedJob(null);
              const target = selectedTrigger.current?.isConnected
                ? selectedTrigger.current : toolsToggle.current ?? pageTitle.current;
              target?.focus({ preventScroll: true });
              const next = afterDetailClose.current;
              afterDetailClose.current = null;
              if (liveSelectedJob) next?.(liveSelectedJob);
            }}
          >
            <AutomationDetailPanel
              key={selectedJob.id}
              job={selectedJob}
              locale={locale}
              actionKey={actionKey}
              error={error}
              onClose={() => setDetailOpen(false)}
              onAction={onAction}
              onRequestEdit={() => handOff(onRequestEdit)}
              onRequestDelete={() => handOff(onRequestDelete)}
            />
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

function AutomationListItem({ job, locale, disabled, onSelect }: {
  job: SessionAutomationJob;
  locale: string;
  disabled: boolean;
  onSelect: (button: HTMLButtonElement) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const attention = automationNeedsAttention(job);
  const compact = Boolean(job.protected);
  const summary = job.state.last_error || (compact ? null : automationSummary(job, tx));
  const running = Boolean(job.state.pending);
  return (
    <li>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="dialog"
        onClick={(event) => onSelect(event.currentTarget)}
        className={cn(
          "automation-task-row group grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 text-left transition-colors",
          compact ? "settings-list-row py-3 settings-hover" : "min-h-[92px] rounded-lg py-5 hover:bg-muted/35",
          formControlFocusClassName,
        )}
      >
        <span className="min-w-0">
          <span className={cn(
            "block truncate font-medium text-foreground",
            compact ? "text-[14px] leading-5" : "text-[16px] leading-6 tracking-[-0.015em] sm:text-[17px]",
          )}>{job.name || job.id}</span>
          {summary ? <span className="mt-1 block truncate text-[13px] leading-5 text-muted-foreground">{summary}</span> : null}
        </span>
        <span className={cn(
          "automation-task-state flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted-foreground",
          !compact && "sm:text-[13px]",
        )}>
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {attention && !running ? (
            <>
              <CircleAlert className="h-4 w-4 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden />
              <span className="text-amber-700 dark:text-amber-400">{tx("settings.automations.filters.failed", "Needs attention")}</span>
              {!job.enabled ? <span>· {tx("settings.automations.next.paused", "Paused")}</span> : null}
            </>
          ) : (
            <span title={formatAutomationNextTitle(job, locale, tx)}>{formatAutomationNext(job, tx)}</span>
          )}
        </span>
        <ChevronRight className="automation-task-chevron h-4 w-4 text-muted-foreground/70" aria-hidden />
      </button>
    </li>
  );
}

function AutomationDetailPanel({
  job, locale, actionKey, error, onClose, onAction, onRequestEdit, onRequestDelete,
}: {
  job: SessionAutomationJob;
  locale: string;
  actionKey: string | null;
  error: string | null;
  onClose: () => void;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const origin = automationOriginLabel(job, t);
  const originHref = job.origin?.channel === "websocket" && job.origin.session_key
    ? `#/chat/${encodeURIComponent(job.origin.session_key)}` : null;
  const localTrigger = isLocalTriggerAutomation(job);
  const command = automationTriggerCommand(job);
  const message = automationDetailText(job, tx);
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
      <div className="shrink-0 px-6 pb-5 pt-6 sm:px-7 sm:pt-7">
        <div className="flex items-start justify-between gap-4">
          <DialogTitle className="min-w-0 break-words text-[22px] font-semibold leading-7 tracking-[-0.025em]">{job.name || job.id}</DialogTitle>
          <Button variant="ghost" size="sm" className={cn("-mr-2 -mt-1 shrink-0 rounded-full text-[13px] text-muted-foreground", job.protected && "text-foreground")} onClick={onClose}>
            {tx("settings.automations.done", "Done")}
          </Button>
        </div>
        {canManage ? (
          <DialogDescription className="mt-2 text-[13px] leading-5">
            {formatAutomationSchedule(job, locale, tx)} · {formatAutomationNext(job, tx)}
          </DialogDescription>
        ) : null}
      </div>
      <div className={cn("min-h-0 overflow-y-auto overscroll-contain px-6 pb-6 sm:px-7", job.protected && "pb-3")}>
        {canManage ? <section className="pb-6 pt-2">
          <div className="flex items-center justify-between gap-3 text-[12px] text-muted-foreground">
            <span>{localTrigger ? tx("settings.automations.fields.command", "Command") : tx("settings.automations.instructions", "Instructions")}</span>
            {localTrigger && command ? (
              <Button variant="ghost" size="sm" className="h-7 rounded-full px-2 text-[12px]" onClick={() => {
                void copyTextToClipboard(command).then((ok) => { if (ok) setCommandCopied(true); });
              }}>
                {commandCopied ? <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden /> : <Clipboard className="mr-1.5 h-3.5 w-3.5" aria-hidden />}
                {commandCopied ? tx("settings.automations.commandCopied", "Copied") : tx("settings.automations.copyCommand", "Copy")}
              </Button>
            ) : null}
          </div>
          <div className="mt-2">
            <ExpandableText id={messageId} expanded={messageExpanded || !messageNeedsExpansion} lines={6} className={cn("whitespace-pre-wrap break-words text-[14px] leading-6 text-foreground/90 [overflow-wrap:anywhere]", localTrigger && "font-mono text-[12px]")}>
              {message}
            </ExpandableText>
          </div>
          {messageNeedsExpansion ? (
            <button type="button" aria-expanded={messageExpanded} aria-controls={messageId} onClick={() => setMessageExpanded((value) => !value)} className="mt-2 rounded-sm text-[12px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {messageExpanded ? tx("settings.automations.message.showLess", "Show less") : tx("settings.automations.message.showMore", "Show full message")}
            </button>
          ) : null}
        </section> : null}
        {job.state.last_error ? <AutomationError message={job.state.last_error} /> : null}
        {error ? <AutomationError message={error} /> : null}
        <dl className="divide-y divide-border/45 border-y border-border/45">
          {job.protected ? (
            <>
              <AutomationDetail label={tx("settings.automations.labels.schedule", "Schedule")}>
                {formatAutomationSchedule(job, locale, tx)}
              </AutomationDetail>
              <AutomationDetail label={tx("settings.automations.sort.next", "Next run")} title={formatAutomationNextTitle(job, locale, tx)}>
                {formatAutomationNext(job, tx)}
              </AutomationDetail>
            </>
          ) : null}
          <AutomationDetail label={tx("settings.automations.sort.last", "Last run")} title={job.state.last_run_at_ms ? fmtDateTime(job.state.last_run_at_ms, locale) : undefined}>
            {job.state.last_run_at_ms
              ? [lastStatus, relativeTime(job.state.last_run_at_ms)].filter(Boolean).join(" · ")
              : lastStatus || tx("settings.automations.neverRun", "Not run yet")}
          </AutomationDetail>
          {!job.protected ? (
            <AutomationDetail label={tx("settings.automations.labels.origin", "Linked chat")}>
              {originHref ? (
                <a href={originHref} className="inline-flex min-w-0 max-w-full items-center gap-2 hover:text-foreground hover:underline">
                  <span className="truncate">{origin}</span>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
                </a>
              ) : origin}
            </AutomationDetail>
          ) : null}
        </dl>
        <Disclosure
          className={cn("mt-3", job.protected && "mt-1")}
          summaryClassName={cn("flex cursor-pointer items-center justify-between gap-3 rounded-lg py-4 text-[13px] text-muted-foreground", job.protected && "py-3", formControlFocusClassName)}
          summary={<>
            {tx("settings.automations.moreDetails", "More details")}
            <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-data-[state=open]/disclosure:rotate-90 motion-reduce:transition-none" aria-hidden />
          </>}
        >
          <dl className="divide-y divide-border/45">
            {job.delete_after_run ? <AutomationDetail label={tx("settings.automations.oneShot", "One-time")}>{tx("settings.automations.oneShotHint", "Removed after running")}</AutomationDetail> : null}
            {job.created_at_ms ? <AutomationDetail label={tx("settings.automations.labels.created", "Created")}>{fmtDateTime(job.created_at_ms, locale)}</AutomationDetail> : null}
            {job.updated_at_ms ? <AutomationDetail label={tx("settings.automations.labels.updated", "Updated")}>{fmtDateTime(job.updated_at_ms, locale)}</AutomationDetail> : null}
            <AutomationDetail label="ID"><span className="break-all font-mono text-[11px]">{job.id}</span></AutomationDetail>
          </dl>
        </Disclosure>
      </div>
      {canManage ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border/45 px-5 py-4 sm:px-7">
          <Button variant="ghost" size="sm" className="rounded-full px-2 text-[13px] text-muted-foreground" disabled={busy || !canToggle} onClick={() => void onAction(job.enabled ? "disable" : "enable", job)}>
            {actionKey === `${job.enabled ? "disable" : "enable"}:${job.id}` ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            {job.enabled ? tx("settings.automations.pause", "Pause") : tx("settings.automations.resume", "Resume")}
          </Button>
          {/* The detail dialog owns modality, including during the delete handoff. */}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full text-muted-foreground" disabled={busy} aria-label={tx("settings.automations.moreActions", "More actions")}>
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {!localTrigger ? <DropdownMenuItem disabled={!canRun || busy} onClick={() => void onAction("run", job)}>{tx("settings.automations.runNow", "Run now")}</DropdownMenuItem> : null}
              <DropdownMenuItem disabled={busy} onClick={() => onRequestDelete(job)} className="text-destructive focus:text-destructive">{tx("settings.automations.delete", "Delete")}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" size="sm" className="ml-auto rounded-full px-4" disabled={busy} onClick={() => onRequestEdit(job)}>
            {tx("settings.automations.edit", "Edit")}
          </Button>
          {originHref ? <Button asChild size="sm" className="rounded-full px-4"><a href={originHref}>{tx("settings.automations.emptyAction", "Open a chat")}</a></Button> : null}
        </div>
      ) : null}
    </>
  );
}

function AutomationError({ message }: { message: string }) {
  return <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg bg-destructive/5 px-3 py-2.5 text-[13px] leading-5 text-destructive">
    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
    <span className="min-w-0 break-words [overflow-wrap:anywhere]">{message}</span>
  </div>;
}

function automationMessageNeedsExpansion(message: string): boolean {
  return message.length > 360 || message.split(/\r?\n/).length > 6;
}

function AutomationDetail({ label, title, children }: { label: string; title?: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)] items-start gap-4 py-3.5 text-[13px] leading-5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-right text-foreground/85 [overflow-wrap:anywhere]" title={title}>{children}</dd>
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
  onSave,
}: {
  job: SessionAutomationJob | null;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (job: SessionAutomationJob, values: AutomationUpdatePayload) => void | Promise<void>;
}) {
  const dialogFocus = useAutomationDialogFocus();
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const [draft, setDraft] = useState<AutomationEditDraft>(() => automationDraftFromJob(null));
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

  return (
    <Dialog open={Boolean(job)} onOpenChange={onOpenChange}>
      {job ? (
        <DialogContent
          {...dialogFocus}
          aria-describedby={undefined}
          className="w-[min(calc(100vw-2rem),34rem)]"
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
                <label className="block space-y-1.5">
                  <span className="text-[12px] font-medium text-muted-foreground">
                    {tx("settings.automations.fields.runAt", "Run at")}
                  </span>
                  <Input
                    type="datetime-local"
                    value={draft.atLocal}
                    onChange={(event) => setDraft((prev) => ({ ...prev, atLocal: event.target.value }))}
                  />
                </label>
              ) : null}

              {validation ? (
                <div className="rounded-control bg-destructive/8 px-3 py-2 text-[12px] text-destructive">
                  {validation}
                </div>
              ) : null}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
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

function automationSummary(
  job: SessionAutomationJob,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (isLocalTriggerAutomation(job)) {
    return automationTriggerCommand(job) || tx("settings.automations.localTrigger", "Local trigger");
  }
  return job.payload.message || tx("settings.automations.systemTask", "System-managed automation");
}

function automationDetailText(
  job: SessionAutomationJob,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  return automationSummary(job, tx);
}

function automationNeedsAttention(job: SessionAutomationJob): boolean {
  return job.state.last_status === "error";
}

function automationStatusKey(
  job: SessionAutomationJob,
): "active" | "running" | "paused" | "failed" | "system" | "completed" | "idle" {
  if (job.protected) return "system";
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

function sortAutomationJobs(jobs: SessionAutomationJob[], sort: AutomationSort): SessionAutomationJob[] {
  const byName = (left: SessionAutomationJob, right: SessionAutomationJob) =>
    (left.name || left.id).localeCompare(right.name || right.id);
  return [...jobs].sort((left, right) => {
    if (sort === "name") return byName(left, right);
    if (sort === "last") {
      return (right.state.last_run_at_ms ?? 0) - (left.state.last_run_at_ms ?? 0) || byName(left, right);
    }
    if (sort === "updated") {
      return (right.updated_at_ms ?? 0) - (left.updated_at_ms ?? 0) || byName(left, right);
    }
    const leftNext = left.state.next_run_at_ms ?? Number.MAX_SAFE_INTEGER;
    const rightNext = right.state.next_run_at_ms ?? Number.MAX_SAFE_INTEGER;
    return leftNext - rightNext || byName(left, right);
  });
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
    const atMs = new Date(draft.atLocal).getTime();
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
    const atMs = new Date(draft.atLocal).getTime();
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

type AutomationSearchField = "id" | "name" | "message" | "chat" | "cron" | "schedule" | "status";

interface AutomationSearchToken {
  field: AutomationSearchField | null;
  value: string;
}

const AUTOMATION_SEARCH_FIELDS = new Set<AutomationSearchField>([
  "id",
  "name",
  "message",
  "chat",
  "cron",
  "schedule",
  "status",
]);

const HOST_AUTOMATION_CHANNEL_LABELS: Record<string, string> = {
  api: "API",
  cli: "CLI",
};

function parseAutomationSearchQuery(query: string): AutomationSearchToken[] {
  return (query.match(/[^\s:]+:"[^"]+"|"[^"]+"|\S+/g) ?? [])
    .map((rawPart): AutomationSearchToken | null => {
      const part = trimAutomationSearchValue(rawPart);
      if (!part) return null;
      const fieldMatch = part.match(/^([A-Za-z]+):(.*)$/);
      if (!fieldMatch) return { field: null, value: part.toLowerCase() };
      const field = fieldMatch[1].toLowerCase() as AutomationSearchField;
      const value = trimAutomationSearchValue(fieldMatch[2]).toLowerCase();
      if (!value) return null;
      return AUTOMATION_SEARCH_FIELDS.has(field)
        ? { field, value }
        : { field: null, value: part.toLowerCase() };
    })
    .filter((token): token is AutomationSearchToken => Boolean(token));
}

function trimAutomationSearchValue(value: string): string {
  return value.trim().replace(/^"|"$/g, "").trim();
}

function automationMatchesSearch(job: SessionAutomationJob, tokens: AutomationSearchToken[]): boolean {
  return tokens.every((token) => automationSearchText(job, token.field).includes(token.value));
}

function automationSearchText(job: SessionAutomationJob, field: AutomationSearchField | null = null): string {
  return automationSearchParts(job, field)
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function automationSearchParts(
  job: SessionAutomationJob,
  field: AutomationSearchField | null,
): Array<string | number | null | undefined> {
  const originParts = automationOriginSearchParts(job);
  const scheduleParts = automationScheduleSearchParts(job);
  if (field === "id") return [job.id];
  if (field === "name") return [job.name, job.id];
  if (field === "message") return [job.payload.message, job.payload.command, job.trigger?.command];
  if (field === "chat") return originParts;
  if (field === "cron" || field === "schedule") return scheduleParts;
  if (field === "status") return [automationStatusKey(job), job.enabled ? "enabled" : "disabled"];
  return [
    job.id,
    job.name,
    job.payload.message,
    job.payload.command,
    job.trigger?.command,
    isLocalTriggerAutomation(job) ? "trigger local" : null,
    ...scheduleParts,
    automationStatusKey(job),
    ...originParts,
  ];
}

function automationOriginSearchParts(job: SessionAutomationJob): Array<string | null | undefined> {
  const origin = job.origin;
  if (!origin) return [];
  const channel = origin.channel.trim().toLowerCase();
  return [
    origin.session_key,
    origin.title,
    origin.preview,
    origin.channel,
    automationChannelDisplayName(channel),
  ];
}

function automationScheduleSearchParts(job: SessionAutomationJob): Array<string | number | null | undefined> {
  const schedule = job.schedule;
  const parts: Array<string | number | null | undefined> = [
    schedule.kind,
    schedule.expr,
    schedule.tz,
    schedule.every_ms,
    schedule.at_ms,
  ];
  if (schedule.kind === "cron" && schedule.expr) {
    parts.push(...automationCronSearchParts(schedule.expr));
  }
  return parts;
}

function automationCronSearchParts(expr: string): string[] {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return [];
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  const everyDay = dayOfMonth === "*" && month === "*" && dayOfWeek === "*";
  const numericMinute = cronNumericToken(minute, 59);
  const numericHour = cronNumericToken(hour, 23);
  if (numericMinute === null) return [];
  const paddedMinute = String(numericMinute).padStart(2, "0");

  if (numericHour !== null) {
    const time = `${String(numericHour).padStart(2, "0")}:${paddedMinute}`;
    return [time, `:${paddedMinute}`];
  }

  if (everyDay && hour === "*") {
    return [`:${paddedMinute}`, `hourly at :${paddedMinute}`];
  }

  const range = /^(\d{1,2})-(\d{1,2})$/.exec(hour);
  if (!everyDay || !range) return [];
  const start = Number(range[1]);
  const end = Number(range[2]);
  if (start > 23 || end > 23) return [];
  const paddedRange = `${String(start).padStart(2, "0")}-${String(end).padStart(2, "0")}`;
  const rawRange = `${start}-${end}`;
  return [
    paddedRange,
    rawRange,
    `:${paddedMinute}`,
    `${paddedRange} at :${paddedMinute}`,
    `hourly ${paddedRange} at :${paddedMinute}`,
  ];
}

function automationMatchesFilter(job: SessionAutomationJob, filter: AutomationFilter): boolean {
  const status = automationStatusKey(job);
  if (filter === "active") return status === "active" || status === "running";
  if (filter === "paused") return status === "paused";
  if (filter === "failed") return automationNeedsAttention(job);
  if (filter === "system") return Boolean(job.protected);
  return true;
}


function automationOriginLabel(
  job: SessionAutomationJob,
  t: TFunction,
): string {
  if (job.protected) return t("settings.automations.origin.system", { defaultValue: "System" });
  const origin = job.origin;
  if (!origin) return t("settings.automations.origin.unknown", { defaultValue: "No linked chat" });
  if (origin.channel !== "websocket") return automationChannelLabel(origin.channel, t);
  return origin.title || origin.preview || origin.session_key || automationChannelLabel(origin.channel, t);
}

function automationChannelLabel(
  channel: string,
  t: TFunction,
): string {
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

function automationChannelDisplayName(channel: string): string | undefined {
  const key = channel.trim().toLowerCase();
  return channelUiPresentation(key)?.displayName ?? HOST_AUTOMATION_CHANNEL_LABELS[key];
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
    const summary = formatCronScheduleSummary(job.schedule.expr, tx);
    if (summary) {
      return job.schedule.tz
        ? tx("settings.automations.schedule.withTz", "{{summary}} · {{tz}}", {
            summary,
            tz: job.schedule.tz,
          })
        : summary;
    }
    return job.schedule.tz
      ? tx("settings.automations.schedule.cronWithTz", "Cron {{expr}} · {{tz}}", {
          expr: job.schedule.expr,
          tz: job.schedule.tz,
        })
      : tx("settings.automations.schedule.cron", "Cron {{expr}}", { expr: job.schedule.expr });
  }
  if (isLocalTriggerAutomation(job)) {
    return tx("settings.automations.schedule.local", "Local trigger");
  }
  return tx("settings.automations.schedule.custom", "Custom schedule");
}

function formatCronScheduleSummary(
  expr: string,
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
  if (!job.enabled) return tx("settings.automations.next.paused", "Paused");
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
