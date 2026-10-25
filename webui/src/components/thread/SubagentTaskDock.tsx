import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

import { CompletedTaskIcon, DelegationIcon, ErrorTaskIcon, StopIcon } from "@/components/icons/product-icons";
import { SubagentTaskButton, useSubagentTasks } from "@/components/thread/SubagentTasks";
import { Button } from "@/components/ui/button";
import { DisclosureContent } from "@/components/ui/disclosure";
import { HoverHint } from "@/components/ui/hover-hint";
import { LoadingRing } from "@/components/ui/loading-ring";
import { isActiveSubagentTask, type ObservedSubagentTask } from "@/lib/subagent-tasks";
import { useSubagentActivity } from "@/components/thread/useSubagentActivity";

function needsReview(task: ObservedSubagentTask) {
  return task.state === "error" || task.state === "incomplete" || task.state === "interrupted";
}

export function SubagentTaskDock({ inputKey = null }: { inputKey?: string | null }) {
  const context = useSubagentTasks();
  if (!context?.available || !context.tasks.length) return null;
  return <TaskDock key={context.sessionKey} allTasks={context.tasks} inputKey={inputKey} />;
}

function TaskDock({ allTasks, inputKey }: { allTasks: ObservedSubagentTask[]; inputKey: string | null }) {
  const { t } = useTranslation("common");
  const context = useSubagentTasks()!;
  const panelId = useId();
  const progressId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [treeMounted, setTreeMounted] = useState(false);
  const [listMaxHeight, setListMaxHeight] = useState(400);
  const { open, setOpen, tasks } = useSubagentActivity(allTasks, inputKey, context.detailOpen || focused || hovered);
  const running = allTasks.filter(isActiveSubagentTask).length;
  const composerInput = () => root.current?.closest(".thread-composer-stack")?.querySelector("textarea");
  const changeOpen = (next: boolean, returnFocus = false) => {
    if (next === open) return;
    if (next) setTreeMounted(true);
    setOpen(next);
    if (!next && returnFocus) (running ? trigger.current : composerInput())?.focus({ preventScroll: true });
  };
  const finishExit = useCallback(() => setTreeMounted(false), []);

  useLayoutEffect(() => {
    if (!open || !root.current) return;
    const anchor = root.current;
    const composer = anchor.closest(".thread-composer-stack")!;
    const pane = anchor.closest(".thread-conversation");
    const viewport = window.visualViewport;
    const measure = () => {
      const top = Math.max(viewport?.offsetTop ?? 0, pane?.getBoundingClientRect().top ?? 0);
      const height = Math.min(448, anchor.getBoundingClientRect().bottom - top - 12);
      setListMaxHeight(Math.max(0, height - (trigger.current?.offsetHeight ?? 44) - 2));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(composer);
    if (pane) observer.observe(pane);
    viewport?.addEventListener("resize", measure);
    viewport?.addEventListener("scroll", measure);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      viewport?.removeEventListener("resize", measure);
      viewport?.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  useEffect(() => {
    if (!open || context.detailOpen) return;
    const outside = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || root.current?.closest(".thread-composer-stack")?.contains(target)) return;
      // Dismissing on blank space must not strand focus after the last task.
      const focusable = target.closest("button, a[href], input, textarea, select, [tabindex], [contenteditable=true]");
      const returnFocus = !running && !focusable;
      if (returnFocus) event.preventDefault();
      changeOpen(false, returnFocus);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.isComposing || event.defaultPrevented) return;
      event.preventDefault();
      changeOpen(false, !!root.current?.contains(document.activeElement) || (!running && document.activeElement === document.body));
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("keydown", escape);
    };
  });

  const gesture = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const suppressClick = useRef(false);
  const cancelGesture = (event: PointerEvent<HTMLButtonElement>) => {
    if (gesture.current?.pointerId !== event.pointerId) return;
    gesture.current = null;
    suppressClick.current = true;
  };
  const completed = tasks.filter(task => task.state === "done").length;
  const attention = tasks.filter(needsReview).length;
  const progress = t("thread.subagents.progress", { completed, total: tasks.length });
  const summary = running ? t("thread.subagents.running", { count: running })
    : completed === tasks.length ? t("thread.subagents.completed", { count: completed })
      : t("thread.subagents.finished", { count: tasks.length });
  const title = t("thread.subagents.workTitle");
  const iconClass = "h-3 w-3 shrink-0";

  if (!tasks.length) return null;
  return <div ref={root} data-testid="subagent-task-dock" className="relative mx-auto h-11 w-full max-w-[var(--composer-content-width,49.5rem)] sm:h-7">
    <div className={`absolute inset-x-1 bottom-0 z-40 overflow-hidden rounded-t-2xl rounded-b-lg border sm:inset-x-0 ${open || treeMounted
      ? "border-border/70 bg-background shadow-[0_-4px_20px_rgba(15,23,42,0.06)] dark:shadow-[0_-4px_20px_rgba(0,0,0,0.24)]"
      : "border-transparent"}`}>
      <HoverHint enabled={!open} content={`${title} · ${summary}`}>
        <button ref={trigger} type="button" data-testid="subagent-task-dock-trigger"
          aria-expanded={open} aria-controls={panelId}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          onPointerEnter={event => { if (event.pointerType === "mouse") setHovered(true); }} onPointerLeave={() => setHovered(false)}
          onPointerDown={event => {
            if (event.button !== 0 || !event.isPrimary || gesture.current) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
            suppressClick.current = false;
          }}
          onPointerMove={event => {
            const start = gesture.current;
            if (start && start.pointerId === event.pointerId
              && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) suppressClick.current = true;
          }}
          onPointerUp={event => {
            const start = gesture.current;
            if (!start || start.pointerId !== event.pointerId) return;
            gesture.current = null;
            const dy = event.clientY - start.y;
            const dx = Math.abs(event.clientX - start.x);
            suppressClick.current ||= Math.hypot(dx, dy) > 6;
            event.currentTarget.releasePointerCapture(event.pointerId);
            if (Math.abs(dy) >= 24 && Math.abs(dy) > dx) changeOpen(dy < 0, dy > 0);
          }}
          onPointerCancel={cancelGesture} onLostPointerCapture={cancelGesture}
          onClick={event => {
            if (suppressClick.current && event.detail !== 0) { suppressClick.current = false; return; }
            changeOpen(!open, open);
          }}
          className="group mx-auto flex h-11 w-24 touch-none select-none items-center justify-center gap-2 rounded-full text-muted-foreground outline-none transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring active:cursor-grabbing motion-reduce:transition-none sm:h-7 sm:cursor-grab">
          <span aria-hidden className="h-1 w-8 rounded-full bg-current opacity-30 transition-opacity group-hover:opacity-60 motion-reduce:transition-none" />
          {!running && (attention ? <ErrorTaskIcon className={`${iconClass} text-destructive`} aria-hidden />
            : completed === tasks.length ? <CompletedTaskIcon className={`${iconClass} text-emerald-600 dark:text-emerald-400`} aria-hidden />
              : <DelegationIcon className={iconClass} aria-hidden />)}
          <span className="sr-only">{title} · {summary}
            {attention ? ` · ${t("thread.subagents.needsReview", { count: attention })}` : ""}
          </span>
        </button>
      </HoverHint>
      <div id={panelId} role="region" aria-label={title} aria-describedby={progressId} hidden={!open && !treeMounted}>
        <p id={progressId} className="sr-only">{progress}</p>
        <DisclosureContent open={open} onExitComplete={finishExit}>
          {open || treeMounted ? <TaskTree tasks={tasks} maxHeight={listMaxHeight} /> : null}
        </DisclosureContent>
      </div>
    </div>
  </div>;
}

