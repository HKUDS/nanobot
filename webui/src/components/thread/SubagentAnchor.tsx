import { useId } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SubagentTaskButton, useSubagentTasks } from "@/components/thread/SubagentTasks";
import type { SubagentAnchor as Anchor } from "@/lib/subagent-anchor-groups";
import { isActiveSubagentTask } from "@/lib/subagent-tasks";

/** Completed tasks remain at their durable places in the parent transcript. */
export function SubagentAnchor({ anchors, expanded, onToggle }: {
  anchors: Anchor[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation("common");
  const rowsId = useId();
  const context = useSubagentTasks();
  const tasks = anchors.flatMap((anchor) => {
    const task = context?.tasks.find((candidate) => candidate.task_id === anchor.taskId
      && candidate.origin_call_id === anchor.callId);
    return task && !isActiveSubagentTask(task) ? [task] : [];
  });
  if (!tasks.length) return null;
  const title = t("thread.subagents.workTitle");
  const completed = tasks.filter((task) => task.state === "done").length;
  const attention = tasks.filter((task) => task.state === "error" || task.state === "incomplete" || task.state === "interrupted").length;
  return <section data-subagent-results aria-label={title}
    className="thread-message-row mt-2 grid grid-cols-[1rem_minmax(0,1fr)_minmax(6rem,max-content)_3rem] items-center gap-x-2.5">
    <button type="button" data-thread-disclosure data-subagent-results-summary aria-expanded={expanded} aria-controls={rowsId}
      onClick={onToggle}
      className="col-span-full grid min-h-11 w-full min-w-0 grid-cols-subgrid items-center gap-y-0.5 rounded-control py-2 text-left text-[13px] leading-5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none sm:min-h-9 sm:py-1.5">
      <img src="/brand/nanobot_mark.svg" alt="" draggable={false} className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 truncate font-medium">{title}</span>
      <span className="col-start-3 row-start-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs leading-4">
        <span>{t(completed === tasks.length ? "thread.subagents.completed" : "thread.subagents.finished", { count: tasks.length })}</span>
        {attention ? <span className="text-destructive">{t("thread.subagents.needsReview", { count: attention })}</span> : null}
      </span>
      <ChevronRight className={`col-start-4 row-start-1 h-3.5 w-3.5 shrink-0 justify-self-end transition-transform motion-reduce:transition-none ${expanded ? "rotate-90" : ""}`} aria-hidden />
    </button>
    <div id={rowsId} hidden={!expanded} className={`col-span-full grid-cols-subgrid pb-1 ${expanded ? "grid" : "hidden"}`}>
      {tasks.map((task) => <SubagentTaskButton key={task.task_id} task={task} />)}
    </div>
  </section>;
}
