import { useMemo, useState, type ComponentProps } from "react";
import { buildDisplayUnits, ThreadMessages } from "@/components/thread/ThreadMessages";
import { SubagentAnchor } from "@/components/thread/SubagentAnchor";
import { useSubagentTasks } from "@/components/thread/SubagentTasks";
import { groupSubagentAnchors } from "@/lib/subagent-anchor-groups";
import { isActiveSubagentTask } from "@/lib/subagent-tasks";
import type { UIMessage } from "@/lib/types";

export function useHasSubagentResults(messages: UIMessage[] = []): boolean {
  const context = useSubagentTasks();
  const anchors = new Map(messages.flatMap((message) => message.subagentAnchor
    ? [[message.subagentAnchor.taskId, message.subagentAnchor.callId] as const] : []));
  return context?.tasks.some((task) => !isActiveSubagentTask(task) && anchors.has(task.task_id)
    && anchors.get(task.task_id) === task.origin_call_id) ?? false;
}
export function SubagentThreadMessages(props: ComponentProps<typeof ThreadMessages>) {
  const context = useSubagentTasks();
  const sessionKey = context?.sessionKey;
  const groups = useMemo(() => groupSubagentAnchors(buildDisplayUnits(props.messages)), [props.messages]);
  const [archive, setArchive] = useState(() => ({ sessionKey, expanded: new Set<string>() }));
  if (archive.sessionKey !== sessionKey) setArchive({ sessionKey, expanded: new Set<string>() });
  return <ThreadMessages {...props} renderSubagentAnchor={(anchor) => {
    const anchors = groups.get(anchor.taskId);
    if (!anchors) return null;
    const expanded = anchors.some((item) => archive.expanded.has(item.taskId));
    return <SubagentAnchor anchors={anchors} expanded={expanded} onToggle={() => {
      props.onActivityToggle?.();
      setArchive((current) => {
        const next = new Set(current.expanded);
        for (const item of anchors) {
          if (expanded) next.delete(item.taskId);
          else next.add(item.taskId);
        }
        return { sessionKey, expanded: next };
      });
    }} />;
  }} />;
}
