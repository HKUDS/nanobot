import { afterEach, describe, expect, it, vi } from "vitest";
import { NanobotClient } from "@/lib/nanobot-client";

import { linearWorkspaceStore } from "../../../nanobot/channels/linear/webui/workspace-store";

const installation = { organization_id: "org-1", organization_name: "nanobot" };
const logo = "https://public.linear.app/org-1/logo";
function fixture() {
  // Keep the real generic transport type; this client is never connected.
  const client = new NanobotClient({ url: "ws://preview.invalid", reconnect: false });
  const requestMutation = vi.spyOn(client, "requestMutation").mockImplementation(async (_action, params) =>
    params?.operation === "inspect"
      ? { installations: [installation] }
      : { organization_id: "org-1", logo_url: logo });
  const store = linearWorkspaceStore(client, "session", "app");
  return { requestMutation, client, store };
}
afterEach(() => vi.restoreAllMocks());

describe("Linear workspace display cache", () => {
  it("publishes the workspace before the logo arrives and caches both on reopen", async () => {
    const { requestMutation, client, store } = fixture();
    let finish!: (value: unknown) => void;
    requestMutation.mockImplementation(async (_action, params) => params?.operation === "inspect"
      ? { installations: [installation] } : new Promise(resolve => { finish = resolve; }));
    await store.load();
    expect(store.getSnapshot().installations).toEqual([installation]);
    expect(store.getSnapshot().loading).toBe(false);
    expect(store.getSnapshot().logos).toEqual({});
    finish({ organization_id: "org-1", logo_url: logo });
    await vi.waitFor(() => expect(store.getSnapshot().logos["org-1"]).toBe(logo));
    const reopened = linearWorkspaceStore(client, "session", "app");
    expect(reopened).toBe(store);
    await reopened.load();
    expect(requestMutation).toHaveBeenCalledTimes(2);
  });

  it("keeps stale workspaces visible while refreshing and after a failed refresh", async () => {
    const { requestMutation, store } = fixture();
    await store.load();
    await vi.waitFor(() => expect(store.getSnapshot().logos["org-1"]).toBe(logo));
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 61_000);
    let fail!: (error: Error) => void;
    requestMutation.mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    const refresh = store.load();
    expect(store.getSnapshot().installations).toEqual([installation]);
    expect(store.getSnapshot().logos["org-1"]).toBe(logo);
    expect(store.getSnapshot().loading).toBe(true);
    fail(new Error("Offline"));
    await refresh;
    expect(store.getSnapshot().installations).toEqual([installation]);
    expect(store.getSnapshot().error).toBe("Offline");
  });

  it("does not let an old read resurrect a disconnected workspace", async () => {
    const { requestMutation, store } = fixture();
    let finish!: (value: unknown) => void;
    requestMutation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const load = store.load();
    store.replace([]);
    finish({ installations: [installation] });
    await load;
    expect(store.getSnapshot().installations).toEqual([]);
    expect(requestMutation).toHaveBeenCalledTimes(1);
  });

  it("ignores a late logo after disconnect and treats a removed logo as empty", async () => {
    const { requestMutation, store } = fixture();
    let finish!: (value: unknown) => void;
    requestMutation.mockImplementation(async (_action, params) => params?.operation === "inspect"
      ? { installations: [installation] } : new Promise(resolve => { finish = resolve; }));
    await store.load();
    store.replace([]);
    finish({ organization_id: "org-1", logo_url: logo });
    await Promise.resolve();
    expect(store.getSnapshot().logos).toEqual({});
    requestMutation.mockImplementation(async (_action, params) => params?.operation === "inspect"
      ? { installations: [installation] } : { organization_id: "org-1", logo_url: null });
    await store.load(true);
    await vi.waitFor(() => expect(store.getSnapshot().logos).toEqual({ "org-1": null }));
  });

  it("keeps usable workspaces when their optional profile fails", async () => {
    const { requestMutation, store } = fixture();
    requestMutation.mockImplementation(async (_action, params) => {
      if (params?.operation === "inspect") return { installations: [installation] };
      throw new Error("Profile unavailable");
    });
    await store.load();
    await Promise.resolve();
    expect(store.getSnapshot().installations).toEqual([installation]);
    expect(store.getSnapshot().error).toBeNull();
    expect(store.getSnapshot().logos).toEqual({});
  });

  it("isolates gateways, admin sessions, and app configurations", async () => {
    const { client, store } = fixture();
    await store.load();
    expect(linearWorkspaceStore({ requestMutation: client.requestMutation }, "session", "app").getSnapshot().installations).toBeNull();
    expect(linearWorkspaceStore(client, "session", "other-app").getSnapshot().installations).toBeNull();
    expect(linearWorkspaceStore(client, "other-session", "app").getSnapshot().installations).toBeNull();
  });

  it("deduplicates pending inspections and notifies subscribers", async () => {
    const { requestMutation, store } = fixture();
    let finish!: (value: unknown) => void;
    requestMutation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    const pending = store.load();
    await store.load();
    expect(requestMutation).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledOnce();
    finish({ installations: [] });
    await pending;
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    store.replace([]);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
