import { useId, useMemo, useState, type ComponentProps } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SubagentTaskButton, useSubagentTasks } from "@/components/thread/SubagentTasks";
import { ThreadMessages } from "@/components/thread/ThreadMessages";
import { isActiveSubagentTask, type ObservedSubagentTask } from "@/lib/subagent-tasks";
import type { UIMessage } from "@/lib/types";

/** Exact initiating prompts win; replayed IDs fall back to the turn's first user message. */
function groupResults(messages: UIMessage[], tasks: ObservedSubagentTask[]) {
  const promptsById = new Map<string, UIMessage>();
  const firstPromptByTurn = new Map<string, UIMessage>();
  for (const message of messages) {
    if (message.role !== "user") continue;
    promptsById.set(message.id, message);
    if (message.turnId && !firstPromptByTurn.has(message.turnId)) {
      firstPromptByTurn.set(message.turnId, message);
    }
  }

  const byMessage = new Map<string, ObservedSubagentTask[]>();
  for (const task of tasks) {
    if (isActiveSubagentTask(task)) continue;
    const prompt = (task.origin_message_id ? promptsById.get(task.origin_message_id) : undefined)
      ?? (task.origin_turn_id ? firstPromptByTurn.get(task.origin_turn_id) : undefined);
    if (!prompt) continue;
    const group = byMessage.get(prompt.id) ?? [];
    group.push(task);
    byMessage.set(prompt.id, group);
  }
  return byMessage;
}

export function SubagentThreadMessages(props: ComponentProps<typeof ThreadMessages>) {
  const context = useSubagentTasks();
  const sessionKey = context?.sessionKey;
  const groups = useMemo(() => groupResults(props.messages, context?.tasks ?? []), [props.messages, context?.tasks]);
  const [archive, setArchive] = useState(() => ({ sessionKey, expanded: new Set<string>() }));
  // Reset only the disclosures; the outgoing transcript must not remount during handoff.
  if (archive.sessionKey !== sessionKey) {
    setArchive({ sessionKey, expanded: new Set<string>() });
  }
  const expanded = (results: ObservedSubagentTask[]) => results.some(task => archive.expanded.has(task.task_id));
  const toggle = (results: ObservedSubagentTask[]) => {
    props.onActivityToggle?.();
    setArchive(current => {
      const next = new Set(current.expanded);
      const close = results.some(task => current.expanded.has(task.task_id));
      for (const task of results) {
        if (close) next.delete(task.task_id);
        else next.add(task.task_id);
      }
      return { sessionKey, expanded: next };
    });
  };

  return <ThreadMessages {...props}
    afterUserMessage={(message) => {
      const results = groups.get(message.id);
      return <>
        {props.afterUserMessage?.(message)}
        {results ? <SubagentResults tasks={results} expanded={expanded(results)}
          onToggle={() => toggle(results)} /> : null}
      </>;
    }} />;
}

function SubagentResults({ tasks, expanded, onToggle }: {
  tasks: ObservedSubagentTask[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation("common");
  const rowsId = useId();
  const completed = tasks.filter((task) => task.state === "done").length;
  const attention = tasks.filter((task) => task.state === "error" || task.state === "incomplete" || task.state === "interrupted").length;
  const title = t("thread.subagents.workTitle");
  const summary = completed === tasks.length
    ? t("thread.subagents.completed", { count: completed })
    : t("thread.subagents.finished", { count: tasks.length });

  return <section data-subagent-results aria-label={title}
    className="thread-message-row mt-2 grid grid-cols-[1rem_minmax(0,1fr)_minmax(6rem,max-content)_3rem] items-center gap-x-2.5">
    <button type="button" data-thread-disclosure data-subagent-results-summary aria-expanded={expanded} aria-controls={rowsId}
      onClick={onToggle}
      className="col-span-full grid min-h-11 w-full min-w-0 grid-cols-subgrid items-center gap-y-0.5 rounded-control py-2 text-left text-[13px] leading-5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none sm:min-h-9 sm:py-1.5">
      <img src="/brand/nanobot_mark.svg" alt="" draggable={false} className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 truncate font-medium">{title}</span>
      <span className="col-start-3 row-start-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs leading-4">
        <span>{summary}</span>
        {attention ? <span className="text-destructive">{t("thread.subagents.needsReview", { count: attention })}</span> : null}
      </span>
      <ChevronRight className={`col-start-4 row-start-1 h-3.5 w-3.5 shrink-0 justify-self-end transition-transform motion-reduce:transition-none ${expanded ? "rotate-90" : ""}`} aria-hidden />
    </button>
    <div id={rowsId} hidden={!expanded} className={`col-span-full grid-cols-subgrid pb-1 ${expanded ? "grid" : "hidden"}`}>
      <ol className="col-span-full grid grid-cols-subgrid">
        {tasks.map((task) => <li key={task.task_id} className="col-span-full grid min-w-0 grid-cols-subgrid">
          <SubagentTaskButton task={task} surface="archive" />
        </li>)}
      </ol>
    </div>
  </section>;
}
