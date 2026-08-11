import {
  Columns2,
  Grid2X2,
  PanelLeft,
  PanelsTopLeft,
  Plus,
  Rows2,
  type LucideIcon,
} from "lucide-react";
import {
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { WorkbenchLayout } from "@/components/workbench/workbench-model";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";

export interface WorkbenchPane {
  key: string;
  reactKey?: string;
  title: string;
}

interface PaneRenderContext {
  active: boolean;
  headerPortalTarget: HTMLElement | null | undefined;
  composerPortalTarget: HTMLElement | null | undefined;
  headerActions: ReactNode;
}

interface PaneWorkbenchProps {
  panes: WorkbenchPane[];
  activePaneKey: string;
  layout: WorkbenchLayout;
  chrome?: boolean;
  showLayoutControl: boolean;
  addPaneDisabled?: boolean;
  onActivatePane: (key: string) => void;
  onAddPane: () => void;
  onLayoutChange: (layout: WorkbenchLayout) => void;
  onPaneOrderChange: (paneKeys: string[]) => void;
  renderPane: (pane: WorkbenchPane, context: PaneRenderContext) => ReactNode;
}

const LAYOUT_MOTION_DURATION_MS = 260;
const LAYOUT_MOTION_EASING = "cubic-bezier(0.2, 0, 0, 1)";

const LAYOUT_CONTROLS: Array<{
  icon: LucideIcon;
  layout: WorkbenchLayout;
  label: string;
}> = [
  { icon: Columns2, layout: "columns", label: "Columns" },
  { icon: Rows2, layout: "rows", label: "Rows" },
  { icon: Grid2X2, layout: "grid", label: "Grid" },
  { icon: PanelsTopLeft, layout: "bsp", label: "BSP" },
  { icon: PanelLeft, layout: "main-stack", label: "Main and stack" },
];

type EffectiveWorkbenchLayout = WorkbenchLayout | "compact";

function paneGridStyle(layout: EffectiveWorkbenchLayout, paneCount: number): CSSProperties {
  const count = Math.max(1, paneCount);
  switch (layout) {
    case "columns":
      return {
        gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))`,
        gridTemplateRows: "minmax(0, 1fr)",
      };
    case "rows":
      return {
        gridTemplateColumns: "minmax(0, 1fr)",
        gridTemplateRows: `repeat(${count}, minmax(0, 1fr))`,
      };
    case "grid": {
      const columns = Math.ceil(Math.sqrt(count));
      const rows = Math.ceil(count / columns);
      return {
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
      };
    }
    case "bsp":
      return {
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gridTemplateRows: "repeat(4, minmax(0, 1fr))",
      };
    case "main-stack":
      return count === 1
        ? {
            gridTemplateColumns: "minmax(0, 1fr)",
            gridTemplateRows: "minmax(0, 1fr)",
          }
        : {
            gridTemplateColumns: "minmax(0, 1.65fr) minmax(0, 1fr)",
            gridTemplateRows: `repeat(${count - 1}, minmax(0, 1fr))`,
          };
    case "compact":
      return {
        gridTemplateColumns: "minmax(0, 1fr)",
        gridTemplateRows: "minmax(0, 1fr)",
      };
  }
}

interface BspCell {
  columnStart: number;
  columnEnd: number;
  rowStart: number;
  rowEnd: number;
}

function bspPaneCells(paneCount: number): BspCell[] {
  const cells: BspCell[] = [{
    columnStart: 1,
    columnEnd: 5,
    rowStart: 1,
    rowEnd: 5,
  }];
  for (let paneIndex = 1; paneIndex < paneCount; paneIndex += 1) {
    const leaf = cells.pop();
    if (!leaf) break;
    if (paneIndex % 2 === 1) {
      const midpoint = (leaf.columnStart + leaf.columnEnd) / 2;
      cells.push(
        { ...leaf, columnEnd: midpoint },
        { ...leaf, columnStart: midpoint },
      );
    } else {
      const midpoint = (leaf.rowStart + leaf.rowEnd) / 2;
      cells.push(
        { ...leaf, rowEnd: midpoint },
        { ...leaf, rowStart: midpoint },
      );
    }
  }
  return cells;
}

function paneCellStyle(
  layout: EffectiveWorkbenchLayout,
  paneCount: number,
  index: number,
): CSSProperties | undefined {
  if (layout === "bsp") {
    const cell = bspPaneCells(paneCount)[index];
    return cell
      ? {
          gridColumn: `${cell.columnStart} / ${cell.columnEnd}`,
          gridRow: `${cell.rowStart} / ${cell.rowEnd}`,
        }
      : undefined;
  }
  if (layout === "main-stack" && paneCount >= 2) {
    return index === 0
      ? { gridColumn: 1, gridRow: `1 / span ${paneCount - 1}` }
      : { gridColumn: 2, gridRow: index };
  }
  return undefined;
}

function isPaneAction(target: EventTarget | null): boolean {
  return target instanceof Element
    && target.closest("[data-workbench-pane-action]") !== null;
}

function movePaneToSlot(
  paneKeys: readonly string[],
  paneKey: string,
  targetKey: string,
): string[] {
  const fromIndex = paneKeys.indexOf(paneKey);
  const targetIndex = paneKeys.indexOf(targetKey);
  if (fromIndex < 0 || targetIndex < 0 || fromIndex === targetIndex) return [...paneKeys];
  const next = paneKeys.filter((key) => key !== paneKey);
  next.splice(targetIndex, 0, paneKey);
  return next;
}

function paneSlotAtPoint(
  rects: readonly DOMRect[],
  x: number,
  y: number,
): number | null {
  for (const [index, rect] of rects.entries()) {
    if (
      x >= rect.left
      && x <= rect.right
      && y >= rect.top
      && y <= rect.bottom
    ) return index;
  }
  return null;
}

function paneInDirection(
  rects: ReadonlyMap<string, DOMRect>,
  paneKey: string,
  direction: "left" | "right" | "up" | "down",
): string | null {
  const source = rects.get(paneKey);
  if (!source) return null;
  const sourceX = source.left + source.width / 2;
  const sourceY = source.top + source.height / 2;
  let best: { key: string; score: number } | null = null;
  for (const [key, rect] of rects) {
    if (key === paneKey) continue;
    const deltaX = rect.left + rect.width / 2 - sourceX;
    const deltaY = rect.top + rect.height / 2 - sourceY;
    const primary = direction === "left"
      ? -deltaX
      : direction === "right"
        ? deltaX
        : direction === "up"
          ? -deltaY
          : deltaY;
    if (primary <= 1) continue;
    const cross = direction === "left" || direction === "right"
      ? Math.abs(deltaY)
      : Math.abs(deltaX);
    const score = primary + cross * 0.35;
    if (!best || score < best.score) best = { key, score };
  }
  return best?.key ?? null;
}

function HeaderIconButton({
  disabled,
  icon: Icon,
  label,
  onClick,
}: {
  disabled?: boolean;
  icon: LucideIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          aria-label={label}
          onClick={onClick}
          className="host-no-drag h-8 w-8 shrink-0 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
        >
          <Icon className="h-4 w-4" aria-hidden />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

export function PaneWorkbench({
  panes,
  activePaneKey,
  layout,
  chrome = true,
  showLayoutControl,
  addPaneDisabled = false,
  onActivatePane,
  onAddPane,
  onLayoutChange,
  onPaneOrderChange,
  renderPane,
}: PaneWorkbenchProps) {
  const { t } = useTranslation();
  const compact = useMediaQuery("(max-width: 767px)");
  const effectiveLayout: EffectiveWorkbenchLayout = compact ? "compact" : layout;
  const [headerPortalTarget, setHeaderPortalTarget] = useState<HTMLElement | null>(null);
  const [composerPortalTarget, setComposerPortalTarget] = useState<HTMLElement | null>(null);
  const paneRefs = useRef(new Map<string, HTMLElement>());
  const lastRectsRef = useRef(new Map<string, DOMRect>());
  const pendingRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const animationsRef = useRef(new Map<string, Animation>());
  const sourcePaneOrder = useMemo(
    () => panes.map((pane) => pane.key),
    [panes],
  );
  const sourcePaneOrderKey = sourcePaneOrder.join("\u0000");
  const [previewPaneKeys, setPreviewPaneKeys] = useState(sourcePaneOrder);
  const previewPaneKeysRef = useRef(sourcePaneOrder);
  const dragGestureRef = useRef<{
    pointerId: number;
    paneKey: string;
    startX: number;
    startY: number;
    slotRects: DOMRect[];
    started: boolean;
  } | null>(null);
  const [draggingPaneKey, setDraggingPaneKey] = useState<string | null>(null);
  const displayedPanes = useMemo(() => {
    const byKey = new Map(panes.map((pane) => [pane.key, pane]));
    return [
      ...previewPaneKeys.map((key) => byKey.get(key)).filter(
        (pane): pane is WorkbenchPane => pane !== undefined,
      ),
      ...panes.filter((pane) => !previewPaneKeys.includes(pane.key)),
    ];
  }, [panes, previewPaneKeys]);
  const paneOrder = displayedPanes.map((pane) => pane.key).join("\u0000");

  useEffect(() => {
    if (dragGestureRef.current) return;
    previewPaneKeysRef.current = sourcePaneOrder;
    setPreviewPaneKeys(sourcePaneOrder);
  }, [sourcePaneOrder, sourcePaneOrderKey]);

  const measurePanes = useCallback(() => {
    const rects = new Map<string, DOMRect>();
    for (const [key, element] of paneRefs.current) {
      if (!element.hidden) rects.set(key, element.getBoundingClientRect());
    }
    return rects;
  }, []);

  const captureLayout = useCallback(() => {
    pendingRectsRef.current = measurePanes();
    for (const animation of animationsRef.current.values()) animation.cancel();
    animationsRef.current.clear();
  }, [measurePanes]);

  useLayoutEffect(() => {
    const previousRects = pendingRectsRef.current ?? lastRectsRef.current;
    pendingRectsRef.current = null;
    const nextRects = measurePanes();
    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (!reduceMotion) {
      for (const [key, nextRect] of nextRects) {
        const previousRect = previousRects.get(key);
        const element = paneRefs.current.get(key);
        if (!element) continue;
        if (!previousRect) {
          if (previousRects.size === 0 || typeof element.animate !== "function") continue;
          const animation = element.animate(
            [
              { opacity: 0, transform: "translateY(5px) scale(0.995)" },
              { opacity: 1, transform: "translateY(0) scale(1)" },
            ],
            {
              duration: 180,
              easing: LAYOUT_MOTION_EASING,
              fill: "backwards",
            },
          );
          animationsRef.current.set(key, animation);
          animation.addEventListener("finish", () => {
            if (animationsRef.current.get(key) === animation) {
              animationsRef.current.delete(key);
            }
          }, { once: true });
          continue;
        }
        if (previousRect.width === 0 || previousRect.height === 0) continue;
        const deltaX = previousRect.left - nextRect.left;
        const deltaY = previousRect.top - nextRect.top;
        const scaleX = previousRect.width / nextRect.width;
        const scaleY = previousRect.height / nextRect.height;
        if (
          Math.abs(deltaX) < 0.5
          && Math.abs(deltaY) < 0.5
          && Math.abs(scaleX - 1) < 0.002
          && Math.abs(scaleY - 1) < 0.002
        ) {
          continue;
        }
        if (typeof element.animate !== "function") continue;
        const animation = element.animate(
          [
            { transform: `translate(${deltaX}px, ${deltaY}px) scale(${scaleX}, ${scaleY})` },
            { transform: "translate(0, 0) scale(1, 1)" },
          ],
          {
            duration: LAYOUT_MOTION_DURATION_MS,
            easing: LAYOUT_MOTION_EASING,
          },
        );
        animationsRef.current.set(key, animation);
        animation.addEventListener("finish", () => {
          if (animationsRef.current.get(key) === animation) {
            animationsRef.current.delete(key);
          }
        }, { once: true });
      }
    }
    lastRectsRef.current = nextRects;
  }, [activePaneKey, effectiveLayout, measurePanes, paneOrder]);

  useEffect(() => () => {
    for (const animation of animationsRef.current.values()) animation.cancel();
  }, []);

  const activatePane = useCallback((key: string, target: EventTarget | null) => {
    if (key === activePaneKey || isPaneAction(target)) return;
    captureLayout();
    onActivatePane(key);
  }, [activePaneKey, captureLayout, onActivatePane]);

  const handlePanePointerDown = useCallback((
    key: string,
    event: ReactPointerEvent<HTMLElement>,
  ) => {
    activatePane(key, event.target);
  }, [activatePane]);

  const handlePaneFocus = useCallback((key: string, event: FocusEvent<HTMLElement>) => {
    activatePane(key, event.target);
  }, [activatePane]);

  const applyPaneOrder = useCallback((paneKey: string, targetKey: string) => {
    const next = movePaneToSlot(previewPaneKeysRef.current, paneKey, targetKey);
    if (next.every((key, index) => previewPaneKeysRef.current[index] === key)) return;
    captureLayout();
    previewPaneKeysRef.current = next;
    setPreviewPaneKeys(next);
    onPaneOrderChange(next);
  }, [captureLayout, onPaneOrderChange]);

  const handleMovePointerDown = useCallback((
    paneKey: string,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) => {
    if (event.button !== 0 || compact || panes.length < 2) return;
    const paneRects = measurePanes();
    dragGestureRef.current = {
      pointerId: event.pointerId,
      paneKey,
      startX: event.clientX,
      startY: event.clientY,
      slotRects: previewPaneKeysRef.current
        .map((key) => paneRects.get(key))
        .filter((rect): rect is DOMRect => rect !== undefined),
      started: false,
    };
    setDraggingPaneKey(paneKey);
  }, [compact, measurePanes, panes.length]);

  const handleMovePointerMove = useCallback((event: globalThis.PointerEvent) => {
    const gesture = dragGestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const distance = Math.hypot(
      event.clientX - gesture.startX,
      event.clientY - gesture.startY,
    );
    if (!gesture.started) {
      if (distance < 8) return;
      gesture.started = true;
    }
    event.preventDefault();
    const targetIndex = paneSlotAtPoint(gesture.slotRects, event.clientX, event.clientY);
    const targetKey = targetIndex === null
      ? null
      : previewPaneKeysRef.current[targetIndex] ?? null;
    if (targetKey) applyPaneOrder(gesture.paneKey, targetKey);
  }, [applyPaneOrder]);

  const finishMoveGesture = useCallback(() => {
    if (!dragGestureRef.current) return;
    dragGestureRef.current = null;
    setDraggingPaneKey(null);
  }, []);

  useEffect(() => {
    if (!draggingPaneKey) return;

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const gesture = dragGestureRef.current;
      if (!gesture || gesture.pointerId !== event.pointerId) return;
      if ((event.buttons & 1) === 0) {
        finishMoveGesture();
        return;
      }
      handleMovePointerMove(event);
    };
    const handlePointerEnd = (event: globalThis.PointerEvent) => {
      if (dragGestureRef.current?.pointerId === event.pointerId) finishMoveGesture();
    };
    const root = document.documentElement;
    const previousCursor = root.style.cursor;
    root.style.cursor = "grabbing";
    window.addEventListener("pointermove", handlePointerMove, { passive: false });
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);
    window.addEventListener("blur", finishMoveGesture);
    return () => {
      root.style.cursor = previousCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
      window.removeEventListener("blur", finishMoveGesture);
    };
  }, [draggingPaneKey, finishMoveGesture, handleMovePointerMove]);

  const handleMoveKeyDown = useCallback((
    paneKey: string,
    event: KeyboardEvent<HTMLButtonElement>,
  ) => {
    const direction = (() => {
      switch (event.key) {
        case "ArrowLeft": return "left";
        case "ArrowRight": return "right";
        case "ArrowUp": return "up";
        case "ArrowDown": return "down";
        default: return null;
      }
    })();
    if (!direction) return;
    const targetKey = paneInDirection(measurePanes(), paneKey, direction);
    if (!targetKey) return;
    event.preventDefault();
    const next = movePaneToSlot(previewPaneKeysRef.current, paneKey, targetKey);
    captureLayout();
    previewPaneKeysRef.current = next;
    setPreviewPaneKeys(next);
    onPaneOrderChange(next);
  }, [captureLayout, measurePanes, onPaneOrderChange]);

  const gridStyle = paneGridStyle(effectiveLayout, panes.length);
  const currentLayout = LAYOUT_CONTROLS.find((control) => control.layout === layout)
    ?? LAYOUT_CONTROLS[0];
  const headerActions = chrome ? (
    <div
      data-workbench-pane-action
      className="host-no-drag flex items-center gap-0.5"
    >
      {showLayoutControl ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("workbench.layout", {
                defaultValue: "Pane layout",
              })}
              className="host-no-drag h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground"
            >
              <currentLayout.icon className="h-4 w-4" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            onCloseAutoFocus={(event) => event.preventDefault()}
          >
            <DropdownMenuLabel>
              {t("workbench.layout", { defaultValue: "Pane layout" })}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup
              value={layout}
              onValueChange={(value) => {
                const next = value as WorkbenchLayout;
                if (next === layout) return;
                captureLayout();
                onLayoutChange(next);
              }}
            >
              {LAYOUT_CONTROLS.map((control) => (
                <DropdownMenuRadioItem
                  key={control.layout}
                  value={control.layout}
                >
                  <control.icon aria-hidden />
                  {t(`workbench.layouts.${control.layout}`, {
                    defaultValue: control.label,
                  })}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
      <HeaderIconButton
        disabled={addPaneDisabled}
        icon={Plus}
        label={t("workbench.addPane", { defaultValue: "Add pane" })}
        onClick={() => {
          captureLayout();
          onAddPane();
        }}
      />
    </div>
  ) : null;

  return (
    <section
      aria-label={t("workbench.aria", { defaultValue: "Conversation workbench" })}
      className="flex h-full min-h-0 flex-col overflow-hidden bg-background"
    >
      <TooltipProvider delayDuration={500} skipDelayDuration={100}>
        {chrome ? (
          <header className="shrink-0 bg-background">
            <div
              ref={setHeaderPortalTarget}
              data-testid="workbench-header-host"
            />
          </header>
        ) : null}
        <div className="min-h-0 flex-1 bg-background">
          <div
            data-testid="pane-grid"
            data-layout={effectiveLayout}
            className={cn(
              "grid h-full min-h-0 min-w-0 overflow-hidden",
              chrome && panes.length > 1 && "gap-px bg-border/55",
            )}
            style={gridStyle}
          >
            {displayedPanes.map((pane, index) => {
              const active = pane.key === activePaneKey;
              const hidden = effectiveLayout === "compact" && !active;

              return (
                <section
                  key={pane.reactKey ?? pane.key}
                  ref={(element) => {
                    if (element) paneRefs.current.set(pane.key, element);
                    else paneRefs.current.delete(pane.key);
                  }}
                  hidden={hidden}
                  aria-label={pane.title}
                  data-active={active ? "true" : "false"}
                  data-dragging={draggingPaneKey === pane.key ? "true" : undefined}
                  data-testid={`workbench-pane-${pane.key}`}
                  onPointerDownCapture={(event) => handlePanePointerDown(pane.key, event)}
                  onFocusCapture={(event) => handlePaneFocus(pane.key, event)}
                  className="workbench-pane relative flex min-h-0 min-w-0 overflow-hidden bg-background"
                  style={paneCellStyle(effectiveLayout, panes.length, index)}
                >
                  {renderPane(pane, {
                    active,
                    headerPortalTarget: chrome ? headerPortalTarget : undefined,
                    composerPortalTarget: chrome ? composerPortalTarget : undefined,
                    headerActions,
                  })}
                  {chrome && panes.length > 1 && !compact ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          tabIndex={active ? 0 : -1}
                          aria-hidden={active ? undefined : true}
                          aria-label={active ? t("workbench.movePane", {
                            defaultValue: "Move {{title}} pane",
                            title: pane.title,
                          }) : undefined}
                          aria-keyshortcuts={active ? "ArrowLeft ArrowRight ArrowUp ArrowDown" : undefined}
                          data-workbench-pane-action
                          data-testid={`pane-move-handle-${pane.key}`}
                          onPointerDown={(event) => handleMovePointerDown(pane.key, event)}
                          onKeyDown={(event) => handleMoveKeyDown(pane.key, event)}
                          className={cn(
                            "group host-no-drag absolute bottom-0 left-1/2 z-30 flex h-6 w-12 -translate-x-1/2 touch-none items-center justify-center rounded-full",
                            "cursor-grab focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background active:cursor-grabbing",
                            "transition-opacity duration-100 motion-reduce:transition-none",
                            active ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
                          )}
                        >
                          <span
                            aria-hidden
                            className={cn(
                              "h-[3px] w-9 rounded-full bg-foreground/35 transition-colors duration-100 motion-reduce:transition-none",
                              draggingPaneKey === pane.key
                                ? "bg-foreground/65"
                                : "group-hover:bg-foreground/50",
                            )}
                          />
                        </button>
                      </TooltipTrigger>
                      {active ? (
                        <TooltipContent side="top">
                          {t("workbench.movePaneHint", {
                            defaultValue: "Drag to move · Arrow keys also work",
                          })}
                        </TooltipContent>
                      ) : null}
                    </Tooltip>
                  ) : null}
                </section>
              );
            })}
          </div>
        </div>

        {chrome ? (
          <footer className="shrink-0 bg-background px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:px-4">
            <div
              ref={setComposerPortalTarget}
              data-testid="workbench-composer-host"
              className="mx-auto w-full max-w-[58rem]"
            />
          </footer>
        ) : null}
      </TooltipProvider>
    </section>
  );
}
