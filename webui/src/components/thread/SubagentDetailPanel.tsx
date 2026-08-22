import { useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Loader2, Terminal, X, XCircle } from "lucide-react";

import { MarkdownText } from "@/components/MarkdownText";
import { cn } from "@/lib/utils";
import type { SubagentDetailSnapshot } from "@/lib/types";

interface SubagentDetailPanelProps {
  details: SubagentDetailSnapshot[];
  selectedTaskId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (taskId: string) => void;
  onClose: (taskId: string) => void;
}

function statusIcon(status: string | undefined) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "failed" || status === "cancelled") return <XCircle className="h-4 w-4 text-red-600" />;
  return <Loader2 className="h-4 w-4 animate-spin text-sky-600" />;
}

export function SubagentDetailPanel({
  details,
  selectedTaskId,
  open,
  onOpenChange,
  onSelect,
  onClose,
}: SubagentDetailPanelProps) {
  const [expandedExecution, setExpandedExecution] = useState<Record<string, boolean>>({});
  const selected = useMemo(
    () => details.find((item) => item.task_id === selectedTaskId) ?? details[0],
    [details, selectedTaskId],
  );
  const executionExpanded = selected
    ? expandedExecution[selected.task_id] ?? selected.status !== "completed"
    : false;

  if (!open) return null;

  return (
    <aside
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background"
      id="subagent-detail-panel"
      data-testid="subagent-detail-panel"
      aria-label="Subagent 运行详情"
    >
      <div className="flex shrink-0 items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">Subagent 运行详情</h2>
          <p className="mt-1 text-xs text-muted-foreground">展示输入、阶段、工具调用摘要、流式输出和最终结果。</p>
        </div>
        <button
          type="button"
          aria-label="关闭 Subagent 详情"
          title="关闭 Subagent 详情"
          onClick={() => onOpenChange(false)}
          className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {details.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 text-sm text-muted-foreground">
            当前会话还没有 Subagent 详情。
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2">
              {details.map((item) => (
                <div
                  key={item.task_id}
                  className={cn(
                    "flex min-w-36 items-center gap-1 rounded-md text-left text-xs",
                    selected?.task_id === item.task_id
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(item.task_id)}
                    className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left"
                  >
                    {statusIcon(item.status)}
                    <span className="truncate">{item.label}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`关闭 ${item.label}`}
                    title={`关闭 ${item.label}`}
                    onClick={() => onClose(item.task_id)}
                    className="mr-1 rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </div>
              ))}
            </div>
            {selected ? (
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm">
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">输入</h3>
                  <div className="rounded-lg bg-muted/50 p-3 whitespace-pre-wrap break-words">{selected.input || "（暂无）"}</div>
                </section>
                <section className="overflow-hidden rounded-lg border border-border/70">
                  <button
                    type="button"
                    data-thread-disclosure=""
                    aria-expanded={executionExpanded}
                    onClick={() => setExpandedExecution((current) => ({
                      ...current,
                      [selected.task_id]: !executionExpanded,
                    }))}
                    className="flex min-h-9 w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:bg-muted/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Terminal className="h-3.5 w-3.5" aria-hidden />
                    <span className="min-w-0 flex-1">执行过程</span>
                    {executionExpanded
                      ? <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                      : <ChevronRight className="h-3.5 w-3.5" aria-hidden />}
                  </button>
                  {executionExpanded ? (
                    <div className="space-y-2 border-t border-border/60 bg-muted/15 p-3">
                      {(selected.steps ?? []).map((step, index) => (
                        <div key={`${String(step.kind)}-${index}`} className="rounded-md border border-border/70 bg-background px-3 py-2 text-xs">
                          <span className="font-medium">{String(step.kind ?? "phase")}</span>
                          {typeof step.name === "string" ? <span className="ml-2 text-muted-foreground">{step.name}</span> : null}
                          {typeof step.iteration === "number" ? <span className="ml-2 text-muted-foreground">第 {step.iteration} 轮</span> : null}
                        </div>
                      ))}
                      {(selected.steps ?? []).length === 0 ? <div className="text-muted-foreground">（暂无执行步骤）</div> : null}
                    </div>
                  ) : null}
                </section>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">流式输出 / 最终结果</h3>
                  <MarkdownText streaming={selected.status !== "completed" && selected.status !== "failed"} className="max-w-none text-sm leading-relaxed">
                    {selected.output || "（暂无输出）"}
                  </MarkdownText>
                </section>
                {selected.error ? (
                  <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
                    <CircleAlert className="h-4 w-4 shrink-0" />{selected.error}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
}
