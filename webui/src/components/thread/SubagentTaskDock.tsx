import { useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CompletedTaskIcon, DelegationIcon, ErrorTaskIcon, StopIcon } from "@/components/icons/product-icons";
import { SubagentTaskButton, useSubagentTasks } from "@/components/thread/SubagentTasks";
import { Button } from "@/components/ui/button";
import { LoadingRing } from "@/components/ui/loading-ring";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
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
  const mobileViewport = useMediaQuery("(max-width: 639px)");
  const [mobile, setMobile] = useState(mobileViewport);
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const { open, setOpen, tasks } = useSubagentActivity(allTasks, inputKey, context.detailOpen || focused || hovered);
  useEffect(() => {
    if (!open && !context.detailOpen) setMobile(mobileViewport);
  }, [open, context.detailOpen, mobileViewport]);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const returnFocusOnClose = useRef(false);
  const composerInput = useRef<HTMLTextAreaElement | null>(null);
  const running = allTasks.filter(isActiveSubagentTask).length;
  const changeOpen = (next: boolean) => {
    if (next) {
      returnFocusOnClose.current = false;
      composerInput.current = trigger.current?.closest(".thread-composer-stack")?.querySelector("textarea") ?? null;
    }
    setOpen(next);
  };
  const restoreFocus = () => (running ? trigger.current : composerInput.current)?.focus({ preventScroll: true });
  const completed = tasks.filter(task => task.state === "done").length;
  const attention = tasks.filter(needsReview).length;
  const progress = t("thread.subagents.progress", { completed, total: tasks.length });
  const summary = running ? t("thread.subagents.active", { count: running })
    : completed === tasks.length ? t("thread.subagents.completed", { count: completed })
      : t("thread.subagents.finished", { count: tasks.length });
  const iconClass = "h-3.5 w-3.5 shrink-0";
  const button = <button ref={trigger} type="button" data-testid="subagent-task-dock-trigger"
    onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
    onPointerEnter={event => { if (event.pointerType === "mouse") setHovered(true); }} onPointerLeave={() => setHovered(false)}
    onClick={() => { if (open) returnFocusOnClose.current = true; }}
    className="flex min-h-11 w-full items-center gap-2.5 rounded-control border border-border/60 bg-background/90 px-3 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9">
    {running ? <LoadingRing className={iconClass} />
      : attention ? <ErrorTaskIcon className={`${iconClass} text-destructive`} aria-hidden />
        : completed === tasks.length ? <CompletedTaskIcon className={`${iconClass} text-emerald-600 dark:text-emerald-400`} aria-hidden />
          : <DelegationIcon className={iconClass} aria-hidden />}
    <span className="shrink-0 font-medium text-foreground">{t("thread.subagents.workTitle")}</span>
    <span className="ml-auto min-w-0 truncate">{summary}</span>
    {running && completed > 0 ? <span className="shrink-0 max-sm:hidden">{t("thread.subagents.completed", { count: completed })}</span> : null}
    {attention ? <span className="shrink-0 text-destructive">{t("thread.subagents.needsReview", { count: attention })}</span> : null}
    <ChevronUp className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-180" : ""}`} aria-hidden />
  </button>;
  const tree = <TaskTree tasks={tasks} />;

  if (!tasks.length) return null;
  return <div data-testid="subagent-task-dock" className="mx-auto mb-1 w-full max-w-[var(--composer-content-width,49.5rem)] px-1 animate-in fade-in-0 slide-in-from-bottom-1 duration-200 motion-reduce:animate-none sm:px-0">
    {mobile ? <Sheet open={open} onOpenChange={changeOpen}>
      <SheetTrigger asChild>{button}</SheetTrigger>
      <SheetContent side="bottom" className="max-h-[min(70dvh,var(--app-viewport-height,70dvh))] gap-0 overflow-hidden rounded-t-modal border-t p-0 pb-[env(safe-area-inset-bottom)] duration-200"
        style={{ bottom: "max(0px, calc(100dvh - var(--app-viewport-top, 0px) - var(--app-viewport-height, 100dvh)))" }}
        overlayClassName="bg-black/20 backdrop-blur-[8px]"
        closeButtonClassName="right-2 top-2 grid h-11 w-11 place-items-center rounded-full"
        onInteractOutside={event => { if (context.detailOpen) event.preventDefault(); }}
        onOpenAutoFocus={event => { if (context.detailOpen) event.preventDefault(); }}
        onCloseAutoFocus={event => { event.preventDefault(); if (!context.detailOpen) restoreFocus(); }}>
        <div className="shrink-0 space-y-1 border-b px-5 py-4 pr-14">
          <SheetTitle className="text-sm">{t("thread.subagents.workTitle")}</SheetTitle>
          <SheetDescription className="text-xs">{progress}</SheetDescription>
        </div>
        {tree}
      </SheetContent>
    </Sheet> : <Popover open={open} onOpenChange={changeOpen}>
      <PopoverTrigger asChild>{button}</PopoverTrigger>
      <PopoverContent side="top" align="start" sideOffset={8} avoidCollisions
        aria-label={t("thread.subagents.workTitle")}
        className="flex max-h-[min(28rem,55dvh,var(--radix-popover-content-available-height))] w-[var(--radix-popover-trigger-width)] flex-col overflow-hidden p-0 duration-200 data-[state=open]:slide-in-from-bottom-1 data-[state=closed]:slide-out-to-bottom-1 motion-reduce:data-[state=open]:animate-none motion-reduce:data-[state=closed]:animate-none"
        onInteractOutside={event => { if (context.detailOpen) event.preventDefault(); }}
        onOpenAutoFocus={event => { if (context.detailOpen) event.preventDefault(); }}
        onEscapeKeyDown={() => { returnFocusOnClose.current = true; }}
        onCloseAutoFocus={event => {
          if (context.detailOpen || returnFocusOnClose.current || (!running && document.activeElement === document.body)) {
            event.preventDefault();
            if (!context.detailOpen) restoreFocus();
          }
        }}>
        <div className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 text-xs">
          <h2 className="font-medium">{t("thread.subagents.workTitle")}</h2>
          <span className="text-muted-foreground">{progress}</span>
        </div>
        {tree}
      </PopoverContent>
    </Popover>}
  </div>;
}

