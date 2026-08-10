import {
  Columns2,
  Grid2X2,
  PanelLeft,
  Plus,
  Rows2,
  Square,
  type LucideIcon,
} from "lucide-react";
import {
  type CSSProperties,
  type FocusEvent,
  type PointerEvent,
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
  addPaneDisabled?: boolean;
  onActivatePane: (key: string) => void;
  onAddPane: () => void;
  onLayoutChange: (layout: WorkbenchLayout) => void;
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
  { icon: PanelLeft, layout: "main-stack", label: "Main and stack" },
  { icon: Square, layout: "monocle", label: "Monocle" },
];

function paneGridStyle(layout: WorkbenchLayout, paneCount: number): CSSProperties {
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
    case "monocle":
      return {
        gridTemplateColumns: "minmax(0, 1fr)",
        gridTemplateRows: "minmax(0, 1fr)",
      };
  }
}

function paneCellStyle(
  layout: WorkbenchLayout,
  paneCount: number,
  index: number,
): CSSProperties | undefined {
  if (layout !== "main-stack" || paneCount < 2) return undefined;
  return index === 0
    ? { gridColumn: 1, gridRow: `1 / span ${paneCount - 1}` }
    : { gridColumn: 2, gridRow: index };
}

function isPaneAction(target: EventTarget | null): boolean {
  return target instanceof Element
    && target.closest("[data-workbench-pane-action]") !== null;
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
  addPaneDisabled = false,
  onActivatePane,
  onAddPane,
  onLayoutChange,
  renderPane,
}: PaneWorkbenchProps) {
  const { t } = useTranslation();
  const compact = useMediaQuery("(max-width: 767px)");
  const effectiveLayout = compact ? "monocle" : layout;
  const [headerPortalTarget, setHeaderPortalTarget] = useState<HTMLElement | null>(null);
  const [composerPortalTarget, setComposerPortalTarget] = useState<HTMLElement | null>(null);
  const paneRefs = useRef(new Map<string, HTMLElement>());
  const lastRectsRef = useRef(new Map<string, DOMRect>());
  const pendingRectsRef = useRef<Map<string, DOMRect> | null>(null);
  const animationsRef = useRef(new Map<string, Animation>());
  const paneOrder = useMemo(() => panes.map((pane) => pane.key).join("\u0000"), [panes]);

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
    event: PointerEvent<HTMLElement>,
  ) => {
    activatePane(key, event.target);
  }, [activatePane]);

  const handlePaneFocus = useCallback((key: string, event: FocusEvent<HTMLElement>) => {
    activatePane(key, event.target);
  }, [activatePane]);

  const gridStyle = paneGridStyle(effectiveLayout, panes.length);
  const currentLayout = LAYOUT_CONTROLS.find((control) => control.layout === layout)
    ?? LAYOUT_CONTROLS[0];
  const headerActions = chrome ? (
    <div
      data-workbench-pane-action
      className="host-no-drag flex items-center gap-0.5"
    >
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
            {panes.map((pane, index) => {
              const active = pane.key === activePaneKey;
              const hidden = effectiveLayout === "monocle" && !active;

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
