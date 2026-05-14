import { useState } from "react";
import { Check, ChevronRight, Circle, ListTree, PanelRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MarkdownText } from "@/components/MarkdownText";
import { StreamingLabelSheen } from "@/components/MessageBubble";
import { cn } from "@/lib/utils";
import type { LongTaskAgentUIData, UIMessage } from "@/lib/types";

import { LongTaskDetailSheet } from "@/components/thread/LongTaskDetailSheet";
import {
  collapsedSummaryLine,
  displayStep1Based,
  EVENT_I18N_KEY,
  snapshotMarkdownBody,
  stepChipLabel,
  totalSteps,
} from "./long-task-ui-helpers";

interface LongTaskActivityCardProps {
  message: UIMessage;
  animClass: string;
}

function isFinished(data: LongTaskAgentUIData): boolean {
  return (
    data.event === "task_complete"
    || data.event === "task_error"
    || data.status === "completed"
    || data.status === "error"
  );
}

function isRunning(data: LongTaskAgentUIData): boolean {
  return !isFinished(data) && data.status !== "idle";
}

export function LongTaskActivityCard({ message, animClass }: LongTaskActivityCardProps) {
  const { t } = useTranslation();
  const data = message.longTask;
  if (!data) return null;

  const [mediumOpen, setMediumOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const finished = isFinished(data);
  const busy = isRunning(data);
  const timeline: LongTaskAgentUIData[] =
    message.longTaskTimeline?.length ? message.longTaskTimeline : [data];

  const lineSummary = collapsedSummaryLine(data, message.content, t);

  return (
    <div className={cn("w-full", animClass)}>
      <div
        className={cn(
          "flex items-center gap-2 rounded-[var(--radius)] border border-border/50 bg-muted/25 px-3 py-2",
          "shadow-[0_1px_0_hsl(var(--border)/0.45)]",
        )}
      >
        <span className="shrink-0" aria-hidden>
          {finished && data.event === "task_complete" ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary">
              <Check className="h-3.5 w-3.5 stroke-[2.5]" />
            </span>
          ) : finished ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <Circle className="h-2 w-2 fill-current" aria-hidden />
            </span>
          ) : (
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted">
              <ListTree className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
            </span>
          )}
        </span>

        <button
          type="button"
          onClick={() => setMediumOpen((v) => !v)}
          className="min-w-0 flex-1 text-left"
          aria-expanded={mediumOpen}
        >
          <span className="flex items-center gap-1.5">
            <StreamingLabelSheen active={busy} className="shrink-0 text-[13px] font-medium text-foreground">
              {t("message.longTaskTitle")}
            </StreamingLabelSheen>
            <span className="truncate text-[13px] text-muted-foreground">
              · {lineSummary}
            </span>
          </span>
          {busy ? (
            <div className="mt-2 h-0.5 w-full overflow-hidden rounded-full bg-border/50">
              <div className="h-full w-2/5 rounded-full bg-primary/35 motion-safe:animate-pulse" aria-hidden />
            </div>
          ) : null}
        </button>

        <button
          type="button"
          className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground"
          aria-label={t("message.longTaskOpenDetails")}
          onClick={(e) => {
            e.stopPropagation();
            setSheetOpen(true);
          }}
        >
          <PanelRight className="h-4 w-4" aria-hidden />
        </button>

        <button
          type="button"
          className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-muted/60"
          aria-label={mediumOpen ? t("message.longTaskCollapsePeek") : t("message.longTaskExpandPeek")}
          onClick={(e) => {
            e.stopPropagation();
            setMediumOpen((v) => !v);
          }}
        >
          <ChevronRight
            className={cn("h-4 w-4 transition-transform duration-200", mediumOpen && "rotate-90")}
            aria-hidden
          />
        </button>
      </div>

      {mediumOpen ? (
        <div
          className={cn(
            "mt-2 max-h-64 overflow-y-auto rounded-[var(--radius)] border border-border/45",
            "bg-background/50 px-3 py-2 scrollbar-thin scrollbar-track-transparent",
          )}
        >
          <div className="flex flex-col gap-3">
            {timeline.map((snap, i) => {
              const body = snapshotMarkdownBody(snap);
              const evKey = EVENT_I18N_KEY[snap.event] ?? "message.longTaskEvFallback";
              const st = totalSteps(snap);
              const n = displayStep1Based(snap);
              return (
                <div
                  key={`${snap.run_id}-${snap.event}-${i}`}
                  className="rounded-md border border-border/35 bg-muted/15 px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] tabular-nums">
                      {stepChipLabel(snap, n, st, t)}
                    </span>
                    <span className="font-medium text-foreground/88">{t(evKey, { event: snap.event })}</span>
                  </div>
                  {body ? (
                    <MarkdownText className="prose prose-sm dark:prose-invert mt-2 max-w-none text-[13px]">
                      {body}
                    </MarkdownText>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <LongTaskDetailSheet message={message} open={sheetOpen} onOpenChange={setSheetOpen} />
    </div>
  );
}
