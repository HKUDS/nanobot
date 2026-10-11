import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserNotificationSettings } from "@/components/settings/overview/BrowserNotificationSettings";
import { BrowserNotifications } from "@/components/BrowserNotifications";
import { enableBrowserNotifications, NOTIFICATION_OPEN_EVENT, notificationChatUrl, notificationProblem, showBrowserNotification, taskNoticeKey } from "@/lib/browser-notifications";
import { DEFAULT_LOCAL_PREFS, writeLocalPreferences } from "@/lib/local-preferences";
import type { TaskNotice } from "@/lib/nanobot-client";
import i18n from "@/i18n";

const requestPermission = vi.fn();
const postMessage = vi.fn();
const worker = { postMessage };
const getRegistration = vi.fn();
let receive: ((event: MessageEvent) => void) | null;

function Harness({ enabled = false }: { enabled?: boolean }) {
  const [preferences, setPreferences] = useState({ ...DEFAULT_LOCAL_PREFS, browserNotifications: enabled });
  return <BrowserNotificationSettings localPrefs={preferences} onChangeLocalPrefs={setPreferences} />;
}

beforeEach(() => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("Notification", { permission: "default", requestPermission });
  vi.stubGlobal("MessageChannel", class {
    port1 = { onmessage: null as ((event: MessageEvent) => void) | null, close: vi.fn() };
    port2 = {};
    constructor() { queueMicrotask(() => { receive = this.port1.onmessage; }); }
  });
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: Object.assign(new EventTarget(), { getRegistration, controller: worker }) });
  getRegistration.mockResolvedValue({ active: worker });
  postMessage.mockImplementation(() => { setTimeout(() => receive?.({ data: "submitted" } as MessageEvent), 0); });
  requestPermission.mockResolvedValue("granted");
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, browserNotifications: true });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
  delete (navigator as unknown as { serviceWorker?: unknown }).serviceWorker;
  Reflect.deleteProperty(document, "visibilityState");
  localStorage.clear();
});

describe("notification permission and delivery boundary", () => {
  it("distinguishes insecure contexts, missing APIs, and browser denial", () => {
    vi.stubGlobal("isSecureContext", false);
    expect(notificationProblem()).toBe("insecure");
    vi.stubGlobal("isSecureContext", true); // Includes localhost, decided by the browser.
    vi.stubGlobal("Notification", undefined);
    expect(notificationProblem()).toBe("unsupported");
    vi.stubGlobal("Notification", { permission: "denied" });
    expect(notificationProblem()).toBe("denied");
  });

  it.each(["default", "denied"])("reports a permission response of %s", async (permission) => {
    requestPermission.mockResolvedValue(permission);
    expect(await enableBrowserNotifications()).toBe(permission === "default" ? "dismissed" : "denied");
  });

  it("requests permission synchronously from the user gesture and requires an active worker", async () => {
    const enabling = enableBrowserNotifications();
    expect(requestPermission).toHaveBeenCalledTimes(1);
    expect(await enabling).toBeNull();
    getRegistration.mockResolvedValue({ installing: worker });
    expect(await enableBrowserNotifications()).toBe("workerUnavailable");
  });

  it("handles permission and registration failures without rejected promises", async () => {
    requestPermission.mockRejectedValue(new Error("permission blocked"));
    expect(await enableBrowserNotifications()).toBe("permissionFailed");
    requestPermission.mockResolvedValue("granted");
    getRegistration.mockRejectedValue(new Error("storage blocked"));
    expect(await enableBrowserNotifications()).toBe("workerUnavailable");
  });

  it("bounds registration and worker response waits", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Notification", { permission: "granted" });
    getRegistration.mockImplementationOnce(() => new Promise(() => {}));
    const enabling = enableBrowserNotifications();
    await vi.advanceTimersByTimeAsync(5_001);
    expect(await enabling).toBe("workerUnavailable");
    postMessage.mockImplementation(() => {});
    const showing = showBrowserNotification("Task completed", { key: "one", url: notificationChatUrl("one", false) });
    await vi.advanceTimersByTimeAsync(5_001);
    expect(await showing).toBe("displayFailed");
  });

  it("uses the worker without constructing Notification, and isolates a post failure", async () => {
    const constructor = vi.fn(() => { throw new TypeError("Mobile constructor unavailable"); });
    vi.stubGlobal("Notification", Object.assign(constructor, { permission: "granted" }));
    const options = { key: "one", url: notificationChatUrl("one", false) };
    expect(await showBrowserNotification("Task completed", options)).toBe("submitted");
    expect(constructor).not.toHaveBeenCalled();
    postMessage.mockImplementation(() => { throw new Error("worker stopped"); });
    expect(await showBrowserNotification("Task completed", options)).toBe("displayFailed");
  });

  it("does not notify while visible, disabled, or disabled during a lookup", async () => {
    vi.stubGlobal("Notification", { permission: "granted" });
    const options = { key: "one", url: notificationChatUrl("one", false) };
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    expect(await showBrowserNotification("Task completed", options)).toBe("skipped");
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    let finish!: (registration: unknown) => void;
    getRegistration.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = showBrowserNotification("Task completed", options);
    writeLocalPreferences(DEFAULT_LOCAL_PREFS);
    finish({ active: worker });
    expect(await pending).toBe("skipped");
    expect(await showBrowserNotification("Task completed", options)).toBe("skipped");
    expect(postMessage).not.toHaveBeenCalled();
  });

  it("keeps links on this gateway without copying query credentials", () => {
    window.history.replaceState(null, "", "/?token=secret#/chat/old");
    expect(notificationChatUrl("a/b", false)).toBe(`${window.location.origin}/#/chat/websocket%3Aa%2Fb`);
    expect(notificationChatUrl("temp", true)).toBe(`${window.location.origin}/#/temporary/temp`);
    window.history.replaceState(null, "", "/");
  });
});

