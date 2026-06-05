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
  text?: unknown;
};

interface DesktopNotifierOptions {
  getWindow: () => BrowserWindow | null;
}

const MAX_NOTIFICATION_BODY_LENGTH = 180;
const MAX_NOTIFICATION_TITLE_LENGTH = 80;

let unreadNotificationCount = 0;

export function handleDesktopNotificationFrame(
  data: string,
  options: DesktopNotifierOptions,
): void {
  const frame = parseWsMessageFrame(data);
  if (!frame || !isAssistantNotificationFrame(frame)) return;
  if (!shouldNotify(options.getWindow())) return;
  showDesktopNotification(frame, options);
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
