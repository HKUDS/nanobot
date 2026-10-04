import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, CircleAlert, CircleMinus, LoaderCircle, Square, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { MarkdownText } from "@/components/MarkdownText";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { useThreadVisibility } from "@/hooks/useThreadVisibility";
import { cancelSubagentTask, fetchSubagentTasks } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import { isSubagentTask, mergeSubagentTasks, type ObservedSubagentTask } from "@/lib/subagent-tasks";
import type { SubagentTaskSnapshot, UIMessage } from "@/lib/types";

function isActive(task: SubagentTaskSnapshot): boolean {
  return task.state === "queued" || task.state === "running" || task.state === "stopping";
}

interface TaskContext {
  tasks: ObservedSubagentTask[];
  loadError: string | null;
  stopError: string | null;
  stoppingId: string | null;
  open: (task: SubagentTaskSnapshot, trigger: HTMLButtonElement) => void;
  stop: (task: SubagentTaskSnapshot) => Promise<void>;
  register: (id: string, button: HTMLButtonElement | null, previous: HTMLButtonElement | null) => void;
}
const TasksContext = createContext<TaskContext | null>(null);

interface SubagentTasksProviderProps {
  client: Pick<NanobotClient, "requestMutation" | "onChat" | "onStatus">;
  sessionKey: string | null;
  token: string;
  enabled: boolean;
  liveEvents: boolean;
  active?: boolean;
  children: ReactNode;
}

