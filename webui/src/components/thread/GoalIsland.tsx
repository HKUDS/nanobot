import { CircleAlert } from "lucide-react";
import { useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { MarkdownText, preloadMarkdownText } from "@/components/MarkdownText";
import { Button } from "@/components/ui/button";
import { LoadingRing } from "@/components/ui/loading-ring";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useToast } from "@/components/ui/toast";
import { useOverlayEscapeFocus } from "@/hooks/useOverlayEscapeFocus";
import type { GoalStateWsPayload } from "@/lib/types";

import "./goal-island.css";

const NARROW_MEDIA_QUERY = "(max-width: 767px)";

function subscribeNarrowViewport(onStoreChange: () => void) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const mql = window.matchMedia(NARROW_MEDIA_QUERY);
  mql.addEventListener("change", onStoreChange);
  return () => mql.removeEventListener("change", onStoreChange);
}

function getNarrowViewportSnapshot() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(NARROW_MEDIA_QUERY).matches;
}

export function GoalIsland({ goal, cancelDisabled, onCancel }: {
  goal: GoalStateWsPayload;
  cancelDisabled: boolean;
  onCancel: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [animateEnter] = useState(() => (
    typeof document === "undefined" || !document.documentElement.hasAttribute("data-session-transition")
  ));
  const showToast = useToast();
  const [scrollBody, setScrollBody] = useState<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const escapeFocus = useOverlayEscapeFocus();
  const narrow = useSyncExternalStore(subscribeNarrowViewport, getNarrowViewportSnapshot, () => false);
  const syncGeometry = (panel: HTMLDivElement) => {
    const triggerRect = triggerRef.current?.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    if (triggerRect && triggerRect.width > 0) {
      panel.style.setProperty("--goal-trigger-width", `${triggerRect.width}px`);
      panel.style.setProperty("--goal-trigger-height", `${triggerRect.height}px`);
    }
    if (panelRect.width > 0 && panelRect.height > 0) {
      panel.style.setProperty("--goal-to-width", `${panelRect.width}px`);
      panel.style.setProperty("--goal-to-height", `${panelRect.height}px`);
    }
  };
  const setPanelNode = (node: HTMLDivElement | null) => {
    panelRef.current = node;
    if (node) syncGeometry(node);
  };
  const changeOpen = (nextOpen: boolean) => {
    const panel = panelRef.current;
    const surface = panel?.querySelector<HTMLElement>(":scope > .goal-island-surface");
    const content = panel?.querySelector<HTMLElement>(".goal-island-panel-content");
    if (panel && surface && content) {
      syncGeometry(panel);
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
  const collapsedLabel = status === "blocked" ? (recap || t("thread.composer.goalBlocked")) : label;
  const cancelButton = <Button
    type="button"
    variant="ghost"
    size="sm"
    className="goal-island-cancel -mt-0.5 ml-auto h-6 shrink-0 rounded-full px-2.5 text-[11.5px] font-medium leading-none"
    disabled={cancelDisabled || cancelling}
    aria-busy={cancelling}
    title={cancelDisabled ? t("thread.composer.cancelGoalOffline") : undefined}
    onClick={async () => {
      setCancelling(true);
      try {
        await onCancel();
      } catch {
        showToast?.({ message: t("thread.composer.cancelGoalFailed"), tone: "error", dedupeKey: "cancel-goal" });
      } finally {
        setCancelling(false);
      }
    }}
  >{t("thread.composer.cancelGoal")}</Button>;

  useLayoutEffect(() => {
    if (!scrollBody) return;
    if (status === "blocked") scrollBody.scrollTop = 0;
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
  }, [scrollBody, status]);

  return (
    <div className="goal-island-position">
      <Popover open={open} onOpenChange={changeOpen}>
        <div
          className="goal-island"
          data-goal-status={status}
          data-detail-mounted={!!scrollBody}
          data-animate-enter={animateEnter || undefined}
          role="status"
          aria-label={status === "blocked" ? [t("thread.composer.goalBlocked"), recap].filter(Boolean).join(" · ") : t("thread.composer.goalStateStrip", { label })}
        >
          <PopoverTrigger asChild>
            <button
              ref={triggerRef}
              type="button"
              className="goal-island-trigger"
              aria-label={t("thread.composer.goalStateExpandAria")}
              {...escapeFocus.triggerProps}
              onPointerEnter={() => { void preloadMarkdownText(); }}
              onFocus={() => { void preloadMarkdownText(); }}
            >
              <span className="goal-island-surface" aria-hidden />
              {status === "blocked"
                ? <CircleAlert className="goal-island-status-icon" strokeWidth={2.2} aria-hidden="true" />
                : <LoadingRing className="h-3 w-3 shrink-0 text-muted-foreground" />}
              {collapsedLabel ? <span className={status === "blocked" ? "goal-island-label goal-island-reason min-w-0 truncate" : "goal-island-label min-w-0 truncate"}>{collapsedLabel}</span> : null}
            </button>
          </PopoverTrigger>
        </div>
        <PopoverContent
          ref={setPanelNode}
          {...escapeFocus.contentProps}
          className="goal-island-panel max-h-[min(25dvh,16rem,var(--radix-popover-content-available-height))] overflow-visible rounded-[20px] bg-transparent p-0 shadow-none dark:shadow-none"
          motionClassName=""
          data-goal-status={status}
          data-narrow={narrow || undefined}
          side="bottom"
          sideOffset={narrow ? 10 : -32}
          collisionPadding={{ top: 8, bottom: 12, left: 24, right: 24 }}
          aria-label={t("thread.composer.goalStateSheetTitle")}
        >
          <div className="goal-island-surface" aria-hidden />
          <div className="goal-island-panel-content">
            <div className="goal-island-summary">
              <div className="markdown-content min-w-0 flex-1">
                <h2>{summary || (status === "blocked" ? t("thread.composer.goalBlocked") : t("thread.composer.goalStateSheetTitle"))}</h2>
              </div>
              {cancelButton}
            </div>
            <div ref={setScrollBody} className="goal-island-body">
              <div className="goal-island-document">
                {status === "blocked" ? (
                  <div className="goal-island-blocked">
                    <CircleAlert className="goal-island-status-icon" strokeWidth={2.2} aria-hidden="true" />
                    <span className="sr-only">{t("thread.composer.goalBlocked")}</span>
                    {recap ? <MarkdownText className="goal-island-reason flex-1">{recap}</MarkdownText> : null}
                  </div>
                ) : null}
                {objective ? <MarkdownText className={status === "blocked" ? "mt-2.5" : undefined}>{objective}</MarkdownText> : null}
                {status !== "blocked" && recap ? (
                  <MarkdownText className="goal-island-recap mt-2.5">{recap}</MarkdownText>
                ) : null}
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
