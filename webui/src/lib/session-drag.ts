export const SESSION_DRAG_TYPE = "application/x-nanobot-session-key";

export function hasDraggedSession(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes(SESSION_DRAG_TYPE);
}

export function readDraggedSession(dataTransfer: DataTransfer): string | null {
  const sessionKey = dataTransfer.getData(SESSION_DRAG_TYPE).trim();
  return sessionKey || null;
}

export function writeDraggedSession(
  dataTransfer: DataTransfer,
  sessionKey: string,
): void {
  dataTransfer.effectAllowed = "copy";
  dataTransfer.setData(SESSION_DRAG_TYPE, sessionKey);
}