export function SubagentTasksProvider({ client, sessionKey, token, enabled, liveEvents, active = true, children }: SubagentTasksProviderProps) {
  const { t } = useTranslation("common");
  const pageVisible = usePageVisibility();
  const paneVisible = useThreadVisibility();
  const [tasks, setTasks] = useState<ObservedSubagentTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const scopeGeneration = useRef(0);
  const mounted = useRef(true);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const trigger = useRef<HTMLButtonElement | null>(null);

  useLayoutEffect(() => {
    scopeGeneration.current += 1;
    setTasks([]);
    setSelectedId(null);
    setStoppingId(null);
    setLoadError(null);
    setStopError(null);
    return () => { scopeGeneration.current += 1; };
  }, [client, sessionKey]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!active || !paneVisible) setSelectedId(null);
  }, [active, paneVisible]);

  useEffect(() => {
    if (!enabled || !active || !pageVisible || !paneVisible || !sessionKey || !token) return;
    let cancelled = false;
    let refreshing = false;
    let refreshPending = false;
    const refresh = async () => {
      if (refreshing) { refreshPending = true; return; }
      refreshing = true;
      try {
        const payload = await fetchSubagentTasks(token, sessionKey);
        if (!cancelled) {
          setTasks((current) => mergeSubagentTasks(current, payload.tasks));
          setLoadError(null);
        }
      } catch {
        if (!cancelled) setLoadError(t("thread.subagents.loadFailed"));
      } finally {
        refreshing = false;
        if (refreshPending && !cancelled) {
          refreshPending = false;
          void refresh();
        }
      }
    };
    const unsubscribeChat = liveEvents ? client.onChat(sessionKey.slice("websocket:".length), (event) => {
      if (cancelled || event.event !== "subagent_task") return;
      if (!isSubagentTask(event.task)) {
        setLoadError(t("thread.subagents.loadFailed"));
        return;
      }
      setTasks((current) => mergeSubagentTasks(current, [event.task]));
    }) : undefined;
    const unsubscribeStatus = liveEvents ? client.onStatus((status) => {
      if (status === "open") void refresh();
    }) : undefined;
    if (!refreshing) void refresh();
    // Protocol 1 hosts may support task reads without the optional event stream.
    const timer = liveEvents ? undefined : window.setInterval(() => void refresh(), 3000);
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      unsubscribeChat?.();
      unsubscribeStatus?.();
      window.removeEventListener("focus", focus);
    };
  }, [client, enabled, liveEvents, active, sessionKey, token, pageVisible, paneVisible, t]);

  const stop = async (task: SubagentTaskSnapshot) => {
    if (!sessionKey) return;
    const generation = scopeGeneration.current;
    setStoppingId(task.task_id);
    setStopError(null);
    try {
      const next = await cancelSubagentTask(client, sessionKey, task.task_id);
      if (!mounted.current || generation !== scopeGeneration.current) return;
      setTasks((current) => mergeSubagentTasks(current, [next]));
    } catch (reason) {
      if (mounted.current && generation === scopeGeneration.current) setStopError(reason instanceof Error ? reason.message : t("thread.subagents.stopFailed"));
    } finally {
      if (mounted.current && generation === scopeGeneration.current) setStoppingId(null);
    }
  };
  const selected = enabled && active && paneVisible ? tasks.find((task) => task.task_id === selectedId) : undefined;
  const value: TaskContext = {
    tasks: enabled ? tasks : [], loadError: enabled ? loadError : null,
    stopError: enabled ? stopError : null, stoppingId,
    open: (task, target) => { trigger.current = target; setSelectedId(task.task_id); }, stop,
    register: (id, button, previous) => {
      if (button) buttons.current.set(id, button);
      else if (buttons.current.get(id) === previous) buttons.current.delete(id);
    },
  };

  return <TasksContext.Provider value={value}>
      {children}
      <Sheet open={!!selected} onOpenChange={(open) => { if (!open) setSelectedId(null); }}>
        <SheetContent className="w-full gap-0 overflow-hidden border-l p-0 sm:w-[min(32rem,calc(100vw-1rem))] sm:max-w-none"
          overlayClassName="bg-black/20 backdrop-blur-[8px]"
          closeButtonClassName="right-3 top-3 grid h-9 w-9 place-items-center rounded-full hover:bg-muted"
          onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!active || !paneVisible) return;
          const target = trigger.current?.isConnected ? trigger.current
            : buttons.current.get(trigger.current?.dataset.subagentId ?? "");
          const focusTarget = target?.closest("[hidden]")
            ? target.closest("[data-subagent-work]")?.querySelector<HTMLButtonElement>("[aria-expanded]") : target;
          focusTarget?.focus({ preventScroll: true });
        }}>
          <div className="shrink-0 space-y-2 border-b px-5 py-5 pr-14">
            <p className="text-xs text-muted-foreground">{t("thread.subagents.details")}</p>
            <SheetTitle className="break-words text-base">{selected?.label}</SheetTitle>
            <SheetDescription className="flex items-center gap-2">
              {selected ? <><TaskStateIcon task={selected} />{t(`thread.subagents.states.${selected.state}`)}
                <span className="tabular-nums">· <TaskElapsed task={selected} /></span></> : null}
            </SheetDescription>
          </div>
          {selected ? <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-5 text-sm">
            {selected.state === "interrupted" ? <p className="text-muted-foreground">{t("thread.subagents.interruptedHelp")}</p> : null}
            <section className="min-w-0 space-y-2">
              <h3 className="font-medium">{t("thread.subagents.description")}</h3>
              <MarkdownText className="text-sm">{selected.task_description}</MarkdownText>
            </section>
            {selected.error ? <p role="alert" className="whitespace-pre-wrap break-words text-destructive">{selected.error}</p> : null}
            {selected.result ? <section className="min-w-0 space-y-2">
              <h3 className="font-medium">{t(selected.partial ? "thread.subagents.partialResult" : "thread.subagents.result")}</h3>
              <MarkdownText className="text-sm">{selected.result}</MarkdownText>
            </section> : null}
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("thread.subagents.activity")}</summary>
              <p className="py-2">{t("thread.subagents.iteration", { count: selected.iteration })}</p>
              {selected.tool_events.length ? <ul className="space-y-1">
                {selected.tool_events.map((event, index) => <li key={index} className="flex min-w-0 items-center gap-2">
                  <code className="min-w-0 flex-1 break-all">{event.name}</code>
                  <span className="shrink-0">{t(`thread.subagents.toolStates.${event.status}`, { defaultValue: event.status })}</span>
                </li>)}
              </ul> : null}
            </details>
            {Object.keys(selected.receipts).length ? <details className="space-y-2 text-xs text-muted-foreground">
              <summary className="cursor-pointer py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("thread.subagents.messages")}</summary>
              <p>{t("thread.subagents.receiptHelp")}</p>
              {(["accepted", "delivered", "undelivered"] as const).map((receipt) => {
                const count = Object.values(selected.receipts).filter((entry) => entry === receipt).length;
                return count ? <p key={receipt}>{t(`thread.subagents.receipts.${receipt}`, { count })}</p> : null;
              })}
            </details> : null}
          </div> : null}
          {selected && (selected.state === "queued" || selected.state === "running") ? <div className="shrink-0 border-t px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
            <Button type="button" variant="outline" size="sm" disabled={stoppingId !== null}
              onClick={() => void stop(selected)}><Square className="mr-2 h-3 w-3" aria-hidden />{t("thread.subagents.stopTask", { label: selected.label })}</Button>
            {stopError ? <p role="alert" className="mt-2 text-xs text-destructive">{stopError}</p> : null}
          </div> : null}
        </SheetContent>
      </Sheet>
  </TasksContext.Provider>;
}

function TaskStateIcon({ task }: { task: SubagentTaskSnapshot }) {
  const className = "h-3.5 w-3.5 shrink-0";
  if (isActive(task)) return <LoaderCircle className={`${className} animate-spin motion-reduce:animate-none text-muted-foreground`} aria-hidden />;
  if (task.state === "done") return <CheckCircle2 className={`${className} text-emerald-600 dark:text-emerald-400`} aria-hidden />;
  if (task.state === "cancelled") return <CircleMinus className={`${className} text-muted-foreground`} aria-hidden />;
  return <CircleAlert className={`${className} text-destructive`} aria-hidden />;
}

