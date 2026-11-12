import {
  StopIcon,
  QueuedTaskIcon,
  StoppingTaskIcon,
  CancelledTaskIcon,
  IncompleteTaskIcon,
  InterruptedTaskIcon,
  ErrorTaskIcon,
} from "@/components/icons/product-icons";
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { LoadingRing } from "@/components/ui/loading-ring";
import { HoverHint } from "@/components/ui/hover-hint";
import { SubagentThread } from "@/components/thread/SubagentThread";
import { ComposerActionIcon } from "@/components/thread/ComposerActionIcon";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { useThreadVisibility } from "@/hooks/useThreadVisibility";
import { cancelSubagentTask, fetchSubagentTasks } from "@/lib/api";
import type { NanobotClient } from "@/lib/nanobot-client";
import { isActiveSubagentTask, isSubagentTask, mergeSubagentTasks, type ObservedSubagentTask } from "@/lib/subagent-tasks";
import type { SubagentTaskSnapshot } from "@/lib/types";

interface TaskContext {
  sessionKey: string | null;
  available: boolean;
  detailOpen: boolean;
  tasks: ObservedSubagentTask[];
  stopError: string | null;
  stoppingId: string | null;
  open: (task: SubagentTaskSnapshot, trigger: HTMLButtonElement) => void;
  stop: (task: SubagentTaskSnapshot) => Promise<void>;
  register: (key: string, button: HTMLButtonElement | null, previous: HTMLButtonElement | null) => void;
}
const TasksContext = createContext<TaskContext | null>(null);

export function useSubagentTasks() {
  return useContext(TasksContext);
}

interface SubagentTasksProviderProps {
  client: Pick<NanobotClient, "requestMutation" | "onChat" | "onStatus">;
  sessionKey: string | null;
  token: string;
  enabled: boolean;
  liveEvents: boolean;
  historyEnabled?: boolean;
  turnIds: string[];
  windowReady?: boolean;
  active?: boolean;
  children: ReactNode;
}

