import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronRight, LoaderCircle, Square, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { useThreadVisibility } from "@/hooks/useThreadVisibility";
import { cancelSubagentTask, fetchSubagentTasks, type WebUIMutationTransport } from "@/lib/api";
import type { SubagentTaskSnapshot } from "@/lib/types";

function isActive(task: SubagentTaskSnapshot): boolean {
  return task.state === "queued" || task.state === "running" || task.state === "stopping";
}

interface TaskContext {
  tasks: SubagentTaskSnapshot[];
  loadError: string | null;
  stopError: string | null;
  stoppingId: string | null;
  open: (task: SubagentTaskSnapshot, trigger: HTMLButtonElement) => void;
  stop: (task: SubagentTaskSnapshot) => Promise<void>;
  register: (id: string, button: HTMLButtonElement | null, previous: HTMLButtonElement | null) => void;
}
const TasksContext = createContext<TaskContext | null>(null);

interface SubagentTasksProviderProps {
  client: WebUIMutationTransport;
  sessionKey: string | null;
  token: string;
  enabled: boolean;
  active?: boolean;
  children: ReactNode;
}

export function SubagentTasksProvider({ client, sessionKey, token, enabled, active = true, children }: SubagentTasksProviderProps) {
  const { t } = useTranslation("common");
  const pageVisible = usePageVisibility();
  const paneVisible = useThreadVisibility();
  const [tasks, setTasks] = useState<SubagentTaskSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const revision = useRef(0);
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
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      const currentRevision = revision.current;
      try {
        const payload = await fetchSubagentTasks(token, sessionKey);
        if (!cancelled && currentRevision === revision.current) {
          setTasks(payload.tasks);
          setLoadError(null);
        }
      } catch {
        if (!cancelled) setLoadError(t("thread.subagents.loadFailed"));
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, [enabled, active, sessionKey, token, pageVisible, paneVisible, t]);

  const stop = async (task: SubagentTaskSnapshot) => {
    if (!sessionKey) return;
    const generation = scopeGeneration.current;
    setStoppingId(task.task_id);
    setStopError(null);
    revision.current += 1;
    try {
      const next = await cancelSubagentTask(client, sessionKey, task.task_id);
      if (!mounted.current || generation !== scopeGeneration.current) return;
      revision.current += 1;
      setTasks((current) => current.map((entry) => entry.task_id === next.task_id ? next : entry));
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
      <Dialog open={!!selected} onOpenChange={(open) => { if (!open) setSelectedId(null); }}>
        <DialogContent className="max-w-xl" onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (!active || !paneVisible) return;
          const target = trigger.current?.isConnected ? trigger.current
            : buttons.current.get(trigger.current?.dataset.subagentId ?? "");
          target?.focus({ preventScroll: true });
        }}>
          <DialogHeader>
            <DialogTitle className="break-words pr-6">{selected?.label}</DialogTitle>
            <DialogDescription>{selected ? t(`thread.subagents.states.${selected.state}`) : ""}</DialogDescription>
          </DialogHeader>
          {selected ? <div className="max-h-[65vh] space-y-4 overflow-y-auto text-sm">
            {selected.state === "interrupted" ? <p className="text-muted-foreground">{t("thread.subagents.interruptedHelp")}</p> : null}
            <p className="whitespace-pre-wrap break-words">{selected.task_description}</p>
            <p className="text-xs text-muted-foreground">{t("thread.subagents.iteration", { count: selected.iteration })}</p>
            {selected.tool_events.length ? <p className="text-xs text-muted-foreground">{selected.tool_events.map((event) => event.name).join(", ")}</p> : null}
            {selected.error ? <p role="alert" className="whitespace-pre-wrap break-words text-destructive">{selected.error}</p> : null}
            {selected.result ? <div>
              <p className="mb-1 font-medium">{t(selected.partial ? "thread.subagents.partialResult" : "thread.subagents.result")}</p>
              <p className="whitespace-pre-wrap break-words">{selected.result}</p>
            </div> : null}
            {Object.keys(selected.receipts).length ? <div className="space-y-1 text-xs text-muted-foreground">
              <p>{t("thread.subagents.receiptHelp")}</p>
              {(["accepted", "delivered", "undelivered"] as const).map((receipt) => {
                const count = Object.values(selected.receipts).filter((entry) => entry === receipt).length;
                return count ? <p key={receipt}>{t(`thread.subagents.receipts.${receipt}`, { count })}</p> : null;
              })}
            </div> : null}
          </div> : null}
        </DialogContent>
      </Dialog>
  </TasksContext.Provider>;
}

function TaskButton({ task }: { task: SubagentTaskSnapshot }) {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  const button = useRef<HTMLButtonElement | null>(null);
  return <button type="button" data-subagent-id={task.task_id} ref={(node) => {
    context?.register(task.task_id, node, button.current);
    button.current = node;
  }}
    onClick={(event) => context?.open(task, event.currentTarget)}
    className="flex min-w-0 flex-1 items-center gap-2 rounded-control px-2 py-1.5 text-left text-sm hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {isActive(task) ? <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden /> : <Workflow className="h-3.5 w-3.5 shrink-0" aria-hidden />}
    <span className="min-w-0 flex-1 truncate">{task.label}</span>
    <span className="shrink-0 text-xs text-muted-foreground">{t(`thread.subagents.states.${task.state}`)}</span>
    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{Math.round(task.elapsed_seconds)}s</span>
    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
  </button>;
}

export function ActiveSubagentTasks() {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  if (!context) return null;
  const active = context.tasks.filter(isActive);
  if (!active.length && !context.loadError && !context.stopError) return null;
  return <section aria-label={t("thread.subagents.activeTitle")} className="mx-auto mb-2 w-full max-w-[49.5rem] rounded-control bg-muted/35 px-2 py-1">
    <div className="max-h-40 overflow-y-auto">
      {active.map((task) => <div key={task.task_id} className="flex items-center gap-1">
        <TaskButton task={task} />
        {task.state === "queued" || task.state === "running" ? <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0"
          aria-label={t("thread.subagents.stopTask", { label: task.label })} disabled={context.stoppingId !== null}
          onClick={() => void context.stop(task)}><Square className="h-3 w-3" aria-hidden /></Button> : null}
      </div>)}
    </div>
    {context.loadError ? <p role="alert" className="px-2 py-1 text-xs text-destructive">{context.loadError}</p> : null}
    {context.stopError ? <p role="alert" className="px-2 py-1 text-xs text-destructive">{context.stopError}</p> : null}
  </section>;
}

export function SubagentHistory({ turnId, messageId, unlinked = false }: { turnId?: string; messageId?: string; unlinked?: boolean }) {
  const context = useContext(TasksContext);
  const { t } = useTranslation("common");
  const completed = context?.tasks.filter((task) => !isActive(task) && (unlinked
    ? !task.origin_turn_id && !task.origin_message_id
    : (turnId ? task.origin_turn_id === turnId : false) || (!!messageId && task.origin_message_id === messageId))) ?? [];
  if (!completed.length) return null;
  return <section aria-label={t("thread.subagents.historyTitle")} className="thread-message-row mt-2 flex flex-col items-end gap-1">
    {completed.map((task) => <div key={task.task_id} className="flex w-full max-w-md text-muted-foreground">
      <TaskButton task={task} />
    </div>)}
  </section>;
}