function TaskElapsed({ task }: { task: ObservedSubagentTask }) {
  const pageVisible = usePageVisibility();
  const paneVisible = useThreadVisibility();
  const [now, setNow] = useState(() => performance.now());
  const running = isActive(task);
  useEffect(() => {
    if (!running || !pageVisible || !paneVisible) return;
    setNow(performance.now());
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, pageVisible, paneVisible]);
  return <>{Math.round(task.elapsed_seconds + (running ? Math.max(0, now - task.observedAtMs) / 1000 : 0))}s</>;
}

function TaskButton({ task }: { task: ObservedSubagentTask }) {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  const button = useRef<HTMLButtonElement | null>(null);
  return <button type="button" data-subagent-id={task.task_id} ref={(node) => {
    context?.register(task.task_id, node, button.current);
    button.current = node;
  }}
    onClick={(event) => context?.open(task, event.currentTarget)}
    className="flex min-w-0 flex-1 items-center gap-2.5 rounded-control px-3 py-2.5 text-left text-sm hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    <TaskStateIcon task={task} />
    <span className="min-w-0 flex-1 truncate">{task.label}</span>
    <span className="shrink-0 text-xs text-muted-foreground">{t(`thread.subagents.states.${task.state}`)}</span>
    <span className="shrink-0 text-xs tabular-nums text-muted-foreground"><TaskElapsed task={task} /></span>
    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
  </button>;
}

export function useHasSubagentContent(): boolean {
  const context = useContext(TasksContext);
  return !!context && (context.tasks.length > 0 || !!context.loadError || !!context.stopError);
}

/** Prefer an exact prompt, then its turn's first prompt when replay changed message IDs. */
export function useSubagentTaskGroups(messages: UIMessage[]) {
  const context = useContext(TasksContext);
  const prompts = messages.filter((message) => message.role === "user");
  const byMessage = new Map<string, ObservedSubagentTask[]>();
  const unlinked: ObservedSubagentTask[] = [];
  for (const task of context?.tasks ?? []) {
    const prompt = prompts.find((message) => message.id === task.origin_message_id)
      ?? prompts.find((message) => !!task.origin_turn_id && message.turnId === task.origin_turn_id);
    if (prompt) {
      const group = byMessage.get(prompt.id) ?? [];
      group.push(task);
      byMessage.set(prompt.id, group);
    } else unlinked.push(task);
  }
  return { byMessage, unlinked };
}

export function SubagentWork({ tasks, unlinked = false }: { tasks: ObservedSubagentTask[]; unlinked?: boolean }) {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  const rowsId = useId();
  const [expanded, setExpanded] = useState<boolean | null>(null);
  if (!context || !tasks.length) return null;
  const activeCount = tasks.filter(isActive).length;
  const completedCount = tasks.filter((task) => task.state === "done").length;
  const failedCount = tasks.filter((task) => ["error", "incomplete", "interrupted"].includes(task.state)).length;
  const open = expanded ?? activeCount > 0;
  const summary = activeCount
    ? t("thread.subagents.progress", { completed: completedCount, total: tasks.length })
    : t("thread.subagents.finished", { count: tasks.length });
  const title = t(unlinked ? "thread.subagents.otherWorkTitle" : "thread.subagents.workTitle");
  return <section data-subagent-work aria-label={title} className="thread-message-row mt-3">
    <div className="overflow-hidden rounded-control border border-border/60 bg-muted/15">
      <button type="button" aria-expanded={open} aria-controls={rowsId}
        onClick={() => setExpanded(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-xs text-muted-foreground hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
        <Workflow className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="font-medium">{title}</span>
        <span className="ml-auto min-w-0 text-right">
          {summary}{activeCount ? ` · ${t("thread.subagents.running", { count: activeCount })}` : ""}
          {failedCount ? <span className="ml-2 text-destructive">{t("thread.subagents.needsReview", { count: failedCount })}</span> : null}
        </span>
        <ChevronDown className={`h-3.5 w-3.5 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      <div id={rowsId} hidden={!open} className="border-t border-border/50 py-0.5">
        {unlinked ? <p className="px-3 py-2 text-xs text-muted-foreground">{t("thread.subagents.unlinkedHelp")}</p> : null}
        {tasks.map((task) => <div key={task.task_id} className="flex items-center gap-1 pr-1">
          <TaskButton task={task} />
          {task.state === "queued" || task.state === "running" ? <Button type="button" variant="ghost" size="icon" className="h-9 w-9 shrink-0"
            aria-label={t("thread.subagents.stopTask", { label: task.label })} disabled={context.stoppingId !== null}
            onClick={() => void context.stop(task)}><Square className="h-3 w-3" aria-hidden /></Button> : null}
        </div>)}
      </div>
    </div>
  </section>;
}

export function SubagentTaskErrors() {
  const context = useContext(TasksContext);
  if (!context?.loadError && !context?.stopError) return null;
  return <div className="thread-message-row mt-2 space-y-1 text-xs text-destructive">
    {context.loadError ? <p role="alert">{context.loadError}</p> : null}
    {context.stopError ? <p role="alert">{context.stopError}</p> : null}
  </div>;
}
