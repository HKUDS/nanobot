import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Circle, Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { SubagentActivityTask } from "@/lib/types";

interface SubagentActivityGroupProps {
  tasks: SubagentActivityTask[];
  onOpenTask?: (taskId: string) => void;
}

function elapsedLabel(value?: number): string {
  if (!Number.isFinite(value) || value == null) return "—";
  const seconds = Math.max(0, Math.round(value / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function SubagentActivityGroup({ tasks, onOpenTask }: SubagentActivityGroupProps) {
  const { t } = useTranslation();
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const running = tasks.filter((task) => task.status === "running").length;
  const statusLabel = running > 0
    ? t("message.subagentsRunning", { count: running, defaultValue: `${running} 个运行中` })
    : t("message.subagentsCompleted", { defaultValue: "已完成" });

  return (
    <section
      className="mt-2 border-t border-border/55 pt-2"
      data-testid="subagent-activity-group"
      aria-label={t("message.subagents", { defaultValue: "Subagents" })}
    >
      <div className="mb-1 flex items-center justify-between gap-3 text-[12px] text-muted-foreground">
        <span className="font-medium">
          {t("message.subagents", { defaultValue: "Subagents" })} · {tasks.length}
        </span>
        <span>{statusLabel}</span>
      </div>
      <div className="flex flex-col gap-0.5">
        {tasks.map((task) => {
          const expanded = expandedTaskId === task.task_id;
          const failed = task.status === "failed";
          const completed = task.status === "completed";
          const latest = task.latest_tool?.name;
          return (
            <div key={task.task_id} className="rounded-md">
              <button
                type="button"
                data-thread-disclosure=""
                className="group flex min-h-7 w-full items-center gap-2 rounded-md px-1.5 text-left text-[12px] text-muted-foreground hover:bg-muted/45 hover:text-foreground"
                aria-expanded={expanded}
                onClick={() => {
                  onOpenTask?.(task.task_id);
                  setExpandedTaskId(expanded ? null : task.task_id);
                }}
              >
                {failed ? (
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
                ) : completed ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-sky-600 dark:text-sky-400" aria-hidden />
                )}
                <span className="min-w-0 flex-1 truncate font-medium">{task.label}</span>
                {task.iteration != null ? <span className="shrink-0 text-muted-foreground/65">第 {task.iteration} 轮</span> : null}
                <span className="flex shrink-0 items-center gap-1 text-muted-foreground/65">
                  <Clock3 className="h-3 w-3" aria-hidden />
                  {elapsedLabel(task.elapsed_ms)}
                </span>
                {expanded ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3" aria-hidden />}
              </button>
              {expanded ? (
                <div className="ml-7 border-l border-border/50 pl-3 py-1 text-[11px] text-muted-foreground/75">
                  <div>
                    {t("message.subagentLatestActivity", { defaultValue: "最近活动" })}：{latest || t("message.subagentNoActivity", { defaultValue: "等待活动" })}
                  </div>
                  {task.recent_tools?.length ? (
                    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
                      {task.recent_tools.map((tool, index) => (
                        <span key={`${tool.name}-${tool.phase}-${index}`} className={cn(tool.phase === "error" && "text-destructive")}>
                          {tool.name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {failed ? <div className="mt-1 text-destructive">{task.error || t("message.subagentFailed", { defaultValue: "执行失败" })}</div> : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
