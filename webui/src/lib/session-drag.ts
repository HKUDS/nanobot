export const SESSION_DRAG_TYPE = "application/x-nanobot-session-key";
export const PANE_DRAG_TYPE = "application/x-nanobot-pane";

export interface DraggedPane {
  paneKey: string;
  sourceTabKey: string;
}

let activeSessionKey: string | null = null;
let activePane: DraggedPane | null = null;

export function hasDraggedSession(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes(SESSION_DRAG_TYPE);
}

export function readDraggedSession(dataTransfer: DataTransfer): string | null {
  const sessionKey = dataTransfer.getData(SESSION_DRAG_TYPE).trim();
  return sessionKey || activeSessionKey;
}

export function clearDraggedSession(): void {
  activeSessionKey = null;
  activePane = null;
}

export function writeDraggedSession(
  dataTransfer: DataTransfer,
  sessionKey: string,
): void {
  activeSessionKey = sessionKey;
  dataTransfer.effectAllowed = "copyMove";
  dataTransfer.setData(SESSION_DRAG_TYPE, sessionKey);
}

export function readDraggedPane(dataTransfer: DataTransfer): DraggedPane | null {
  const serialized = dataTransfer.getData(PANE_DRAG_TYPE).trim();
  if (serialized) {
    try {
      const parsed = JSON.parse(serialized) as Partial<DraggedPane>;
      if (parsed.paneKey && parsed.sourceTabKey) {
        return { paneKey: parsed.paneKey, sourceTabKey: parsed.sourceTabKey };
      }
    } catch {
      // Fall through to the in-memory payload used while the native drag is active.
    }
  }
  return activePane;
}

export function writeDraggedPane(
  dataTransfer: DataTransfer,
  pane: DraggedPane,
): void {
  activePane = pane;
  writeDraggedSession(dataTransfer, pane.paneKey);
  dataTransfer.setData(PANE_DRAG_TYPE, JSON.stringify(pane));
}
