export const SESSION_DRAG_TYPE = "application/x-nanobot-session-key";

let activeSessionKey: string | null = null;

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

export function writeDraggedSession(
  dataTransfer: DataTransfer,
  sessionKey: string,
): void {
  activeSessionKey = sessionKey;
  dataTransfer.effectAllowed = "copyMove";
  dataTransfer.setData(SESSION_DRAG_TYPE, sessionKey);
}
