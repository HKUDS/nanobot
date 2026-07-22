import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { MessageCircleMore } from "lucide-react";
import { useTranslation } from "react-i18next";

const MAX_QUOTED_CONTEXT_CHARS = 4_000;

interface SelectionActionState {
  text: string;
  left: number;
  top: number;
  above: boolean;
}

interface AssistantSelectionActionProps {
  containerRef: RefObject<HTMLElement | null>;
  onQuoteSelection?: (text: string) => void;
}

function selectableAncestor(node: Node | null, container: HTMLElement): HTMLElement | null {
  const element = node instanceof Element ? node : node?.parentElement;
  const selectable = element?.closest<HTMLElement>("[data-assistant-selectable='true']") ?? null;
  return selectable && container.contains(selectable) ? selectable : null;
}

function selectedRangeRect(range: Range): DOMRect | null {
  const rect = range.getBoundingClientRect();
  if (rect.width > 0 || rect.height > 0) return rect;
  return range.getClientRects()[0] ?? null;
}

function normalizedSelectionText(selection: Selection): string {
  return selection
    .toString()
    .replace(/\u00a0/g, " ")
    .replace(/\r\n?/g, "\n")
    .trim()
    .slice(0, MAX_QUOTED_CONTEXT_CHARS);
}

export function AssistantSelectionAction({
  containerRef,
  onQuoteSelection,
}: AssistantSelectionActionProps) {
  const { t } = useTranslation();
  const [action, setAction] = useState<SelectionActionState | null>(null);
  const frameRef = useRef<number | null>(null);
  const actionRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const element = actionRef.current;
    if (!action || !element) return;
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportRight = viewportLeft + (viewport?.width ?? window.innerWidth);
    const viewportBottom = viewportTop + (viewport?.height ?? window.innerHeight);
    const rect = element.getBoundingClientRect();
    const padding = 12;
    const shiftX = rect.left < viewportLeft + padding
      ? viewportLeft + padding - rect.left
      : rect.right > viewportRight - padding
        ? viewportRight - padding - rect.right
        : 0;
    const shiftY = rect.top < viewportTop + padding
      ? viewportTop + padding - rect.top
      : rect.bottom > viewportBottom - padding
        ? viewportBottom - padding - rect.bottom
        : 0;
    element.style.translate = `${shiftX}px ${shiftY}px`;
  }, [action]);

  useEffect(() => {
    if (!onQuoteSelection) return;

    const updateFromSelection = () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        const container = containerRef.current;
        const selection = window.getSelection();
        if (!container || !selection || selection.isCollapsed || selection.rangeCount === 0) {
          setAction(null);
          return;
        }
        const range = selection.getRangeAt(0);
        const start = selectableAncestor(range.startContainer, container);
        const end = selectableAncestor(range.endContainer, container);
        const text = normalizedSelectionText(selection);
        const rect = selectedRangeRect(range);
        if (!start || start !== end || !text || !rect) {
          setAction(null);
          return;
        }

        const viewport = window.visualViewport;
        const viewportTop = viewport?.offsetTop ?? 0;
        const viewportBottom = viewportTop + (viewport?.height ?? window.innerHeight);
        const above = rect.bottom + 52 > viewportBottom;
        setAction({
          text,
          left: rect.left + rect.width / 2,
          top: above ? rect.top - 8 : rect.bottom + 8,
          above,
        });
      });
    };

    const dismiss = () => setAction(null);
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest("[data-selection-follow-up='true']")) return;
      dismiss();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };

    document.addEventListener("selectionchange", updateFromSelection);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("scroll", dismiss, true);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", dismiss);
    window.visualViewport?.addEventListener("resize", dismiss);
    window.visualViewport?.addEventListener("scroll", dismiss);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      document.removeEventListener("selectionchange", updateFromSelection);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("scroll", dismiss, true);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", dismiss);
      window.visualViewport?.removeEventListener("resize", dismiss);
      window.visualViewport?.removeEventListener("scroll", dismiss);
    };
  }, [containerRef, onQuoteSelection]);

  if (!action || typeof document === "undefined") return null;

  return createPortal(
    <button
      ref={actionRef}
      type="button"
      data-selection-follow-up="true"
      className="fixed z-[80] inline-flex h-9 max-w-[calc(100vw-24px)] items-center gap-1.5 rounded-full border border-border/80 bg-popover px-3 text-[13px] font-medium text-popover-foreground shadow-lg shadow-black/10 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:shadow-black/35"
      style={{
        left: action.left,
        top: action.top,
        transform: action.above ? "translate(-50%, -100%)" : "translateX(-50%)",
      }}
      onPointerDown={(event) => event.preventDefault()}
      onClick={() => {
        onQuoteSelection?.(action.text);
        window.getSelection()?.removeAllRanges();
        setAction(null);
      }}
    >
      <MessageCircleMore className="h-3.5 w-3.5" aria-hidden />
      <span className="truncate">{t("message.askAboutSelection")}</span>
    </button>,
    document.body,
  );
}
