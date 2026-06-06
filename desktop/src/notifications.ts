import {
  app,
  BrowserWindow,
  Notification,
} from "electron";

type NotificationSource = {
  kind?: unknown;
  label?: unknown;
};

type WsMessageFrame = {
  chat_id?: unknown;
  event?: unknown;
  kind?: unknown;
  source?: NotificationSource;
  stream_id?: unknown;
  text?: unknown;
};

interface DesktopNotifierOptions {
  getWindow: () => BrowserWindow | null;
}

const MAX_NOTIFICATION_BODY_LENGTH = 180;
const MAX_NOTIFICATION_TITLE_LENGTH = 80;

let unreadNotificationCount = 0;
const streamTextBuffers = new Map<string, string>();

export function handleDesktopNotificationFrame(
  data: string,
  options: DesktopNotifierOptions,
): void {
  const frame = parseWsMessageFrame(data);
  const notificationFrame = frame ? notificationFrameFromWsFrame(frame) : null;
  if (!notificationFrame) return;
  if (!shouldNotify(options.getWindow())) return;
  showDesktopNotification(notificationFrame, options);
}

export function clearDesktopNotificationBadge(): void {
  unreadNotificationCount = 0;
  app.setBadgeCount(0);
}

function parseWsMessageFrame(data: string): WsMessageFrame | null {
  try {
    const parsed = JSON.parse(data) as unknown;
    return parsed && typeof parsed === "object"
      ? parsed as WsMessageFrame
      : null;
  } catch {
    return null;
  }
}

function isAssistantNotificationFrame(frame: WsMessageFrame): frame is WsMessageFrame & {
  chat_id: string;
  text: string;
} {
  return (
    frame.event === "message" &&
    typeof frame.chat_id === "string" &&
    typeof frame.text === "string" &&
    frame.text.trim().length > 0 &&
    frame.kind !== "tool_hint" &&
    frame.kind !== "progress" &&
    frame.kind !== "reasoning"
  );
}

function notificationFrameFromWsFrame(frame: WsMessageFrame): WsMessageFrame & {
  chat_id: string;
  text: string;
} | null {
  if (isAssistantNotificationFrame(frame)) return frame;
  if (frame.event === "delta") {
    if (typeof frame.chat_id === "string" && typeof frame.text === "string") {
      const key = streamNotificationKey(frame);
      streamTextBuffers.set(key, `${streamTextBuffers.get(key) ?? ""}${frame.text}`);
    }
    return null;
  }
  if (frame.event === "stream_end" && typeof frame.chat_id === "string") {
    const key = streamNotificationKey(frame);
    const text = typeof frame.text === "string"
      ? frame.text
      : streamTextBuffers.get(key) ?? "";
    streamTextBuffers.delete(key);
    return text.trim().length > 0
      ? { ...frame, chat_id: frame.chat_id, text }
      : null;
  }
  return null;
}

function streamNotificationKey(frame: WsMessageFrame): string {
  const streamId = typeof frame.stream_id === "string" ? frame.stream_id : "";
  return `${frame.chat_id ?? ""}\u0000${streamId}`;
}

function shouldNotify(win: BrowserWindow | null): boolean {
  if (!Notification.isSupported()) return false;
  if (!win || win.isDestroyed()) return false;
  return !win.isFocused();
}

function showDesktopNotification(
  frame: WsMessageFrame & { chat_id: string; text: string },
  options: DesktopNotifierOptions,
): void {
  const notification = new Notification({
    title: notificationTitle(frame.source),
    body: notificationBody(frame.text),
    subtitle: "nanobot",
  });
  notification.on("failed", (_event, error) => {
    console.warn(`[nanobot] Desktop notification failed: ${error}`);
  });
  notification.on("click", () => openChatFromNotification(frame.chat_id, options));
  notification.show();
  unreadNotificationCount += 1;
  app.setBadgeCount(unreadNotificationCount);
}

function notificationTitle(source: NotificationSource | undefined): string {
  if (source?.kind === "cron" && typeof source.label === "string") {
    const label = source.label.trim();
    if (label) return truncateText(label, MAX_NOTIFICATION_TITLE_LENGTH);
  }
  return "nanobot";
}

function notificationBody(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return truncateText(compact, MAX_NOTIFICATION_BODY_LENGTH);
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 3)}...`;
}

function openChatFromNotification(chatId: string, options: DesktopNotifierOptions): void {
  const win = options.getWindow();
  if (!win || win.isDestroyed()) return;
  if (win.isMinimized()) win.restore();
  if (!win.isVisible()) win.show();
  win.focus();
  clearDesktopNotificationBadge();

  const sessionKey = `websocket:${chatId}`;
  const hash = `#/chat/${encodeURIComponent(sessionKey)}`;
  void win.webContents.executeJavaScript(
    `window.location.hash = ${JSON.stringify(hash)}`,
    true,
  ).catch(() => {});
}
