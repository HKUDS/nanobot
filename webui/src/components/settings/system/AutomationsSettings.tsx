import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowUpDown,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clipboard,
  ExternalLink,
  Loader2,
  PauseCircle,
  Pencil,
  PlayCircle,
  Search,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { channelUiPresentation } from "@/channel-plugins/registry";
import { SETTINGS_SEARCH_INPUT_CLASS } from "@/components/settings/shared/SettingsControls";
import { AppsActionButton } from "@/components/settings/system/AppsSettings";
import { Button } from "@/components/ui/button";
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
import { copyTextToClipboard } from "@/lib/clipboard";
import { fmtDateTime, relativeTime } from "@/lib/format";
import type { AutomationsPayload, AutomationUpdatePayload, SessionAutomationJob } from "@/lib/types";
import { cn } from "@/lib/utils";

export type AutomationFilter = "all" | "active" | "paused" | "failed" | "system";
export type AutomationSort = "next" | "last" | "updated" | "name";
export type AutomationAction = "enable" | "disable" | "delete" | "run";

export function AutomationsSettings({
  payload,
  loading,
  query,
  filter,
  sort,
  actionKey,
  error,
  onQueryChange,
  onFilterChange,
  onSortChange,
  onAction,
  onRequestEdit,
  onRequestDelete,
  onBackToChat,
}: {
  payload: AutomationsPayload | null;
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
  onBackToChat: () => void;
}) {
  const { t, i18n } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const jobs = payload?.jobs ?? [];
  const locale = i18n.resolvedLanguage || i18n.language;
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const filtered = useMemo(() => {
    const searchTokens = parseAutomationSearchQuery(query);
    return sortAutomationJobs(jobs, sort)
      .filter((job) => automationMatchesFilter(job, filter))
      .filter((job) => !searchTokens.length || automationMatchesSearch(job, searchTokens));
  }, [filter, jobs, query, sort]);
  const activeCount = jobs.filter((job) => {
    const key = automationStatusKey(job);
    return key === "active" || key === "running";
  }).length;
  const pausedCount = jobs.filter((job) => automationStatusKey(job) === "paused").length;
  const failedCount = jobs.filter(automationNeedsAttention).length;
  const systemCount = jobs.filter((job) => job.protected).length;
  const summaryOptions: Array<{ value: AutomationFilter; label: string; count: number }> = [
    { value: "all", label: tx("settings.automations.filters.all", "All"), count: jobs.length },
    { value: "active", label: tx("settings.automations.filters.active", "Active"), count: activeCount },
    { value: "paused", label: tx("settings.automations.filters.paused", "Paused"), count: pausedCount },
    { value: "failed", label: tx("settings.automations.filters.failed", "Needs attention"), count: failedCount },
    { value: "system", label: tx("settings.automations.filters.system", "System"), count: systemCount },
  ];
  const sortLabel = {
    next: tx("settings.automations.sort.next", "Next run"),
    last: tx("settings.automations.sort.last", "Last run"),
    updated: tx("settings.automations.sort.updated", "Updated"),
    name: tx("settings.automations.sort.name", "Name"),
  } satisfies Record<AutomationSort, string>;
  const selectedJob = filtered.find((job) => job.id === selectedJobId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!filtered.length) {
      if (selectedJobId !== null) setSelectedJobId(null);
      return;
    }
    if (!selectedJobId || !filtered.some((job) => job.id === selectedJobId)) {
      setSelectedJobId(filtered[0].id);
    }
  }, [filtered, selectedJobId]);

  return (
    <div className="space-y-5">
      {jobs.length ? (
        <section className="shrink-0">
          <div className="mx-auto flex w-full max-w-[56rem] flex-col gap-3">
            <div className="-mx-1 overflow-x-auto px-1 pb-0.5">
              <div className="grid w-full min-w-[36rem] grid-cols-5 gap-1 rounded-[15px] bg-muted p-1">
                {summaryOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => onFilterChange(option.value)}
                    className={cn(
                      "inline-flex h-8 min-w-0 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[11px] px-3 text-[12px] font-medium text-muted-foreground transition-colors",
                      filter === option.value && "bg-background text-foreground",
                      automationFilterToneClass(option.value, option.count, filter === option.value),
                    )}
                  >
                    <span>{option.label}</span>
                    <span
                      className={cn(
                        "min-w-5 shrink-0 rounded-full bg-background/75 px-1.5 py-0.5 text-center text-[11px] tabular-nums text-muted-foreground",
                        automationFilterCountClass(option.value, option.count),
                      )}
                    >
                      {option.count}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div className="relative min-w-0">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/70" />
                <Input
                  value={query}
                  onChange={(event) => onQueryChange(event.target.value)}
                  placeholder={tx(
                    "settings.automations.search",
                    "Search task, message, linked chat, or schedule",
                  )}
                  className={cn(
                    "h-9 w-full rounded-[13px] pl-9 text-[13px]",
                    SETTINGS_SEARCH_INPUT_CLASS,
                  )}
                />
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-9 min-w-[8.5rem] items-center justify-center gap-1.5 whitespace-nowrap rounded-[13px] border border-border/45 bg-settings-surface px-3 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:w-auto"
                  >
                    <ArrowUpDown className="h-3.5 w-3.5" aria-hidden />
                    <span>{sortLabel[sort]}</span>
                    <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-40">
                  {(Object.keys(sortLabel) as AutomationSort[]).map((value) => (
                    <DropdownMenuItem key={value} onClick={() => onSortChange(value)}>
                      <span>{sortLabel[value]}</span>
                      {sort === value ? <Check className="ml-auto h-3.5 w-3.5" aria-hidden /> : null}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </section>
      ) : null}

      {error ? (
        <div className="flex items-center gap-2 rounded-[18px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
          <CircleAlert className="h-4 w-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      ) : null}

      {loading && !payload ? (
        <div className="flex h-44 items-center justify-center rounded-[22px] bg-settings-surface text-[13px] text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
          {tx("settings.automations.loading", "Loading automations...")}
        </div>
      ) : filtered.length && selectedJob ? (
        <section className="grid min-h-0 overflow-hidden rounded-[22px] bg-settings-surface xl:grid-cols-[minmax(16rem,18rem)_minmax(0,1fr)] xl:items-stretch">
          <aside className="flex min-h-0 flex-col overflow-hidden border-b border-border/35 bg-settings-surface xl:border-b-0 xl:border-r">
            <div className="flex shrink-0 items-center justify-between gap-3 px-4 py-3">
              <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
                {tx("settings.automations.queue", "Queue")}
              </h2>
              <span className="rounded-full bg-orange-100/60 px-2 py-0.5 text-[11px] text-orange-800/70 tabular-nums dark:bg-orange-300/10 dark:text-orange-200/75">
                {filtered.length}
              </span>
            </div>
            <div
              className="max-h-[28rem] space-y-1 overflow-y-auto overscroll-contain px-2 pb-2 xl:max-h-[calc(100vh-24rem)]"
              role="list"
              aria-label={tx("settings.automations.queue", "Queue")}
            >
              {filtered.map((job) => (
                <AutomationListItem
                  key={job.id}
                  job={job}
                  locale={locale}
                  selected={job.id === selectedJob.id}
                  onSelect={() => setSelectedJobId(job.id)}
                />
              ))}
            </div>
          </aside>
          <AutomationDetailPanel
            job={selectedJob}
            locale={locale}
            actionKey={actionKey}
            onAction={onAction}
            onRequestEdit={onRequestEdit}
            onRequestDelete={onRequestDelete}
          />
        </section>
      ) : (
        <div className="rounded-[22px] bg-settings-surface px-5 py-12 text-center text-[13px] text-muted-foreground">
          <div>
            {jobs.length
              ? tx("settings.automations.noMatches", "No automations match this view.")
              : tx("settings.automations.empty", "No automations yet.")}
          </div>
          {!jobs.length ? (
            <>
              <div className="mx-auto mt-2 max-w-[28rem] text-[12px] leading-5">
                {tx(
                  "settings.automations.emptyHint",
                  "Create automations in a chat so they keep the right context.",
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                className="mt-4 rounded-full"
                onClick={onBackToChat}
              >
                {tx("settings.automations.emptyAction", "Open a chat")}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="outline"
              className="mt-4 rounded-full"
              onClick={() => {
                onQueryChange("");
                onFilterChange("all");
              }}
            >
              {tx("settings.automations.clearFilters", "Clear filters")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function AutomationListItem({
  job,
  locale,
  selected,
  onSelect,
}: {
  job: SessionAutomationJob;
  locale: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const status = automationStatus(job, tx);
  const origin = automationOriginLabel(job, tx);
  const nextRun = formatAutomationNext(job, tx);
  const summary = automationSummary(job, tx);

  return (
    <div role="listitem">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "group grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-[18px] px-3 py-3.5 text-left transition-colors",
          selected
            ? "bg-background/80 text-foreground"
            : "text-muted-foreground hover:bg-background/55 hover:text-foreground",
        )}
      >
        <span className="min-w-0">
          <span className="flex min-w-0 items-center gap-2.5">
            <span
              className={cn("h-2 w-2 shrink-0 rounded-full", automationStatusDotClass(job))}
              aria-hidden
            />
            <span className="truncate text-[13.5px] font-medium text-foreground">
              {job.name || job.id}
            </span>
          </span>
          <span className="mt-1.5 line-clamp-2 text-[12px] leading-5 text-muted-foreground">
            {summary}
          </span>
          <span className="mt-2.5 flex min-w-0 items-center gap-2 text-[11.5px] leading-none text-muted-foreground">
            <span className="truncate" title={formatAutomationNextTitle(job, locale, tx)}>
              {nextRun}
            </span>
            <span className="h-1 w-1 shrink-0 rounded-full bg-muted-foreground/35" aria-hidden />
            <span className="truncate">{origin}</span>
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-2 pt-0.5">
          <span className="rounded-full bg-background/70 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {status.label}
          </span>
          {job.delete_after_run ? (
            <span className="rounded-full bg-background/80 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {tx("settings.automations.oneShot", "One-time")}
            </span>
          ) : null}
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 text-muted-foreground/55 transition-opacity",
              selected ? "opacity-100" : "opacity-0 group-hover:opacity-70",
            )}
            aria-hidden
          />
        </span>
      </button>
    </div>
  );
}

function AutomationDetailPanel({
  job,
  locale,
  actionKey,
  onAction,
  onRequestEdit,
  onRequestDelete,
}: {
  job: SessionAutomationJob;
  locale: string;
  actionKey: string | null;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const status = automationStatus(job, tx);
  const origin = automationOriginLabel(job, tx);
  const originHref = job.origin?.channel === "websocket" && job.origin.session_key
    ? `#/chat/${encodeURIComponent(job.origin.session_key)}`
    : null;
  const created = job.created_at_ms ? fmtDateTime(job.created_at_ms, locale) : null;
  const updated = job.updated_at_ms ? fmtDateTime(job.updated_at_ms, locale) : null;
  const localTrigger = isLocalTriggerAutomation(job);
  const triggerCommand = automationTriggerCommand(job);
  const message = automationDetailText(job, tx);
  const messageLabel = localTrigger
    ? tx("settings.automations.fields.command", "Command")
    : tx("settings.automations.fields.message", "Message");
  const schedule = formatAutomationSchedule(job, locale, tx);
  const [messageExpanded, setMessageExpanded] = useState(false);
  const [commandCopied, setCommandCopied] = useState(false);
  const messageNeedsExpansion = automationMessageNeedsExpansion(message);

  useEffect(() => {
    setMessageExpanded(false);
    setCommandCopied(false);
  }, [job.id]);

  return (
    <article className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-settings-surface">
      <div className="shrink-0 border-b border-border/35 px-4 py-3.5 dark:border-white/10 sm:px-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h3 className="min-w-0 truncate text-[18px] font-medium leading-7 text-foreground">
                {job.name || job.id}
              </h3>
              <AutomationStatusBadge tone={status.tone}>{status.label}</AutomationStatusBadge>
              {job.delete_after_run ? (
                <AutomationStatusBadge>{tx("settings.automations.oneShot", "One-time")}</AutomationStatusBadge>
              ) : null}
            </div>
            <p className="mt-1 truncate text-[12.5px] leading-5 text-muted-foreground">
              {schedule} · {origin}
            </p>
          </div>
          <AutomationActionGroup
            job={job}
            actionKey={actionKey}
            onAction={onAction}
            onRequestEdit={onRequestEdit}
            onRequestDelete={onRequestDelete}
          />
        </div>
      </div>

      <div className="grid min-h-0 min-w-0 flex-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_14.5rem]">
        <div className="min-h-0 min-w-0 space-y-3 overflow-y-auto overscroll-contain p-4 sm:p-5">
          <section className="rounded-[20px] bg-background/55 px-4 py-3.5">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-medium leading-none text-muted-foreground/75">
                {messageLabel}
              </div>
              {localTrigger && triggerCommand ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 rounded-full px-2 text-[11.5px]"
                  onClick={() => {
                    void copyTextToClipboard(triggerCommand).then((ok) => {
                      if (ok) setCommandCopied(true);
                    });
                  }}
                >
                  {commandCopied ? (
                    <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <Clipboard className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                  )}
                  {commandCopied
                    ? tx("settings.automations.commandCopied", "Copied")
                    : tx("settings.automations.copyCommand", "Copy")}
                </Button>
              ) : null}
            </div>
            <div
              className={cn(
                "mt-3 whitespace-pre-wrap break-words text-[13px] leading-6 text-foreground/85",
                localTrigger && "font-mono text-[12.5px]",
                !messageExpanded && messageNeedsExpansion && "line-clamp-6",
              )}
            >
              {message}
            </div>
            {messageNeedsExpansion ? (
              <button
                type="button"
                className="mt-3 inline-flex text-[12px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                onClick={() => setMessageExpanded((value) => !value)}
              >
                {messageExpanded
                  ? tx("settings.automations.message.showLess", "Show less")
                  : tx("settings.automations.message.showMore", "Show full message")}
              </button>
            ) : null}
          </section>

          <div className="grid gap-3 md:grid-cols-2">
            <AutomationDetail
              label={tx("settings.automations.labels.next", "Next")}
              title={formatAutomationNextTitle(job, locale, tx)}
            >
              {formatAutomationNext(job, tx)}
            </AutomationDetail>
            <AutomationDetail label={tx("settings.automations.labels.origin", "Linked chat")} title={origin}>
              {originHref ? (
                <a
                  className="inline-flex max-w-full items-center gap-1 text-foreground/80 underline-offset-2 hover:underline"
                  href={originHref}
                >
                  <span className="truncate">{origin}</span>
                  <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                </a>
              ) : (
                origin
              )}
            </AutomationDetail>
          </div>

          {job.state.last_error ? (
            <div className="rounded-[16px] border border-destructive/20 bg-destructive/8 px-3 py-2 text-[12px] leading-5 text-destructive">
              {job.state.last_error}
            </div>
          ) : null}
        </div>

        <aside className="min-h-0 overflow-y-auto overscroll-contain border-t border-border/35 bg-settings-surface p-4 text-[12px] text-muted-foreground lg:border-l lg:border-t-0">
          <div className="grid gap-3">
            <AutomationDetail
              label={tx("settings.automations.labels.schedule", "Schedule")}
              title={schedule}
            >
              {schedule}
            </AutomationDetail>
            <div className="rounded-[18px] bg-background/55 p-3">
              <div className="grid gap-3">
                {created ? (
                  <div>
                    <div className="text-[11px] leading-none text-muted-foreground/75">
                      {tx("settings.automations.labels.created", "Created")}
                    </div>
                    <div className="mt-1.5 text-[12.5px] leading-5 text-foreground/80">{created}</div>
                  </div>
                ) : null}
                {updated ? (
                  <div>
                    <div className="text-[11px] leading-none text-muted-foreground/75">
                      {tx("settings.automations.labels.updated", "Updated")}
                    </div>
                    <div className="mt-1.5 text-[12.5px] leading-5 text-foreground/80">{updated}</div>
                  </div>
                ) : null}
                <div>
                  <div className="text-[11px] leading-none text-muted-foreground/75">ID</div>
                  <div className="mt-1.5 break-all font-mono text-[11.5px] leading-5 text-foreground/70">
                    {job.id}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </article>
  );
}

function AutomationActionGroup({
  job,
  actionKey,
  onAction,
  onRequestEdit,
  onRequestDelete,
}: {
  job: SessionAutomationJob;
  actionKey: string | null;
  onAction: (action: AutomationAction, job: SessionAutomationJob) => void | Promise<void>;
  onRequestEdit: (job: SessionAutomationJob) => void;
  onRequestDelete: (job: SessionAutomationJob) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  const canManage = !job.protected;
  const hasLinkedChat = Boolean(job.origin);
  const localTrigger = isLocalTriggerAutomation(job);
  const canRun = canManage && hasLinkedChat && job.enabled && !job.state.pending && !localTrigger;
  const toggleAction: AutomationAction = job.enabled ? "disable" : "enable";
  const canToggle = canManage && (job.enabled || hasLinkedChat);
  const toggleBusy = actionKey === `${toggleAction}:${job.id}`;

  if (!canManage) {
    return (
      <span className="inline-flex h-9 items-center rounded-full bg-muted px-3 text-[12px] font-medium text-muted-foreground">
        {tx("settings.automations.protected", "Protected")}
      </span>
    );
  }

  return (
    <div className="flex shrink-0 items-center gap-1 rounded-full bg-background/65 p-1">
      <AppsActionButton
        ariaLabel={tx("settings.automations.edit", "Edit")}
        disabled={Boolean(actionKey)}
        onClick={() => onRequestEdit(job)}
      >
        <Pencil className="h-4 w-4" aria-hidden />
      </AppsActionButton>
      {!localTrigger ? (
        <AppsActionButton
          ariaLabel={tx("settings.automations.runNow", "Run now")}
          busy={actionKey === `run:${job.id}`}
          disabled={!canRun}
          onClick={() => void onAction("run", job)}
        >
          <PlayCircle className="h-4 w-4" aria-hidden />
        </AppsActionButton>
      ) : null}
      <AppsActionButton
        ariaLabel={
          job.enabled
            ? tx("settings.automations.pause", "Pause")
            : tx("settings.automations.resume", "Resume")
        }
        busy={toggleBusy}
        disabled={!canToggle}
        onClick={() => void onAction(toggleAction, job)}
      >
        {job.enabled ? (
          <PauseCircle className="h-4 w-4" aria-hidden />
        ) : (
          <PlayCircle className="h-4 w-4" aria-hidden />
        )}
      </AppsActionButton>
      <AppsActionButton
        ariaLabel={tx("settings.automations.delete", "Delete")}
        tone="danger"
        disabled={Boolean(actionKey)}
        onClick={() => onRequestDelete(job)}
      >
        <Trash2 className="h-4 w-4" aria-hidden />
      </AppsActionButton>
    </div>
  );
}

function AutomationStatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "warning";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full px-2.5 text-[11.5px] font-medium",
        tone === "success" &&
          "bg-orange-100/72 text-orange-800 dark:bg-orange-300/12 dark:text-orange-200",
        tone === "warning" &&
          "bg-amber-100/80 text-amber-800 dark:bg-amber-300/14 dark:text-amber-200",
        tone === "neutral" &&
          "bg-white/64 text-muted-foreground dark:bg-background/35 dark:text-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function automationMessageNeedsExpansion(message: string): boolean {
  return message.length > 360 || message.split(/\r?\n/).length > 6;
}

function AutomationDetail({
  label,
  title,
  secondary,
  children,
}: {
  label: string;
  title?: string;
  secondary?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-[17px] bg-background/55 px-3 py-3">
      <div className="text-[11px] font-medium leading-none text-muted-foreground/75">
        {label}
      </div>
      <div className="mt-1.5 min-w-0">
        <div className="line-clamp-2 text-[13px] leading-5 text-foreground/85" title={title}>
          {children}
        </div>
        {secondary ? (
          <div className="mt-0.5 truncate text-[11.5px] leading-4 text-muted-foreground" title={title}>
            {secondary}
          </div>
        ) : null}
      </div>
    </div>
  );
}

type AutomationEveryUnit = "second" | "minute" | "hour" | "day";

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
          aria-describedby={undefined}
          className="w-[min(calc(100vw-2rem),34rem)] rounded-[26px]"
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
                  className="h-10 rounded-[12px]"
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
                    className="min-h-[160px] resize-none rounded-[12px] text-[13px] leading-5"
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
                      className="h-10 rounded-[12px]"
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
                        "h-10 w-full rounded-[12px] border border-input bg-background px-3 text-[13px] text-foreground transition-colors",
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
                      className="h-10 rounded-[12px] font-mono text-[13px]"
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
                      className="h-10 rounded-[12px] text-[13px]"
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
                    className="h-10 rounded-[12px]"
                  />
                </label>
              ) : null}

              {validation ? (
                <div className="rounded-[12px] bg-destructive/8 px-3 py-2 text-[12px] text-destructive">
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
                className="rounded-full"
              >
                {tx("settings.automations.cancel", "Cancel")}
              </Button>
              <Button type="submit" disabled={Boolean(validation) || saving} className="rounded-full">
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
  const { t } = useTranslation();
  const tx = (key: string, fallback: string, values?: Record<string, unknown>) =>
    t(key, { defaultValue: fallback, ...(values ?? {}) });
  return (
    <Dialog open={Boolean(job)} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(calc(100vw-2rem),26rem)] rounded-[26px]">
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
            className="rounded-full"
          >
            {tx("settings.automations.cancel", "Cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => job && void onConfirm(job)}
            disabled={!job || deleting}
            className="rounded-full"
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
  if (!draft.name.trim()) return tx("settings.automations.validation.nameRequired", "Name is required.");
  if (isLocalTriggerAutomation(job)) return null;
  if (!draft.message.trim()) {
    return tx("settings.automations.validation.messageRequired", "Message is required.");
  }
  if (draft.scheduleKind === "every") {
    const value = Number(draft.everyValue);
    if (!Number.isInteger(value) || value <= 0) {
      return tx("settings.automations.validation.intervalRequired", "Interval must be a positive number.");
    }
  }
  if (draft.scheduleKind === "cron" && !draft.cronExpr.trim()) {
    return tx("settings.automations.validation.cronRequired", "Cron expression is required.");
  }
  if (draft.scheduleKind === "at") {
    const atMs = new Date(draft.atLocal).getTime();
    if (!Number.isFinite(atMs)) {
      return tx("settings.automations.validation.timeRequired", "Run time is required.");
    }
    if (atMs <= Date.now() && automationScheduleChanged(draft, job)) {
      return tx("settings.automations.validation.futureRequired", "Run time must be in the future.");
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

const AUTOMATION_FILTER_TONES: Partial<
  Record<AutomationFilter, { text: string; selectedText: string; count: string }>
> = {
  active: {
    text: "text-emerald-600 dark:text-emerald-400",
    selectedText: "text-emerald-700 dark:text-emerald-300",
    count: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  paused: {
    text: "text-amber-600 dark:text-amber-400",
    selectedText: "text-amber-700 dark:text-amber-300",
    count: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  failed: {
    text: "text-rose-600 dark:text-rose-400",
    selectedText: "text-rose-700 dark:text-rose-300",
    count: "bg-rose-500/10 text-rose-700 dark:text-rose-300",
  },
  system: {
    text: "text-sky-600 dark:text-sky-400",
    selectedText: "text-sky-700 dark:text-sky-300",
    count: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  },
};

function automationFilterToneClass(value: AutomationFilter, count: number, selected: boolean): string {
  const tone = AUTOMATION_FILTER_TONES[value];
  if (count <= 0 || !tone) return "";
  return selected ? tone.selectedText : tone.text;
}

function automationFilterCountClass(value: AutomationFilter, count: number): string {
  const tone = AUTOMATION_FILTER_TONES[value];
  return count > 0 && tone ? tone.count : "";
}

function automationStatus(
  job: SessionAutomationJob,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): { label: string; tone: "neutral" | "success" | "warning" } {
  const status = automationStatusKey(job);
  if (status === "system") return { label: tx("settings.automations.status.system", "System"), tone: "neutral" };
  if (status === "running") {
    return { label: tx("settings.automations.status.running", "Running now"), tone: "warning" };
  }
  if (status === "paused") return { label: tx("settings.automations.status.paused", "Paused"), tone: "neutral" };
  if (status === "failed") {
    return { label: tx("settings.automations.status.failed", "Failed"), tone: "warning" };
  }
  if (status === "completed") {
    return { label: tx("settings.automations.status.completed", "Completed"), tone: "neutral" };
  }
  if (status === "idle") {
    return { label: tx("settings.automations.status.noSchedule", "No schedule"), tone: "neutral" };
  }
  return { label: tx("settings.automations.status.active", "Active"), tone: "success" };
}

function automationOriginLabel(
  job: SessionAutomationJob,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  if (job.protected) return tx("settings.automations.origin.system", "System");
  const origin = job.origin;
  if (!origin) return tx("settings.automations.origin.unknown", "No linked chat");
  if (origin.channel !== "websocket") return automationChannelLabel(origin.channel, tx);
  return origin.title || origin.preview || origin.session_key || automationChannelLabel(origin.channel, tx);
}

function automationChannelLabel(
  channel: string,
  tx: (key: string, fallback: string, values?: Record<string, unknown>) => string,
): string {
  const key = channel.trim().toLowerCase();
  const displayName = automationChannelDisplayName(key);
  return displayName
    ? tx(`settings.automations.channels.${key}`, displayName)
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

function automationStatusDotClass(job: SessionAutomationJob): string {
  const status = automationStatusKey(job);
  if (status === "active" || status === "running") return "bg-orange-500";
  if (status === "failed") return "bg-amber-500";
  return "bg-muted-foreground/45";
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
