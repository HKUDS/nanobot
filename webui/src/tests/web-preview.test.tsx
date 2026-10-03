// @vitest-environment-options {"settings":{"disableIframePageLoading":true}}
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebLink, WebPreviewContext } from "@/components/WebLink";
import { WebPreviewPanel } from "@/components/WebPreviewPanel";
import { FilePreviewStore, useFilePreviewState } from "@/hooks/useFilePreviewState";
import { copyTextToClipboard } from "@/lib/clipboard";
import { isNativeRuntime } from "@/lib/runtime";
import { parseWebLink, webPreviewRestriction } from "@/lib/web-preview";

vi.mock("@/lib/runtime", () => ({ isNativeRuntime: vi.fn(() => false) }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));
const credentialless = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "credentialless");

beforeEach(() => {
  vi.mocked(isNativeRuntime).mockReturnValue(false);
  vi.mocked(copyTextToClipboard).mockResolvedValue(true);
  Object.defineProperty(HTMLIFrameElement.prototype, "credentialless", { configurable: true, value: false });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  if (credentialless) Object.defineProperty(HTMLIFrameElement.prototype, "credentialless", credentialless);
  else Reflect.deleteProperty(HTMLIFrameElement.prototype, "credentialless");
});

describe("web preview boundaries", () => {
  it.each(["javascript:alert(1)", "data:text/html,hello", "file:///etc/passwd", "https://user:password@example.com/", "https://example.com/\n", "https:\\example.com", "/api/settings", "https://example.com/" + "x".repeat(8192)])("rejects %s", (url) => {
    expect(parseWebLink(url)).toBeNull();
  });
  it("keeps URL query/hash and accepts loopback without treating it as a server-side fetch", () => {
    expect(parseWebLink("http://127.1:4173/page?q=one#two")?.href).toBe("http://127.0.0.1:4173/page?q=one#two");
  });
  it("gates native, unsupported, same-origin and mixed-content embeds", () => {
    const page = new URL("https://nanobot.example");
    const external = new URL("https://example.com");
    expect(webPreviewRestriction(external, page, true, true)).toBe("native");
    expect(webPreviewRestriction(external, page, false, false)).toBe("unsupported");
    expect(webPreviewRestriction(page, page, false, true)).toBe("sameOrigin");
    expect(webPreviewRestriction(new URL("http://example.com"), page, false, true)).toBe("mixedContent");
    expect(webPreviewRestriction(external, page, false, true)).toBeNull();
  });
  it("embeds only on mount, without credentials/referrer/host permissions, and refreshes with a new frame", async () => {
    const { container } = render(<WebPreviewPanel url="https://example.com/demo" />);
    const frame = container.querySelector("iframe")!;
    expect(frame).toHaveAttribute("src", "https://example.com/demo");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).toHaveAttribute("credentialless", "");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(frame.getAttribute("allow")).toContain("clipboard-read 'none'");
    // A frame load event is not evidence that CSP/X-Frame-Options allowed embedding.
    fireEvent.load(frame);
    expect(screen.queryByText(/Some sites block embedding/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "About website previews" }));
    expect(await screen.findByText(/Some sites block embedding/)).toBeInTheDocument();
    await userEvent.setup().keyboard("{Escape}");
    fireEvent.click(screen.getByRole("button", { name: "Refresh website" }));
    expect(container.querySelector("iframe")).not.toBe(frame);
    expect(screen.getByRole("link", { name: "Open in browser" })).toHaveAttribute("rel", "noreferrer noopener");
  });
  it("does not load an iframe in native or unsupported browsers", () => {
    vi.mocked(isNativeRuntime).mockReturnValue(true);
    const { container, rerender } = render(<WebPreviewPanel url="https://example.com" />);
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/native host/);
    vi.mocked(isNativeRuntime).mockReturnValue(false);
    Reflect.deleteProperty(HTMLIFrameElement.prototype, "credentialless");
    rerender(<WebPreviewPanel url="https://example.com" />);
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/does not support/);
  });
  it("explains that loopback belongs to the browsing device on request", async () => {
    render(<WebPreviewPanel url="http://127.0.0.1:4173" />);
    fireEvent.click(screen.getByRole("button", { name: "About website previews" }));
    expect(await screen.findByText(/not a remote gateway/)).toBeInTheDocument();
  });
});

