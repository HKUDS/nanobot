import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HOST_BRIDGE, isLocalShellOrigin, readHostAnchor } from "@/components/remote/host-bridge";
import { useSidebarHostBridge } from "@/components/remote/useSidebarHostBridge";
import type { HostFrame } from "@/components/remote/useHostSessions";
const origin = "http://127.0.0.1:23456";
const makeFrame = (id = "host-a"): HostFrame => ({
  connection: { id, name: "Team server", host: "private-ssh-alias", hostname: "team-host", config_path: "/private/config.json", gateway_id: "gateway-1", url: `${origin}/#/?bootstrapSecret=never-share-this` },
  loaded: true, offline: false, failures: 0,
});
const rect = { left: 60, top: 600, width: 120, height: 32 };
function addFrame() {
  const node = document.createElement("iframe");
  // A detached frame avoids loading a page in the unit-test environment.
  Object.defineProperty(node, "contentWindow", { value: { postMessage: vi.fn() } });
  vi.spyOn(node, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 20, 800, 800));
  return node;
}
function send(source: Window, data: Record<string, unknown>, from = origin) {
  act(() => { window.dispatchEvent(new MessageEvent("message", { source, origin: from, data: { channel: HOST_BRIDGE, ...data } })); });
}
function parentView() {
  const node = addFrame();
  const source = node.contentWindow!;
  const post = vi.spyOn(source, "postMessage").mockImplementation(() => {});
  const nodes = { current: new Map([["host-a", node]]) };
  const restore = vi.fn();
  const hook = renderHook(({ selectedId }) => useSidebarHostBridge([makeFrame()], selectedId, nodes, restore, {}), {
    initialProps: { selectedId: "host-a" as string | undefined },
  });
  send(source, { type: "hello" });
  const init = post.mock.calls[0][0] as Record<string, unknown>;
  return { ...hook, node, source, post, init, restore };
}
afterEach(() => { cleanup(); document.querySelectorAll("iframe").forEach((node) => node.remove()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("sidebar host bridge", () => {
  it("sends only current display identity, never secrets, profiles or filesystem paths", () => {
    const { post, init } = parentView();
    expect(post).toHaveBeenCalledWith(expect.objectContaining({ type: "init", name: "Team server", hostname: "team-host" }), origin);
    const json = JSON.stringify(init);
    expect(json).not.toContain("never-share-this");
    expect(json).not.toContain("config.json");
    expect(json).not.toContain("private-ssh-alias");
    expect(init).not.toHaveProperty("profiles");
  });

  it("requires matching source, origin and nonce before enabling the sidebar or opening its menu", () => {
    const { source, init, result } = parentView();
    send(source, { type: "ready", nonce: "wrong" });
    send(source, { type: "ready", nonce: init.nonce }, "https://attacker.example");
    send(window, { type: "ready", nonce: init.nonce });
    expect(result.current.readyIds).toEqual([]);
    send(source, { type: "ready", nonce: init.nonce });
    expect(result.current.readyIds).toEqual(["host-a"]);
    send(source, { type: "open", nonce: init.nonce, anchor: rect });
    expect(result.current.anchor).toEqual({ ...rect, left: 70, top: 620 });
  });

  it("ignores inactive frames and does not accept commands to connect, disconnect or navigate", () => {
    const { source, init, result, rerender } = parentView();
    for (const type of ["connect", "disconnect", "select", "navigate"]) send(source, { type, nonce: init.nonce, id: "another-host", url: "https://attacker.example" });
    expect(result.current.anchor).toBeNull();
    rerender({ selectedId: undefined });
    send(source, { type: "open", nonce: init.nonce, anchor: rect });
    expect(result.current.anchor).toBeNull();
  });

  it("rejects invalid anchor values without opening a menu", () => {
    const { source, init, result } = parentView();
    send(source, { type: "open", nonce: init.nonce, anchor: { ...rect, top: NaN } });
    expect(result.current.anchor).toBeNull();
    expect(readHostAnchor({ ...rect, width: -1 })).toBeNull();
    expect(readHostAnchor({ ...rect, left: "0" })).toBeNull();
  });

  it("restores remote focus only through a verified sidebar bridge", () => {
    const { source, init, result, post } = parentView();
    send(source, { type: "ready", nonce: init.nonce });
    act(() => result.current.focus("host-a"));
    expect(post).toHaveBeenLastCalledWith({ channel: HOST_BRIDGE, type: "focus", nonce: init.nonce }, origin);
  });

  it("embedded mode trusts only its loopback parent and pins the handshake", () => {
    const parent = addFrame().contentWindow!;
    const post = vi.spyOn(parent, "postMessage").mockImplementation(() => {});
    vi.stubGlobal("parent", parent);
    const restore = vi.fn();
    const nodes = { current: new Map<string, HTMLIFrameElement>() };
    const { result } = renderHook(() => useSidebarHostBridge([], undefined, nodes, restore, {}));
    expect(post).toHaveBeenCalledWith({ channel: HOST_BRIDGE, type: "hello" }, "*");
    const nonce = crypto.randomUUID();
    const init = { type: "init", nonce, name: "Team server", hostname: "team-host" };
    send(parent, init, "https://attacker.example");
    send(window, init, "http://127.0.0.1:8870");
    expect(result.current.embedded).toBeNull();
    send(parent, init, "http://127.0.0.1:8870");
    expect(result.current.embedded?.name).toBe("Team server");
    act(() => result.current.embedded?.open(rect));
    expect(post).toHaveBeenLastCalledWith({ channel: HOST_BRIDGE, type: "open", nonce, anchor: rect }, "http://127.0.0.1:8870");
    send(parent, { ...init, name: "Spoofed", nonce: crypto.randomUUID() }, "http://127.0.0.1:8870");
    expect(result.current.embedded?.name).toBe("Team server");
    send(parent, { type: "focus", nonce }, "http://127.0.0.1:8870");
    expect(restore).toHaveBeenCalledOnce();
  });

  it.each(["null", "https://example.com", "http://127.0.0.1.evil.test", "file:///tmp/page", "http://127.0.0.1:8870/path"])("rejects non-shell origin %s", (value) => {
    expect(isLocalShellOrigin(value)).toBe(false);
  });
});
