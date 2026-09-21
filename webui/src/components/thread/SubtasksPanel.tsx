import { useEffect, useState } from "react";
import { ChevronDown, GitFork, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { NanobotClient } from "@/lib/nanobot-client";
import { Button } from "@/components/ui/button";

export type Subtask = {
  task_id: string; turn_id: string; label: string; revision: number;
  state: "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  iteration: number; elapsed_ms: number; output: string; tools: string[]; truncated: boolean;
};

const states = new Set(["queued", "running", "completed", "failed", "cancelled", "interrupted"]);
export function readSubtasks(value: unknown): Subtask[] {
  if (!value || typeof value !== "object" || !("tasks" in value) || !Array.isArray(value.tasks)) {
    throw new Error("Invalid subtask snapshot");
  }
  return value.tasks.slice(-32).filter((row): row is Subtask => row && typeof row === "object"
    && typeof row.task_id === "string" && typeof row.turn_id === "string" && typeof row.label === "string"
    && states.has(row.state) && Number.isSafeInteger(row.revision) && row.revision >= 0
    && Number.isSafeInteger(row.iteration) && Number.isSafeInteger(row.elapsed_ms)
    && typeof row.output === "string" && Array.isArray(row.tools) && row.tools.every((tool: unknown) => typeof tool === "string"));
}

/** Poll only this mounted/visible parent; never cache private output in browser storage. */
export function SubtasksPanel({ client, chatId }: {
  client: Pick<NanobotClient, "requestMutation">; chatId: string;
}) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Subtask[]>([]);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  useEffect(() => {
    let disposed = false;
    let busy = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (disposed || busy || document.visibilityState === "hidden") return;
      busy = true;
      try {
        const result = await client.requestMutation("subtasks.snapshot", { chat_id: chatId }, 10_000);
        if (!disposed) { setTasks(readSubtasks(result)); setError(false); }
      } catch {
        if (!disposed) setError(true);
      } finally {
        busy = false;
        if (!disposed) timer = setTimeout(() => void poll(), 3000);
      }
    }
    function visibility() { clearTimeout(timer); void poll(); }
    void poll();
    document.addEventListener("visibilitychange", visibility);
    return () => { disposed = true; clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [client, chatId, refresh]);
  if (!tasks.length) return null;
  const active = tasks.filter((task) => task.state === "running" || task.state === "queued").length;
  return <section className="mx-auto mb-2 w-full max-w-[49.5rem] rounded-control border border-border/60 bg-muted/20 text-sm">
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="flex w-full items-center gap-2 rounded-control px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {active && !error ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> : <GitFork className="size-4" aria-hidden />}
      <span className="flex-1">{t("thread.subtasks.title")} <span className="text-muted-foreground">({tasks.length})</span></span>
      <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
    </button>
    <div hidden={!expanded} className="max-h-[min(50vh,26rem)] space-y-2 overflow-y-auto px-3 pb-3">
      <p className="text-xs text-muted-foreground">{t("thread.subtasks.retention")}</p>
      {error ? <div role="status" className="flex flex-wrap items-center gap-2 text-xs">
        {t("thread.subtasks.stale")}<Button variant="ghost" size="sm" onClick={() => setRefresh((n) => n + 1)}>{t("thread.subtasks.retry")}</Button>
      </div> : null}
      {[...tasks].reverse().map((task) => <div key={task.task_id} className="rounded-lg border border-border/60 bg-background/40 p-3">
        <button type="button" aria-expanded={opened.has(task.task_id)} onClick={() => setOpened((previous) => {
          const next = new Set(previous); if (next.has(task.task_id)) next.delete(task.task_id); else next.add(task.task_id); return next;
        })} className="w-full space-y-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <div className="flex items-baseline gap-2"><span className="min-w-0 flex-1 break-words font-medium [overflow-wrap:anywhere]">{task.label || task.task_id}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{t(`thread.subtasks.${error && (task.state === "running" || task.state === "queued") ? "unknown" : task.state}`)}</span></div>
          <div className="text-xs text-muted-foreground">{t("thread.subtasks.round", { count: task.iteration })} · {Math.round(task.elapsed_ms / 1000)}s</div>
        </button>
        <div hidden={!opened.has(task.task_id)}>
        {task.tools.length ? <p className="mt-3 break-words font-mono text-xs text-muted-foreground">{task.tools.join(" → ")}</p> : null}
        <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed [overflow-wrap:anywhere]">{task.output || t("thread.subtasks.noOutput")}</pre>
        {task.truncated ? <p className="mt-2 text-xs text-muted-foreground">{t("thread.subtasks.truncated")}</p> : null}
        </div>
      </div>)}
    </div>
  </section>;
}