describe("web link actions", () => {
  it("keeps the primary link without a persistent action button or extra tab stop", () => {
    render(<WebLink href="https://example.com/">Long website title</WebLink>);
    const link = screen.getByRole("link", { name: "Long website title" });
    expect(link).toHaveAttribute("href", "https://example.com/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(fireEvent.click(link)).toBe(true);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
  it("opens a shared right-click menu without loading any website beforehand", async () => {
    const open = vi.fn();
    const { container } = render(<WebPreviewContext.Provider value={open}><WebLink href="https://example.com/?a=b#c">Example</WebLink></WebPreviewContext.Provider>);
    expect(container.querySelector("iframe")).toBeNull();
    fireEvent.contextMenu(screen.getByRole("link", { name: "Example" }));
    expect(screen.getAllByRole("menuitem")).toHaveLength(3);
    expect(screen.queryByText("example.com")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("menuitem", { name: "Preview website" }));
    expect(open).toHaveBeenCalledWith("https://example.com/?a=b#c");
  });
  it("supports keyboard menus and reports copy success or failure", async () => {
    render(<WebLink href="https://example.com/?q=one#two">Example</WebLink>);
    fireEvent.keyDown(screen.getByRole("link", { name: "Example" }), { key: "F10", shiftKey: true });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Copy link" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Link copied"));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Example" })).toHaveFocus();
    expect(copyTextToClipboard).toHaveBeenCalledWith("https://example.com/?q=one#two");
    expect(screen.queryByRole("menuitem", { name: "Preview website" })).not.toBeInTheDocument();
    vi.mocked(copyTextToClipboard).mockResolvedValue(false);
    fireEvent.keyDown(screen.getByRole("link", { name: "Example" }), { key: "ContextMenu" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Copy link" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not copy link"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    vi.mocked(copyTextToClipboard).mockResolvedValue(true);
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy link" }));
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });
  it("ignores a late copy completion after the user reopens the menu", async () => {
    let finish!: (result: boolean) => void;
    vi.mocked(copyTextToClipboard).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(<WebLink href="https://example.com/">Example</WebLink>);
    const link = screen.getByRole("link", { name: "Example" });
    fireEvent.contextMenu(link);
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy link" }));
    await userEvent.setup().keyboard("{Escape}");
    fireEvent.contextMenu(link);
    await act(async () => finish(true));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
  it("closes with Escape and restores focus, without stealing an outside click", async () => {
    const user = userEvent.setup();
    render(<><WebLink href="https://example.com/">Example</WebLink><button>Elsewhere</button></>);
    const link = screen.getByRole("link", { name: "Example" });
    fireEvent.keyDown(link, { key: "F10", shiftKey: true });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(link).toHaveFocus());
    fireEvent.contextMenu(link);
    // Radix's modal menu disables hit testing on underlying controls. A real
    // outside pointer first dismisses the menu rather than activating that control.
    // Its document listener is deferred until the opening pointer event finishes.
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    fireEvent.pointerDown(document.body, { pointerType: "mouse", button: 0 });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(link).not.toHaveFocus();
  });
  it("leaves touch holds, native context menus and subsequent taps to the browser", async () => {
    vi.useFakeTimers();
    const onClick = vi.fn();
    render(<WebLink href="https://example.com/" onClick={onClick}>Example</WebLink>);
    const link = screen.getByRole("link", { name: "Example" });
    fireEvent.pointerDown(link, { pointerId: 1, pointerType: "touch", isPrimary: true, button: 0, clientX: 100, clientY: 150 });
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(fireEvent.contextMenu(link)).toBe(true);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(link.className).not.toContain("touch-callout");
    fireEvent.pointerUp(link, { pointerId: 1, pointerType: "touch" });
    expect(fireEvent.click(link)).toBe(true);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
  it("still supports a mouse and keyboard after touch on a hybrid device", () => {
    render(<WebLink href="https://example.com/">Example</WebLink>);
    const link = screen.getByRole("link", { name: "Example" });
    fireEvent.pointerDown(link, { pointerType: "touch" });
    fireEvent.pointerDown(link, { pointerType: "mouse", button: 2 });
    expect(fireEvent.contextMenu(link)).toBe(false);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    fireEvent.pointerDown(link, { pointerType: "touch" });
    fireEvent.keyDown(link, { key: "F10", shiftKey: true });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
  it("leaves a coarse-pointer context menu native even without a preceding pointer event", () => {
    const original = window.matchMedia;
    const media = vi.spyOn(window, "matchMedia").mockImplementation(query => ({ ...original(query), matches: query === "(pointer: coarse)" }));
    render(<WebLink href="https://example.com/">Example</WebLink>);
    expect(fireEvent.contextMenu(screen.getByRole("link", { name: "Example" }))).toBe(true);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    media.mockRestore();
  });
  it("discards an open menu when its URL changes", () => {
    const view = (href: string) => <WebLink href={href}>Example</WebLink>;
    const { rerender } = render(view("https://example.com/old"));
    fireEvent.contextMenu(screen.getByRole("link", { name: "Example" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    rerender(view("https://example.com/third"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
  it("does not add web actions for mail, files or executable addresses", () => {
    render(<><WebLink href="mailto:test@example.com">Mail</WebLink><WebLink href="javascript:alert(1)">Unsafe</WebLink><WebLink href="file:///notes">File</WebLink></>);
    expect(screen.getByRole("link", { name: "Mail" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Unsafe" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

it("keeps file and website tabs per session, clears them on deletion, and never persists URLs", () => {
  const store = new FilePreviewStore();
  const local = vi.spyOn(Storage.prototype, "setItem");
  function View({ session }: { session: string }) {
    const { state, openWeb, openFile } = useFilePreviewState(session, store);
    return <><output>{state.tabs.find((tab) => tab.id === state.activeId)?.value ?? "closed"}</output><button onClick={() => openWeb("https://example.com/preview")}>Web</button><button onClick={() => openFile("notes.txt")}>File</button></>;
  }
  const { rerender } = render(<View session="a" />);
  fireEvent.click(screen.getByText("Web"));
  rerender(<View session="b" />);
  expect(screen.getByRole("status")).toHaveTextContent("closed");
  fireEvent.click(screen.getByText("File"));
  rerender(<View session="a" />);
  expect(screen.getByRole("status")).toHaveTextContent("https://example.com/preview");
  fireEvent.click(screen.getByText("File"));
  expect(store.get("a").activeId).toBe("file:notes.txt");
  expect(store.get("a").tabs).toHaveLength(2);
  fireEvent.click(screen.getByText("Web"));
  expect(store.get("a").activeId).toBe("web:https://example.com/preview");
  expect(store.get("a").tabs).toHaveLength(2);
  act(() => store.delete("a"));
  expect(screen.getByRole("status")).toHaveTextContent("closed");
  act(() => store.clear());
  expect(store.get("b").tabs).toEqual([]);
  expect(local).not.toHaveBeenCalled();
});