export function SubagentTasksProvider({ client, sessionKey, token, enabled, liveEvents, historyEnabled = false, turnIds, windowReady = true, active = true, children }: SubagentTasksProviderProps) {
  const { t } = useTranslation("common");
  const pageVisible = usePageVisibility();
  const paneVisible = useThreadVisibility();
  const [tasks, setTasks] = useState<ObservedSubagentTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const scopeGeneration = useRef(0);
  const mounted = useRef(true);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const detailPanel = useRef<HTMLDivElement | null>(null);
  const taskRef = useRef(tasks);
  taskRef.current = tasks;
  const windowScope = { turnIds };
  const windowKey = JSON.stringify(windowScope);
  const windowRef = useRef(windowScope);
  windowRef.current = windowScope;
  const windowKeyRef = useRef(windowKey);
  windowKeyRef.current = windowKey;
  const readState = useMemo(() => ({
    turnIds: new Set<string>(), inFlight: false, force: false, epoch: 0,
  }), [client, sessionKey]);
  const readStateRef = useRef(readState);
  readStateRef.current = readState;
  const refreshRef = useRef<((force: boolean, invalidate?: boolean) => void) | null>(null);
  const mergeTasks = (incoming: SubagentTaskSnapshot[]) => {
    const next = mergeSubagentTasks(taskRef.current, incoming);
    taskRef.current = next;
    setTasks(next);
  };

  useLayoutEffect(() => {
    scopeGeneration.current += 1;
    taskRef.current = [];
    setTasks([]);
    setSelectedId(null);
    setStoppingId(null);
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
    if (!enabled || !active || !pageVisible || !paneVisible || !sessionKey || !token || !liveEvents) return;
    let subscribing = true;
    const unsubscribeChat = client.onChat(sessionKey.slice("websocket:".length), (event) => {
      if (readStateRef.current === readState && event.event === "subagent_task" && isSubagentTask(event.task)) mergeTasks([event.task]);
    });
    const unsubscribeStatus = client.onStatus((status) => {
      if (!subscribing && status === "open") refreshRef.current?.(true, true);
    });
    subscribing = false;
    return () => { unsubscribeChat(); unsubscribeStatus(); };
  }, [client, enabled, liveEvents, active, sessionKey, token, pageVisible, paneVisible, readState]);

  useEffect(() => {
    if (!enabled || !active || !pageVisible || !paneVisible || !sessionKey || !token || !windowReady) return;
    let cancelled = false;
    let scheduled = false;
    const read = () => {
      if (readState.inFlight) return;
      const full = readState.force;
      const current = windowRef.current;
      const requested = {
        turnIds: current.turnIds.filter((id) => full || !readState.turnIds.has(id)),
      };
      if (!full && requested.turnIds.length === 0) return;
      readState.force = false;
      readState.inFlight = true;
      const requestedKey = windowKeyRef.current;
      const requestedEpoch = readState.epoch;
      const window = {
        ...requested,
        trackedIds: taskRef.current.filter(isActiveSubagentTask).map((task) => task.task_id),
      };
      let succeeded = false;
      void fetchSubagentTasks(token, sessionKey, window).then((payload) => {
        if (!mounted.current || readStateRef.current !== readState) return;
        succeeded = true;
        if (requestedEpoch === readState.epoch) {
          for (const id of requested.turnIds) readState.turnIds.add(id);
        }
        mergeTasks(payload.tasks);
      }).catch(() => {
        // Background read failures retain the last task snapshot and remain retryable.
      }).finally(() => {
        readState.inFlight = false;
        if (readStateRef.current === readState
          && (succeeded || readState.force || requestedKey !== windowKeyRef.current)) refreshRef.current?.(false);
      });
    };
    const refresh = (force: boolean, invalidate = false) => {
      if (cancelled) return;
      if (invalidate) {
        // Events may have been missed on any previously viewed page. Mark all
        // pages stale, then refresh only the current one and revisit others lazily.
        readState.epoch += 1;
        readState.turnIds.clear();
      }
      if (force) readState.force = true;
      if (scheduled) return;
      scheduled = true;
      // Coalesce layout-driven window changes and Strict Mode effect replays.
      queueMicrotask(() => { scheduled = false; if (!cancelled) read(); });
    };
    refreshRef.current = refresh;
    refresh(true, true);
    const focus = () => refresh(true, true);
    window.addEventListener("focus", focus);
    return () => {
      cancelled = true;
      refreshRef.current = null;
      window.removeEventListener("focus", focus);
    };
  }, [client, enabled, active, sessionKey, token, pageVisible, paneVisible, windowReady, readState]);

  useEffect(() => { refreshRef.current?.(false); }, [windowKey]);

  const stop = async (task: SubagentTaskSnapshot) => {
    if (!sessionKey) return;
    const generation = scopeGeneration.current;
    setStoppingId(task.task_id);
    setStopError(null);
    try {
      const next = await cancelSubagentTask(client, sessionKey, task.task_id);
      if (!mounted.current || generation !== scopeGeneration.current) return;
      mergeTasks([next]);
    } catch (reason) {
      if (mounted.current && generation === scopeGeneration.current) setStopError(reason instanceof Error ? reason.message : t("thread.subagents.stopFailed"));
    } finally {
      if (mounted.current && generation === scopeGeneration.current) setStoppingId(null);
    }
  };
  const selected = enabled && active && paneVisible ? tasks.find((task) => task.task_id === selectedId) : undefined;
  const canStopSelected = selected?.state === "queued" || selected?.state === "running";
  const value: TaskContext = {
    sessionKey, available: enabled && active && paneVisible, detailOpen: !!selected,
    tasks: enabled ? tasks : [],
    stopError: enabled ? stopError : null, stoppingId,
    open: (task, target) => { trigger.current = target; setSelectedId(task.task_id); }, stop,
    register: (key, button, previous) => {
      if (button) buttons.current.set(key, button);
      else if (buttons.current.get(key) === previous) buttons.current.delete(key);
    },
  };

  return <TasksContext.Provider value={value}>
      {children}
      <Sheet open={!!selected} onOpenChange={(open) => { if (!open) setSelectedId(null); }}>
        <SheetContent ref={detailPanel} tabIndex={-1}
          className="w-[calc(100vw-1rem)] gap-0 p-0 sm:w-[min(32rem,calc(100vw-1rem))] sm:max-w-none"
          closeButtonClassName="right-2 top-2 grid h-11 w-11 place-items-center rounded-full sm:right-3 sm:top-3 sm:h-9 sm:w-9"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            detailPanel.current?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!active || !paneVisible) return;
          const target = trigger.current?.isConnected ? trigger.current
            : buttons.current.get(`${trigger.current?.dataset.subagentSurface}:${trigger.current?.dataset.subagentId}`);
          const focusTarget = target?.closest("[hidden]")
            ? target.closest("[data-subagent-results]")?.querySelector<HTMLButtonElement>("[aria-expanded]") : target;
          focusTarget?.focus({ preventScroll: true });
        }}>
          <div className="flex min-h-[60px] shrink-0 items-center gap-3 border-b py-2 pl-5 pr-14">
            <SheetTitle className="min-w-0 flex-1 truncate text-base" title={selected?.label}>{selected?.label}</SheetTitle>
            <SheetDescription className={selected?.state === "done" || selected?.state === "running" ? "sr-only" : "flex shrink-0 items-center gap-2 whitespace-nowrap"}>
              {selected ? <>
                {selected.state !== "done" && selected.state !== "running" ? <TaskStateIcon task={selected} /> : null}
                <span>{t(`thread.subagents.states.${selected.state}`)}</span>
              </> : null}
            </SheetDescription>
            {selected && canStopSelected ? <HoverHint content={t("thread.subagents.stopTask", { label: selected.label })}>
              <Button type="button" size="icon"
                className="composer-primary-action touch-target h-11 w-11 shrink-0 rounded-full border border-transparent bg-foreground/[0.045] bg-clip-padding text-foreground/85 hover:bg-foreground/[0.08] hover:text-foreground disabled:text-muted-foreground/50 sm:h-9 sm:w-9"
                aria-label={t("thread.subagents.stopTask", { label: selected.label })} aria-busy={stoppingId === selected.task_id}
                disabled={stoppingId !== null} onClick={() => void stop(selected)}>
                {selected.state === "running" ? <ComposerActionIcon state="stop" /> : <StopIcon className="h-3.5 w-3.5" aria-hidden />}
              </Button>
            </HoverHint> : null}
          </div>
          {canStopSelected && stopError ? <p role="alert" className="px-5 pt-3 text-xs text-destructive">{stopError}</p> : null}
          {selected && sessionKey ? <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-5">
            {selected.state === "interrupted" || selected.error ? <div className="space-y-2 px-5 pb-4 text-sm">
              {selected.state === "interrupted" ? <p className="text-muted-foreground">{t("thread.subagents.interruptedHelp")}</p> : null}
              {selected.error ? <p role="alert" className="whitespace-pre-wrap break-words text-destructive">{selected.error}</p> : null}
            </div> : null}
            <SubagentThread key={`${sessionKey}:${selected.task_id}`} token={token} sessionKey={sessionKey}
              task={selected} historyEnabled={historyEnabled} isStreaming={isActiveSubagentTask(selected)} />
          </div> : null}
        </SheetContent>
      </Sheet>
  </TasksContext.Provider>;
}