function TaskTree({ tasks, maxHeight }: { tasks: ObservedSubagentTask[]; maxHeight: number }) {
  const { t } = useTranslation("common");
  const context = useSubagentTasks()!;
  return <div data-testid="subagent-task-tree" style={{ maxHeight }} className="min-h-0 overflow-y-auto overscroll-contain p-1.5 pt-0 scrollbar-thin">
    <ol className="space-y-0.5">
      {tasks.map(task => <li key={task.task_id} data-task-state={task.state}
        className="rounded-lg transition-colors duration-150 hover:bg-muted/50 focus-within:bg-muted/50 motion-reduce:transition-none">
        <div className="flex min-w-0 items-center gap-0.5">
          <SubagentTaskButton task={task} surface="activity" />
          {task.state === "queued" || task.state === "running" ? <HoverHint content={t("thread.subagents.stopTask", { label: task.label })}>
            <Button type="button" variant="ghost" size="icon"
              className="h-11 w-11 shrink-0 rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive motion-reduce:transition-none sm:h-9 sm:w-9"
              aria-label={t("thread.subagents.stopTask", { label: task.label })} aria-busy={context.stoppingId === task.task_id}
              disabled={context.stoppingId !== null} onClick={() => void context.stop(task)}>
              {context.stoppingId === task.task_id ? <LoadingRing className="h-3.5 w-3.5" /> : <StopIcon className="h-3.5 w-3.5" fill="currentColor" aria-hidden />}
            </Button>
          </HoverHint> : null}
        </div>
        {isActiveSubagentTask(task) && task.tool_events.length ? <ul className="ml-[21px] mr-2 space-y-1 border-l border-border/60 pb-2 pl-4 text-[11px] leading-4 text-muted-foreground">
          {task.tool_events.map((tool, index) => <li key={`${index}:${tool.name}`} className="flex min-h-5 min-w-0 items-center gap-2">
            {tool.status === "running" ? <LoadingRing className="h-3 w-3 shrink-0" />
              : tool.status === "error" ? <ErrorTaskIcon className="h-3 w-3 shrink-0 text-destructive" aria-hidden />
                : <span className="h-1 w-1 shrink-0 rounded-full bg-current opacity-50" aria-hidden />}
            <span className="truncate font-mono">{tool.name}</span>
          </li>)}
        </ul> : null}
        {task.error ? <p className="ml-[38px] line-clamp-2 break-words pb-2 pr-3 text-xs leading-5 text-destructive">{task.error}</p>
          : task.state === "done" && task.result ? <p className="ml-[38px] line-clamp-2 break-words pb-2 pr-3 text-xs leading-5 text-muted-foreground">
            {task.result.trim().slice(0, 240)}
          </p> : null}
      </li>)}
    </ol>
    {context.stopError ? <p role="alert" className="px-3 pt-2 text-xs text-destructive">{context.stopError}</p> : null}
  </div>;
}