describe("notification settings", () => {
  it("explains unavailable notification support beside a disabled switch", () => {
    vi.stubGlobal("Notification", undefined);
    render(<Harness />);
    expect(screen.getByRole("switch", { name: "Browser notifications" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("This browser cannot send notifications");
  });

  it("reports dismissal and lets the user retry, test, and disable", async () => {
    requestPermission.mockResolvedValueOnce("default").mockImplementationOnce(() => {
      vi.stubGlobal("Notification", { permission: "granted", requestPermission });
      return Promise.resolve("granted");
    });
    render(<Harness />);
    const toggle = screen.getByRole("switch", { name: "Browser notifications" });
    fireEvent.click(toggle);
    await screen.findByText("Permission was not granted. Turn on notifications and choose Allow.");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    fireEvent.click(screen.getByRole("button", { name: "Test notification" }));
    await screen.findByText(/Sent to the browser/);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: "Test notification" })).not.toBeInTheDocument();
  });

  it("updates revoked permission on return and still allows opt-out", () => {
    vi.stubGlobal("Notification", { permission: "granted" });
    render(<Harness enabled />);
    vi.stubGlobal("Notification", { permission: "denied" });
    fireEvent.focus(window);
    expect(screen.getByRole("status")).toHaveTextContent("Notifications are blocked");
    expect(screen.queryByRole("button", { name: "Test notification" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("does not save late permission results after leaving settings", async () => {
    let resolve!: (permission: string) => void;
    requestPermission.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const save = vi.fn();
    const { unmount } = render(<BrowserNotificationSettings localPrefs={DEFAULT_LOCAL_PREFS} onChangeLocalPrefs={save} />);
    fireEvent.click(screen.getByRole("switch"));
    unmount();
    await act(async () => { resolve("granted"); });
    expect(save).not.toHaveBeenCalled();
  });
});

it("subscribes outside a chat, uses generic localized text, and cleans up", async () => {
  vi.stubGlobal("Notification", { permission: "granted" });
  await i18n.changeLanguage("zh-CN");
  let handler!: (notice: TaskNotice) => void;
  const unsubscribe = vi.fn();
  const client = { onTaskNotice: (value: typeof handler) => { handler = value; return unsubscribe; } };
  const { unmount } = render(<BrowserNotifications client={client} />);
  const event = { event: "turn_end", chat_id: "other", turn_id: "turn", outcome: "failed", failure_message: "PRIVATE TOKEN" } as const;
  handler({ event, temporary: false });
  await waitFor(() => expect(postMessage).toHaveBeenCalled());
  expect(postMessage.mock.calls[0][0]).toMatchObject({ body: "任务未完成，打开 nanobot 查看详情。", url: notificationChatUrl("other", false) });
  expect(JSON.stringify(postMessage.mock.calls[0][0])).not.toContain("PRIVATE TOKEN");
  expect(taskNoticeKey({ event, temporary: false })).toBe('["other","turn","end"]');
  unmount();
  expect(unsubscribe).toHaveBeenCalledOnce();
});

it("does not report cancellation or interruption as completion", async () => {
  vi.stubGlobal("Notification", { permission: "granted" });
  await i18n.changeLanguage("en");
  let handler!: (notice: TaskNotice) => void;
  const client = { onTaskNotice: (value: typeof handler) => { handler = value; return () => {}; } };
  render(<BrowserNotifications client={client} />);
  const event = { event: "turn_end", chat_id: "one", turn_id: "turn", outcome: "cancelled" } as const;
  handler({ event, temporary: false });
  expect(taskNoticeKey({ event, temporary: false })).toBeNull();
  expect(postMessage).not.toHaveBeenCalled();
  handler({ event: { ...event, outcome: "interrupted" }, temporary: false });
  await waitFor(() => expect(postMessage).toHaveBeenCalled());
  expect(postMessage.mock.calls[0][0]).toMatchObject({ body: "Task needs attention. Open nanobot to continue." });
});

it("opens a notification only from the controlling worker and reveals the owning host", () => {
  const client = { onTaskNotice: () => () => {} };
  render(<BrowserNotifications client={client} />);
  const reveal = vi.fn();
  window.addEventListener(NOTIFICATION_OPEN_EVENT, reveal);
  const url = notificationChatUrl("clicked", false);
  const send = (source: unknown, target: string) => navigator.serviceWorker.dispatchEvent(new MessageEvent("message", {
    source: source as Window, data: { type: "nanobot:notification-click", url: target },
  }));
  send(window, url);
  send(worker, "https://wrong-host.example/#/chat/other");
  expect(reveal).not.toHaveBeenCalled();
  send(worker, url);
  expect(window.location.hash).toBe("#/chat/websocket%3Aclicked");
  expect(reveal).toHaveBeenCalledOnce();
  window.removeEventListener(NOTIFICATION_OPEN_EVENT, reveal);
  window.history.replaceState(null, "", "/");
});

it("keys recovery alerts by recovery identity, not by chat mounting", () => {
  const event = { event: "recovery_state", chat_id: "one", recovery_id: "attempt", status: "awaiting_user" } as const;
  expect(taskNoticeKey({ event, temporary: false })).toBe('["one","attempt","awaiting_user"]');
  expect(taskNoticeKey({ event: { ...event, status: "recovered" }, temporary: false })).toBeNull();
});
