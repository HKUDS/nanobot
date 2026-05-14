import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

import { MarkdownText } from "@/components/MarkdownText";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { LongTaskAgentUIData, UIMessage } from "@/lib/types";

import {
  displayStep1Based,
  EVENT_I18N_KEY,
  snapshotMarkdownBody,
  stepChipLabel,
  totalSteps,
} from "./long-task-ui-helpers";

function fileList(paths: string[] | undefined, label: string) {
  if (!paths?.length) return null;
  return (
    <div className="mt-2">
      <p className="text-[11px] font-medium text-muted-foreground/80">{label}</p>
      <ul className="mt-1 space-y-0.5">
        {paths.map((p) => (
          <li key={p} className="truncate font-mono text-[12px] text-foreground/90" title={p}>
            {p}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface LongTaskDetailSheetProps {
  message: UIMessage | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function LongTaskDetailSheet({ message, open, onOpenChange }: LongTaskDetailSheetProps) {
  const { t } = useTranslation();
  const data = message?.longTask;
  const timeline: LongTaskAgentUIData[] =
    message?.longTaskTimeline?.length ? message.longTaskTimeline : data ? [data] : [];
  const effectiveOpen = open && !!data;

  if (!data) return null;

  const goal = (data.goal ?? "").trim();

  return (
    <Sheet open={effectiveOpen} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className={cn(
          "flex h-full w-full max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-xl",
        )}
        showCloseButton={false}
      >
        <SheetHeader className="space-y-1 border-b border-border/50 px-5 py-4 text-left">
          <div className="flex items-start justify-between gap-3">
            <SheetTitle className="pr-8 text-base font-semibold leading-tight">
              {t("message.longTaskTitle")}
            </SheetTitle>
            <SheetClose
              className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none"
              aria-label={t("message.longTaskCloseDetails")}
            >
              <X className="h-4 w-4" />
            </SheetClose>
          </div>
          {data.ui_summary ? (
            <p className="text-[13px] text-muted-foreground">{data.ui_summary}</p>
          ) : null}
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 scrollbar-thin scrollbar-track-transparent">
          {goal ? (
            <section className="mb-6">
              <h3 className="text-[11px] font-medium text-muted-foreground/85">
                {t("message.longTaskFullGoal")}
              </h3>
              <MarkdownText className="prose prose-sm dark:prose-invert mt-2 max-w-none">
                {goal}
              </MarkdownText>
            </section>
          ) : null}

          <h3 className="text-[11px] font-medium text-muted-foreground/85">
            {t("message.longTaskActivityLog")}
          </h3>
          <div className="mt-3 flex flex-col gap-4">
            {timeline.map((snap, i) => {
              const body = snapshotMarkdownBody(snap);
              const evKey = EVENT_I18N_KEY[snap.event] ?? "message.longTaskEvFallback";
              const tot = totalSteps(snap);
              const n = displayStep1Based(snap);
              return (
                <article
                  key={`${snap.run_id}-${snap.event}-${i}`}
                  className="rounded-lg border border-border/50 bg-muted/20 px-3 py-3"
                >
                  <header className="flex flex-wrap items-center gap-2 text-[12px]">
                    <span className="rounded-md bg-background px-2 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                      {stepChipLabel(snap, n, tot, t)}
                    </span>
                    <span className="font-medium text-foreground/90">{t(evKey, { event: snap.event })}</span>
                    {snap.tools_used?.length ? (
                      <span className="text-muted-foreground">
                        {snap.tools_used.slice(0, 6).join(", ")}
                        {snap.tools_used.length > 6 ? "…" : ""}
                      </span>
                    ) : null}
                    {snap.stop_reason ? (
                      <span className="text-muted-foreground">· {snap.stop_reason}</span>
                    ) : null}
                  </header>
                  {body ? (
                    <MarkdownText className="prose prose-sm dark:prose-invert mt-3 max-w-none">
                      {body}
                    </MarkdownText>
                  ) : null}
                  {fileList(snap.files_created_union, t("message.longTaskCreated"))}
                  {fileList(snap.files_modified_union, t("message.longTaskModified"))}
                </article>
              );
            })}
          </div>

          {data.cumulative_usage && typeof data.cumulative_usage.total_tokens === "number" ? (
            <p className="mt-6 text-[11px] tabular-nums text-muted-foreground">
              {t("message.longTaskTokens", {
                total: data.cumulative_usage.total_tokens,
                prompt: data.cumulative_usage.prompt_tokens ?? 0,
                completion: data.cumulative_usage.completion_tokens ?? 0,
              })}
            </p>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
