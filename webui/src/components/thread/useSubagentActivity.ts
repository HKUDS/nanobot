import { useEffect, useState } from "react";
import { isActiveSubagentTask, type ObservedSubagentTask } from "@/lib/subagent-tasks";

export const SUBAGENT_COMPLETION_FEEDBACK_MS = 4000;

interface ActivityView {
  observed: ObservedSubagentTask[];
  inputKey: string | null;
  cycleIds: string[];
  retainedIds: string[];
  open: boolean;
}

export function useSubagentActivity(tasks: ObservedSubagentTask[], inputKey: string | null, interacting: boolean) {
  const [view, setView] = useState<ActivityView>(() => ({
    observed: tasks, inputKey, cycleIds: tasks.filter(isActiveSubagentTask).map(task => task.task_id), retainedIds: [], open: false,
  }));
  const activeTasks = tasks.filter(isActiveSubagentTask);
  const activeIds = activeTasks.map(task => task.task_id);
  if (view.observed !== tasks || view.inputKey !== inputKey) {
    const startsWork = activeIds.length > 0 && !view.observed.some(isActiveSubagentTask);
    setView({
      ...view, observed: tasks, inputKey,
      cycleIds: startsWork || view.inputKey !== inputKey ? activeIds : [...new Set([...view.cycleIds, ...activeIds])],
      retainedIds: view.open ? [...new Set([...view.retainedIds, ...activeIds])] : [],
    });
  }
  const receiptKey = view.cycleIds.join("\0");
  const hasActive = activeIds.length > 0;
  useEffect(() => {
    if (hasActive || view.open || interacting || !receiptKey) return;
    const timer = window.setTimeout(() => setView(current => current.open || current.observed.some(isActiveSubagentTask)
      ? current : { ...current, cycleIds: [] }), SUBAGENT_COMPLETION_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [hasActive, view.open, interacting, receiptKey]);

  const visibleIds = view.open ? view.retainedIds : hasActive ? activeIds : view.cycleIds;
  const byId = new Map(tasks.map(task => [task.task_id, task]));
  return {
    open: view.open,
    tasks: visibleIds.map(id => byId.get(id)!),
    setOpen: (open: boolean, { preserveFeedback = false }: { preserveFeedback?: boolean } = {}) => setView(current => {
      const currentActive = current.observed.filter(isActiveSubagentTask).map(task => task.task_id);
      return {
        ...current, open,
        // Cancelling a partial drag is not a dismissal of the completion receipt.
        cycleIds: open || preserveFeedback ? current.cycleIds : currentActive,
        retainedIds: open ? currentActive.length ? currentActive : current.cycleIds : [],
      };
    }),
  };
}
