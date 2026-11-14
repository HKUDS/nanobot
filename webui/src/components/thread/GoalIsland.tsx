import { CircleAlert } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useOverlayEscapeFocus } from "@/hooks/useOverlayEscapeFocus";
import type { GoalStateWsPayload } from "@/lib/types";

import "./goal-island.css";

export function GoalIsland({ goal, cancelDisabled, onCancel }: {
  goal: GoalStateWsPayload;
  cancelDisabled: boolean;
  onCancel: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelFailed, setCancelFailed] = useState(false);
  const [scrollBody, setScrollBody] = useState<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const escapeFocus = useOverlayEscapeFocus();
  const changeOpen = (nextOpen: boolean) => {
    const panel = panelRef.current;
    const surface = panel?.querySelector<HTMLElement>(":scope > .goal-island-surface");
    const content = panel?.querySelector<HTMLElement>(".goal-island-panel-content");
    if (panel && surface && content) {
      const shape = getComputedStyle(surface);
      const text = getComputedStyle(content);
      panel.style.setProperty("--goal-from-width", shape.width);
      panel.style.setProperty("--goal-from-height", shape.height);
      panel.style.setProperty("--goal-from-radius", shape.getPropertyValue("--goal-island-radius"));
      panel.style.setProperty("--goal-from-opacity", text.opacity);
      panel.style.setProperty("--goal-from-transform", text.transform);
    }
    setOpen(nextOpen);
  };
  const summary = goal.ui_summary?.trim() ?? "";
  const objective = goal.objective?.trim() ?? "";
  const label = summary || objective || t("thread.composer.goalStateFallback");
  const status = goal.status === "blocked" ? "blocked" : "active";
  const recap = goal.recap?.trim() ?? "";
  const collapsedLabel = status === "blocked" ? recap : label;
  const cancelButton = <Button
    type="button"
    variant="ghost"
    size="sm"
    className="ml-auto h-7 shrink-0 px-2 text-caption text-muted-foreground"
    disabled={cancelDisabled || cancelling}
    aria-busy={cancelling}
    title={cancelDisabled ? t("thread.composer.cancelGoalOffline") : undefined}
    onClick={async () => {
      setCancelling(true);
      setCancelFailed(false);
      try {
        await onCancel();
      } catch {
        setCancelFailed(true);
      } finally {
        setCancelling(false);
      }
    }}
  >{t("thread.composer.cancelGoal")}</Button>;

  useLayoutEffect(() => {
    if (!scrollBody) return;
    if (status === "blocked" || cancelFailed) scrollBody.scrollTop = 0;
    const measure = () => {
      scrollBody.toggleAttribute("data-overflow-top", scrollBody.scrollTop > 1);
      scrollBody.toggleAttribute("data-overflow-bottom", scrollBody.scrollHeight - scrollBody.clientHeight - scrollBody.scrollTop > 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(scrollBody);
    if (scrollBody.firstElementChild) observer.observe(scrollBody.firstElementChild);
    scrollBody.addEventListener("scroll", measure, { passive: true });
    return () => {
      observer.disconnect();
      scrollBody.removeEventListener("scroll", measure);
    };
  }, [scrollBody, status, cancelFailed]);

  return (
    <div className="goal-island-position">
      <Popover open={open} onOpenChange={changeOpen}>
        <div className="goal-island" data-goal-status={status} data-detail-mounted={!!scrollBody} role="status" aria-label={status === "blocked" ? [t("thread.composer.goalBlocked"), recap].filter(Boolean).join(" · ") : t("thread.composer.goalStateStrip", { label })}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="goal-island-trigger"
              aria-label={t("thread.composer.goalStateExpandAria")}
              {...escapeFocus.triggerProps}
              onPointerEnter={() => { void preloadMarkdownText(); }}
              onFocus={() => { void preloadMarkdownText(); }}
            >
              <span className="goal-island-surface" aria-hidden />
              {status === "blocked" ? <CircleAlert className="goal-island-status-icon" strokeWidth={2.5} aria-hidden="true" /> : null}
              {collapsedLabel ? <span className={status === "blocked" ? "goal-island-reason min-w-0 truncate" : "min-w-0 truncate"}>{collapsedLabel}</span> : null}
            </button>
          </PopoverTrigger>
        </div>
        <PopoverContent
          ref={panelRef}
          {...escapeFocus.contentProps}
          className="goal-island-panel max-h-[min(25dvh,var(--radix-popover-content-available-height))] overflow-visible rounded-t-none rounded-b-[28px] bg-transparent p-0 shadow-none dark:shadow-none"
          motionClassName=""
          data-goal-status={status}
          side="bottom"
          sideOffset={-40}
          collisionPadding={{ top: 0, bottom: 12, left: 32, right: 32 }}
          aria-label={t("thread.composer.goalStateSheetTitle")}
        >
          <div className="goal-island-surface" aria-hidden />
          <div className="goal-island-panel-content">
            {status !== "blocked" ? <div className="goal-island-summary flex items-start gap-3">
              {summary ? <div className="markdown-content min-w-0 flex-1"><h2>{summary}</h2></div> : null}
              {cancelButton}
            </div> : null}
            <div ref={setScrollBody} className="goal-island-body">
              <div className="goal-island-document">
                {cancelFailed ? <p role="alert" className="mb-2 text-caption text-destructive">{t("thread.composer.cancelGoalFailed")}</p> : null}
                {status === "blocked" ? <div className="goal-island-blocked">
                  <CircleAlert className="goal-island-status-icon" strokeWidth={2.5} aria-hidden="true" />
                  <span className="sr-only">{t("thread.composer.goalBlocked")}</span>
                  {recap ? <MarkdownText className="goal-island-reason flex-1">{recap}</MarkdownText> : null}
                  {cancelButton}
                </div> : null}
                {objective ? <MarkdownText className={status === "blocked" ? "mt-4" : undefined}>{objective}</MarkdownText> : null}
                {status !== "blocked" && recap ? <MarkdownText className="mt-4 text-muted-foreground">{recap}</MarkdownText> : null}
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