function TaskTree({ tasks }: { tasks: ObservedSubagentTask[] }) {
  const { t } = useTranslation("common");
  const context = useSubagentTasks()!;
  return <div data-testid="subagent-task-tree" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-3 scrollbar-thin">
    <ol className="pr-1">
      {tasks.map(task => <li key={task.task_id} data-task-state={task.state}
        className="relative ml-3 border-l border-border/70 pb-2 pl-2 animate-in fade-in-0 slide-in-from-bottom-1 duration-200 motion-reduce:animate-none last:border-transparent last:pb-0">
        <span aria-hidden className={`absolute -left-px top-0 h-[23px] w-3 rounded-bl-[6px] border-b border-l ${task.state === "done" ? "border-emerald-500/45" : "border-border"}`} />
        <div className="relative flex min-w-0 items-center gap-1">
          <SubagentTaskButton task={task} surface="activity" />
          {task.state === "queued" || task.state === "running" ? <Button type="button" variant="ghost" size="icon"
            className="h-11 w-11 shrink-0 sm:h-9 sm:w-9" aria-label={t("thread.subagents.stopTask", { label: task.label })}
            disabled={context.stoppingId !== null} onClick={() => void context.stop(task)}>
            <StopIcon className="h-3 w-3" aria-hidden />
          </Button> : null}
        </div>
        {isActiveSubagentTask(task) && task.tool_events.length ? <ul className="ml-[19px] space-y-1 border-l border-border/60 pb-1 pl-3 text-xs text-muted-foreground">
          {task.tool_events.map((tool, index) => <li key={`${index}:${tool.name}`} className="flex min-h-5 min-w-0 items-center gap-2">
            {tool.status === "running" ? <LoadingRing className="h-3 w-3 shrink-0" />
              : tool.status === "error" ? <ErrorTaskIcon className="h-3 w-3 shrink-0 text-destructive" aria-hidden />
                : <span className="h-1 w-1 shrink-0 rounded-full bg-current opacity-50" aria-hidden />}
            <span className="truncate">{tool.name}</span>
          </li>)}
        </ul> : null}
        {task.error ? <p className="ml-[29px] line-clamp-2 break-words px-1 text-xs text-destructive">{task.error}</p>
          : task.state === "done" && task.result ? <p className="ml-[29px] line-clamp-2 break-words px-1 text-xs text-muted-foreground">
            {task.result.trim().slice(0, 240)}
          </p> : null}
      </li>)}
    </ol>
    {context.stopError ? <p role="alert" className="px-3 pt-2 text-xs text-destructive">{context.stopError}</p> : null}
  </div>;
}
