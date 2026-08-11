import type { DraggedPane } from "@/lib/session-drag";

export interface PaneDropSlot {
  beforePaneKey: string | null;
  tabKey: string;
}

export interface PaneTabDragState {
  height: number;
  item: DraggedPane;
  origin: "pane" | "tab";
  slot: PaneDropSlot | null;
}

export interface PaneTabDragLayout {
  offsets: Map<string, number>;
  slotIndex: number;
}

export function samePaneDropSlot(
  current: PaneDropSlot | null,
  next: PaneDropSlot | null,
): boolean {
  return current?.tabKey === next?.tabKey
    && current?.beforePaneKey === next?.beforePaneKey;
}

export function paneDropSlotForRow(
  tabKey: string,
  paneKeys: string[],
  draggedPaneKey: string,
  targetPaneKey: string,
  edge: "before" | "after",
): PaneDropSlot {
  const remaining = paneKeys.filter((key) => key !== draggedPaneKey);
  const targetIndex = remaining.indexOf(targetPaneKey);
  const insertionIndex = targetIndex < 0
    ? remaining.length
    : targetIndex + (edge === "after" ? 1 : 0);
  return {
    tabKey,
    beforePaneKey: remaining[insertionIndex] ?? null,
  };
}

export function paneTabDragLayout(
  paneKeys: string[],
  tabKey: string,
  drag: PaneTabDragState | null,
): PaneTabDragLayout {
  const offsets = new Map<string, number>();
  if (!drag || drag.height <= 0) {
    return { offsets, slotIndex: -1 };
  }
  const distance = drag.height + 2;
  const sourceIndex = paneKeys.indexOf(drag.item.paneKey);
  if (
    sourceIndex < 0
    || drag.item.sourceTabKey !== tabKey
    || drag.slot?.tabKey !== tabKey
  ) {
    return { offsets, slotIndex: -1 };
  }

  const remaining = paneKeys.filter((key) => key !== drag.item.paneKey);
  const requestedIndex = drag.slot.beforePaneKey
    ? remaining.indexOf(drag.slot.beforePaneKey)
    : remaining.length;
  const slotIndex = requestedIndex < 0 ? remaining.length : requestedIndex;

  if (sourceIndex < slotIndex) {
    for (let index = sourceIndex + 1; index <= slotIndex; index += 1) {
      offsets.set(paneKeys[index], -distance);
    }
  } else if (sourceIndex > slotIndex) {
    for (let index = slotIndex; index < sourceIndex; index += 1) {
      offsets.set(paneKeys[index], distance);
    }
  }
  return { offsets, slotIndex };
}
