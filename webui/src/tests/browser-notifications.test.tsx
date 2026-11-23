import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserNotificationSettings } from "@/components/settings/notifications/BrowserNotificationSettings";
import { NotificationSettings } from "@/components/settings/notifications/NotificationSettings";
import { BrowserNotifications, useBrowserNotificationLifecycle } from "@/components/BrowserNotifications";
import { useLocalPreferences } from "@/hooks/useLocalPreferences";
import { enableBrowserNotifications, NOTIFICATION_OPEN_EVENT, notificationChatUrl, notificationProblem, showBrowserNotification, taskNoticeKey } from "@/lib/browser-notifications";
import { DEFAULT_LOCAL_PREFS, readLocalPreferences, writeLocalPreferences } from "@/lib/local-preferences";
import type { TaskNotice } from "@/lib/nanobot-client";
import i18n from "@/i18n";

const requestPermission = vi.fn();
const postMessage = vi.fn();
const worker = { postMessage };
const getRegistration = vi.fn();

function Harness({ enabled = false }: { enabled?: boolean }) {
  const [preferences, setPreferences] = useState({ ...DEFAULT_LOCAL_PREFS, browserNotifications: enabled });
  return <BrowserNotificationSettings localPrefs={preferences} onChangeLocalPrefs={setPreferences} />;
}

function LifecycleHarness({ settings = true }: { settings?: boolean }) {
  useBrowserNotificationLifecycle();
  const preferences = useLocalPreferences();
  return settings ? <BrowserNotificationSettings localPrefs={preferences}
    onChangeLocalPrefs={(update) => writeLocalPreferences(typeof update === "function" ? update(readLocalPreferences()) : update)} /> : null;
}

beforeEach(() => {
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal("Notification", { permission: "default", requestPermission });
  vi.stubGlobal("MessageChannel", class {
    port1 = { onmessage: null as ((event: MessageEvent) => void) | null, close: vi.fn() };
    port2 = { reply: (data: unknown) => this.port1.onmessage?.({ data } as MessageEvent) };
  });
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: Object.assign(new EventTarget(), { getRegistration, controller: worker }) });
  getRegistration.mockResolvedValue({ active: worker });
  postMessage.mockImplementation((data, ports) => { queueMicrotask(() => ports[0].reply(data.type === "nanobot:notification-probe" ? "ready" : "submitted")); });
  requestPermission.mockImplementation(() => {
    vi.stubGlobal("Notification", { permission: "granted", requestPermission });
    return Promise.resolve("granted");
  });
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
    expect(await showing).toBe("workerUnavailable");
  });

  it("reports an older active worker that does not understand the notification protocol", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Notification", { permission: "granted" });
    postMessage.mockImplementation(() => {});
    const enabling = enableBrowserNotifications();
    await vi.advanceTimersByTimeAsync(5_001);
    expect(await enabling).toBe("workerUnavailable");
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it("uses the worker without constructing Notification, and isolates a post failure", async () => {
    const constructor = vi.fn(() => { throw new TypeError("Mobile constructor unavailable"); });
    vi.stubGlobal("Notification", Object.assign(constructor, { permission: "granted" }));
    const options = { key: "one", url: notificationChatUrl("one", false) };
    expect(await showBrowserNotification("Task completed", options)).toBe("submitted");
    expect(constructor).not.toHaveBeenCalled();
    postMessage.mockImplementation(() => { throw new Error("worker stopped"); });
    expect(await showBrowserNotification("Task completed", options)).toBe("workerUnavailable");
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
  it("keeps completion sound independent when browser notifications are unavailable", () => {
    vi.stubGlobal("Notification", undefined);
    function Page() {
      const [preferences, setPreferences] = useState(DEFAULT_LOCAL_PREFS);
      return <NotificationSettings localPrefs={preferences} onChangeLocalPrefs={setPreferences} />;
    }
    render(<Page />);
    expect(screen.getByRole("switch", { name: "Browser notifications" })).toBeDisabled();
    const sound = screen.getByRole("switch", { name: "Completion sound" });
    expect(sound).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sound);
    expect(sound).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: "Browser notifications" })).toHaveAttribute("aria-checked", "false");
  });

  it("explains unavailable notification support beside a disabled switch", () => {
    vi.stubGlobal("Notification", undefined);
    render(<Harness />);
    expect(screen.getByRole("switch", { name: "Browser notifications" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("This browser doesn’t support notifications");
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Test notification" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Test notification" }));
    await screen.findByText(/Sent to the browser/);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: "Test notification" })).not.toBeInTheDocument();
  });

  it("reconciles revocation outside settings and requires opt-in after regranting permission", async () => {
    vi.stubGlobal("Notification", { permission: "granted" });
    writeLocalPreferences({ ...DEFAULT_LOCAL_PREFS, browserNotifications: true, notificationSound: true });
    const { rerender } = render(<LifecycleHarness settings={false} />);
    vi.stubGlobal("Notification", { permission: "denied" });
    fireEvent.focus(window);
    expect(readLocalPreferences()).toMatchObject({ browserNotifications: false, notificationSound: true });
    rerender(<LifecycleHarness />);
    expect(screen.getByRole("status")).toHaveTextContent("Notification permission was revoked");
    expect(screen.queryByRole("button", { name: "Test notification" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    vi.stubGlobal("Notification", { permission: "granted", requestPermission });
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(screen.getByRole("switch")).toBeEnabled();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true"));
  });

  it("allows opt-out and an explicit readiness retry when the worker is unavailable", async () => {
    vi.stubGlobal("Notification", { permission: "granted" });
    getRegistration.mockResolvedValue(null);
    render(<Harness enabled />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("notification service is not ready"));
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    getRegistration.mockResolvedValue({ active: worker });
    const retry = screen.getByRole("button", { name: "Check again" });
    await waitFor(() => expect(retry).toBeEnabled());
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Check again" })).not.toBeInTheDocument());
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
  expect(postMessage.mock.calls[0][0]).toMatchObject({ body: "任务失败，点击查看详情。", url: notificationChatUrl("other", false) });
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
  expect(postMessage.mock.calls[0][0]).toMatchObject({ body: "Task needs attention. Click to continue." });
});

it("keeps validated notification navigation alive through sign-out and reveals the owning host", () => {
  const client = { onTaskNotice: () => () => {} };
  function AuthBoundary({ authenticated }: { authenticated: boolean }) {
    useBrowserNotificationLifecycle();
    return authenticated ? <BrowserNotifications client={client} /> : null;
  }
  const { rerender } = render(<AuthBoundary authenticated />);
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
  window.location.hash = "#/settings?section=notifications";
  rerender(<AuthBoundary authenticated={false} />);
  send(worker, url);
  expect(window.location.hash).toBe("#/chat/websocket%3Aclicked");
  rerender(<AuthBoundary authenticated />);
  expect(window.location.hash).toBe("#/chat/websocket%3Aclicked");
  window.removeEventListener(NOTIFICATION_OPEN_EVENT, reveal);
  window.history.replaceState(null, "", "/");
});

it("keys recovery alerts by recovery identity, not by chat mounting", () => {
  const event = { event: "recovery_state", chat_id: "one", recovery_id: "attempt", status: "awaiting_user" } as const;
  expect(taskNoticeKey({ event, temporary: false })).toBe('["one","attempt","awaiting_user"]');
  expect(taskNoticeKey({ event: { ...event, status: "recovered" }, temporary: false })).toBeNull();
});