function TaskStateIcon({ task }: { task: SubagentTaskSnapshot }) {
  const className = "h-3.5 w-3.5 shrink-0";
  if (task.state === "running") return <LoadingRing className={`${className} text-muted-foreground`} />;
  if (task.state === "done") return <span className={`${className} block`} aria-hidden />;
  const Icon = {
    queued: QueuedTaskIcon, stopping: StoppingTaskIcon,
    cancelled: CancelledTaskIcon, incomplete: IncompleteTaskIcon,
    interrupted: InterruptedTaskIcon, error: ErrorTaskIcon,
  }[task.state];
  const tone = task.state === "error" || task.state === "incomplete" ? "text-destructive" : "text-muted-foreground";
  return <Icon key={task.state} className={`${className} ${tone} animate-in fade-in-0 duration-200 motion-reduce:animate-none`} aria-hidden />;
}

function TaskElapsed({ task }: { task: ObservedSubagentTask }) {
  const pageVisible = usePageVisibility();
  const paneVisible = useThreadVisibility();
  const [now, setNow] = useState(() => performance.now());
  const running = isActiveSubagentTask(task);
  useEffect(() => {
    if (!running || !pageVisible || !paneVisible) return;
    setNow(performance.now());
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, pageVisible, paneVisible]);
  return <>{Math.round(task.elapsed_seconds + (running ? Math.max(0, now - task.observedAtMs) / 1000 : 0))}s</>;
}

export function SubagentTaskButton({ task, surface = "archive" }: { task: ObservedSubagentTask; surface?: "activity" | "archive" }) {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  const button = useRef<HTMLButtonElement | null>(null);
  const activity = surface === "activity";
  const completed = task.state === "done";
  return <button type="button" data-subagent-id={task.task_id} data-subagent-surface={surface} ref={node => {
    context?.register(`${surface}:${task.task_id}`, node, button.current);
    button.current = node;
  }}
    onClick={(event) => context?.open(task, event.currentTarget)}
    className={activity
      ? "grid min-h-11 min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 gap-y-0.5 rounded-lg px-2 py-2 text-left text-[13px] leading-5 transition-colors duration-150 hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none sm:min-h-9 sm:grid-cols-[auto_minmax(0,1fr)_auto_auto] sm:py-1.5"
      : "col-span-full grid min-h-11 min-w-0 grid-cols-subgrid items-center gap-y-0.5 rounded-control py-2 text-left text-[13px] leading-5 hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9 sm:py-1.5"}>
    <span className="col-start-1 row-start-1 self-center"><TaskStateIcon task={task} /></span>
    <span className={`col-start-2 row-start-1 min-w-0 line-clamp-2 break-words font-medium sm:line-clamp-none sm:truncate ${activity ? "" : "col-span-2 sm:col-span-1"}`}>{task.label}</span>
    <span className={completed ? "sr-only" : `col-start-2 row-start-2 text-xs leading-4 text-muted-foreground sm:col-start-3 sm:row-start-1 ${activity ? "" : "col-span-2 sm:col-span-1"}`}>{t(`thread.subagents.states.${task.state}`)}</span>
    <span className={`${activity ? "col-start-3 sm:col-start-4" : "col-start-4"} text-right text-xs tabular-nums text-muted-foreground sm:row-start-1 sm:min-w-[5ch] ${completed ? "row-start-1" : "row-start-2"}`}><TaskElapsed task={task} /></span>
  </button>;
}
