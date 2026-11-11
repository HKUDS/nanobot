import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { ErrorTaskIcon, StopIcon } from "@/components/icons/product-icons";
import { SubagentTaskButton, useSubagentTasks } from "@/components/thread/SubagentTasks";
import { Button } from "@/components/ui/button";
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
  const ownedPointerDown = useRef<PointerEvent | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const gesture = useRef<{ pointerId: number; x: number; y: number; height: number; wasOpen: boolean; dragged: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [treeMounted, setTreeMounted] = useState(false);
  const [listMaxHeight, setListMaxHeight] = useState(400);
  const [expandedHeight, setExpandedHeight] = useState(0);
  const [dragHeight, setDragHeight] = useState<number | null>(null);
  const { open, setOpen, tasks } = useSubagentActivity(allTasks, inputKey, context.detailOpen || focused || hovered || dragHeight !== null);
  const visible = tasks.length > 0;
  const running = allTasks.filter(isActiveSubagentTask).length;
  const composerInput = () => root.current?.closest(".thread-composer-stack")?.querySelector("textarea");
  const changeOpen = (next: boolean, returnFocus = false, preserveFeedback = false) => {
    if (next === open) return;
    if (next) setTreeMounted(true);
    setOpen(next, { preserveFeedback });
    if (!next && returnFocus) (running ? trigger.current : composerInput())?.focus({ preventScroll: true });
  };
  const finishExit = useCallback(() => setTreeMounted(false), []);
  const cancelGesture = () => {
    const start = gesture.current;
    if (!start) return;
    gesture.current = null;
    suppressClick.current = true;
    if (trigger.current?.hasPointerCapture(start.pointerId)) trigger.current.releasePointerCapture(start.pointerId);
    setDragHeight(null);
    changeOpen(start.wasOpen, false, true);
  };

  useLayoutEffect(() => {
    const node = trigger.current;
    if (!node) return;
    const preventNativeDrag = (event: TouchEvent) => {
      if (gesture.current && suppressClick.current) event.preventDefault();
    };
    // React touch handlers are passive; cancel native inertia only after tap slop.
    node.addEventListener("touchmove", preventNativeDrag, { passive: false });
    return () => node.removeEventListener("touchmove", preventNativeDrag);
  }, [visible]);

  useLayoutEffect(() => {
    if (!treeMounted || !root.current) return;
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
  }, [treeMounted]);

  useLayoutEffect(() => {
    if (!treeMounted || !content.current) return;
    const node = content.current;
    const measure = () => setExpandedHeight(node.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [treeMounted]);

  useEffect(() => {
    if (open || dragHeight !== null || !treeMounted) return;
    const animations = panel.current?.getAnimations?.() ?? [];
    if (!animations.length) { finishExit(); return; }
    let cancelled = false;
    void Promise.allSettled(animations.map(animation => animation.finished)).then(() => {
      if (!cancelled) finishExit();
    });
    return () => { cancelled = true; };
  }, [open, dragHeight, treeMounted, finishExit]);

  useEffect(() => {
    if ((!open && dragHeight === null) || context.detailOpen) return;
    const outside = (event: PointerEvent) => {
      const target = event.target;
      if (gesture.current || ownedPointerDown.current === event || !(target instanceof Element) || root.current?.closest(".thread-composer-stack")?.contains(target)) return;
      // Dismissing on blank space must not strand focus after the last task.
      const focusable = target.closest("button, a[href], input, textarea, select, [tabindex], [contenteditable=true]");
      const returnFocus = !running && !focusable;
      if (returnFocus) event.preventDefault();
      changeOpen(false, returnFocus);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.isComposing || event.defaultPrevented) return;
      event.preventDefault();
      if (gesture.current) cancelGesture();
      else changeOpen(false, !!root.current?.contains(document.activeElement) || (!running && document.activeElement === document.body));
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("keydown", escape);
    };
  });

  const completed = tasks.filter(task => task.state === "done").length;
  const attention = tasks.filter(needsReview).length;
  const progress = t("thread.subagents.progress", { completed, total: tasks.length });
  const summary = running ? t("thread.subagents.running", { count: running })
    : completed === tasks.length ? t("thread.subagents.completed", { count: completed })
      : t("thread.subagents.finished", { count: tasks.length });
  const title = t("thread.subagents.workTitle");

  if (!visible) return null;
  return <div ref={root} data-testid="subagent-task-dock" className="subagent-task-dock relative mx-auto h-11 sm:h-7"
    onPointerDownCapture={event => { ownedPointerDown.current = event.nativeEvent; }}>
    <div className="absolute inset-x-0 bottom-0 z-30 overflow-hidden rounded-t-2xl border border-b-0 border-border/70 bg-card shadow-[0_-4px_20px_rgba(15,23,42,0.06)] dark:shadow-[0_-4px_20px_rgba(0,0,0,0.24)]">
      <HoverHint enabled={!open && dragHeight === null} content={`${title} · ${summary}`}>
        <button ref={trigger} type="button" data-testid="subagent-task-dock-trigger"
          aria-expanded={open} aria-controls={panelId}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          onPointerEnter={event => { if (event.pointerType === "mouse") setHovered(true); }} onPointerLeave={() => setHovered(false)}
          onPointerDown={event => {
            if (event.button !== 0 || !event.isPrimary || gesture.current) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            const height = panel.current?.getBoundingClientRect().height ?? 0;
            gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, height, wasOpen: open, dragged: false };
            suppressClick.current = false;
            setTreeMounted(true);
            setDragHeight(height);
          }}
          onPointerMove={event => {
            const start = gesture.current;
            if (!start || start.pointerId !== event.pointerId) return;
            const dy = event.clientY - start.y;
            const dx = Math.abs(event.clientX - start.x);
            suppressClick.current ||= Math.hypot(dx, dy) > 6;
            if (!start.dragged && (Math.abs(dy) <= 6 || Math.abs(dy) <= dx)) return;
            start.dragged = true;
            const height = Math.max(0, Math.min(content.current!.getBoundingClientRect().height, start.height - dy));
            if (height > 0) changeOpen(true);
            setDragHeight(height);
          }}
          onPointerUp={event => {
            const start = gesture.current;
            if (!start || start.pointerId !== event.pointerId) return;
            gesture.current = null;
            const dy = event.clientY - start.y;
            const dx = Math.abs(event.clientX - start.x);
            suppressClick.current ||= Math.hypot(dx, dy) > 6;
            event.currentTarget.releasePointerCapture(event.pointerId);
            setDragHeight(null);
            const next = start.dragged && Math.abs(dy) >= 24 ? dy < 0 : start.wasOpen;
            changeOpen(next, start.dragged && !next, !start.wasOpen && !next);
          }}
          onPointerCancel={event => { if (gesture.current?.pointerId === event.pointerId) cancelGesture(); }}
          onLostPointerCapture={event => { if (gesture.current?.pointerId === event.pointerId) cancelGesture(); }}
          onClick={event => {
            if (suppressClick.current && event.detail !== 0) { suppressClick.current = false; return; }
            changeOpen(!open, open);
          }}
          className="group flex h-11 w-full touch-none select-none items-center justify-center text-muted-foreground outline-none transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring active:cursor-grabbing motion-reduce:transition-none sm:h-7 sm:cursor-grab">
          <span aria-hidden className="h-1 w-8 rounded-full bg-current opacity-30 transition-opacity group-hover:opacity-60 motion-reduce:transition-none" />
          <span className="sr-only">{title} · {summary}
            {attention ? ` · ${t("thread.subagents.needsReview", { count: attention })}` : ""}
          </span>
        </button>
      </HoverHint>
      <div ref={panel} id={panelId} role="region" aria-label={title} aria-describedby={progressId}
        hidden={!treeMounted} aria-hidden={open ? undefined : true} {...(!open ? { inert: "" } : {})}
        className="overflow-hidden transition-[height] duration-200 ease-out motion-reduce:transition-none"
        style={{ height: dragHeight === null ? open ? expandedHeight : 0 : Math.min(dragHeight, expandedHeight), transition: dragHeight === null ? undefined : "none" }}>
        <p id={progressId} className="sr-only">{progress}</p>
        <div ref={content}>{treeMounted ? <TaskTree tasks={tasks} maxHeight={listMaxHeight} /> : null}</div>
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
        onClick={event => {
          const target = event.target;
          if (event.defaultPrevented || !(target instanceof Element) || !event.currentTarget.contains(target)
            || target.closest("button, a[href], input, textarea, select, summary, [role=button], [role=link], [contenteditable=true]")) return;
          const selection = window.getSelection();
          if (selection && !selection.isCollapsed && selection.containsNode(event.currentTarget, true)) return;
          context.open(task, event.currentTarget.querySelector<HTMLButtonElement>("[data-subagent-id]")!);
        }}
        className="cursor-pointer rounded-lg transition-colors duration-150 hover:bg-muted/50 focus-within:bg-muted/50 motion-reduce:transition-none">
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
            {tool.status === "error" ? <ErrorTaskIcon className="h-3 w-3 shrink-0 text-destructive" aria-hidden />
              : <span className="h-1 w-1 shrink-0 rounded-full bg-current opacity-50" aria-hidden />}
            <span className="truncate font-mono">{tool.name}</span>
          </li>)}
        </ul> : null}
        {task.error ? <p className="ml-[38px] line-clamp-2 break-words pb-2 pr-3 text-xs leading-5 text-destructive">{task.error}</p>
          : task.state === "done" && task.result ? <div className="ml-[38px] min-w-0 pb-2 pr-3">
            <MarkdownText className="text-muted-foreground [--text-reading-size:0.75rem]">{task.result}</MarkdownText>
          </div> : null}
      </li>)}
    </ol>
    {context.stopError ? <p role="alert" className="px-3 pt-2 text-xs text-destructive">{context.stopError}</p> : null}
  </div>;
}
