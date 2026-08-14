export const SESSION_DRAG_TYPE = "application/x-nanobot-session-key";
export const WORKBENCH_GROUP_DRAG_TYPE = "application/x-nanobot-workbench-group-key";

let activeSessionKey: string | null = null;
let activeWorkbenchGroupKey: string | null = null;

export function hasDraggedSession(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes(SESSION_DRAG_TYPE);
}

export function readDraggedSession(dataTransfer: DataTransfer): string | null {
  const sessionKey = dataTransfer.getData(SESSION_DRAG_TYPE).trim();
  return sessionKey || activeSessionKey;
}

export function clearDraggedSession(): void {
  activeSessionKey = null;
}

export function hasDraggedWorkbenchGroup(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes(WORKBENCH_GROUP_DRAG_TYPE);
}

export function readDraggedWorkbenchGroup(dataTransfer: DataTransfer): string | null {
  const groupKey = dataTransfer.getData(WORKBENCH_GROUP_DRAG_TYPE).trim();
  return groupKey || activeWorkbenchGroupKey;
}

export function clearDraggedWorkbenchGroup(): void {
  activeWorkbenchGroupKey = null;
}

export function writeDraggedSession(
  dataTransfer: DataTransfer,
  sessionKey: string,
): void {
  activeSessionKey = sessionKey;
  dataTransfer.effectAllowed = "copyMove";
  dataTransfer.setData(SESSION_DRAG_TYPE, sessionKey);
}

export function writeDraggedWorkbenchGroup(
  dataTransfer: DataTransfer,
  groupKey: string,
): void {
  activeWorkbenchGroupKey = groupKey;
  dataTransfer.effectAllowed = "move";
  dataTransfer.setData(WORKBENCH_GROUP_DRAG_TYPE, groupKey);
}
