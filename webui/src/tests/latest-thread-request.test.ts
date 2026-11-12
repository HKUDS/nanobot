import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";
import { NanobotClient } from "@/lib/nanobot-client";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import type { WebuiThreadPersistedPayload } from "@/lib/types";

const KEY = "websocket:shared";

function connectedClient(url: string): NanobotClient {
  const socket = { readyState: 1, onopen: null as (() => void) | null, send() {}, close() {} };
  const client = new NanobotClient({ url, reconnect: false, socketFactory: () => socket as unknown as WebSocket });
  client.connect();
  socket.onopen?.();
  return client;
}

function cachedThread(revision = "cached"): WebuiThreadPersistedPayload {
  return { schemaVersion: 1, projection: "events", events: [], revision };
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((finish) => { resolve = finish; });
  return { promise, resolve };
}

afterEach(() => {
  vi.unstubAllGlobals();
  webuiThreadCache.clear();
});

describe("shared latest thread requests", () => {
  it("shares a conditional read and lets one consumer cancel while another receives the owning 304 body", async () => {
    const client = connectedClient("ws://host");
    const body = cachedThread();
    webuiThreadCache.set(KEY, body);
    const read = deferredResponse();
    const fetchMock = vi.fn().mockReturnValue(read.promise);
    vi.stubGlobal("fetch", fetchMock);
    const mounted = new AbortController();
    const first = fetchLatestWebuiThread(client, "token", KEY, mounted.signal);
    const surviving = fetchLatestWebuiThread(client, "token", KEY);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Ashared/webui-thread?limit=40&direction=latest",
      expect.objectContaining({ headers: { Authorization: "Bearer token", "If-None-Match": '"cached"' } }),
    );
    const rejected = expect(first).rejects.toMatchObject({ name: "AbortError" });
    mounted.abort();
    await rejected;
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
    read.resolve(new Response(null, { status: 304 }));
    await expect(surviving).resolves.toBe(body);
  });

  it("aborts the network after its final consumer cancels and starts a new read for recovery", async () => {
    const client = connectedClient("ws://host");
    const reads = [deferredResponse(), deferredResponse()];
    const fetchMock = vi.fn().mockReturnValueOnce(reads[0].promise).mockReturnValueOnce(reads[1].promise);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const cancelled = fetchLatestWebuiThread(client, "token", KEY, controller.signal);
    const rejected = expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await rejected;
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    const recovered = fetchLatestWebuiThread(client, "token", KEY);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const body = cachedThread("new");
    for (const read of reads) read.resolve(new Response(JSON.stringify(body), { status: 200 }));
    await expect(recovered).resolves.toEqual(body);
  });

  it.each(["thread update", "turn end"] as const)("replaces surviving reads only for their own chat's %s", async (invalidation) => {
    const socket = {
      readyState: 1, onopen: null as (() => void) | null,
      onmessage: null as ((event: MessageEvent) => void) | null, send() {}, close() {},
    };
    const client = new NanobotClient({ url: "ws://host", reconnect: false, socketFactory: () => socket as unknown as WebSocket });
    client.connect();
    socket.onopen?.();
    const reads = [deferredResponse(), deferredResponse()];
    const fetchMock = vi.fn().mockReturnValueOnce(reads[0].promise).mockReturnValueOnce(reads[1].promise);
    vi.stubGlobal("fetch", fetchMock);
    const first = fetchLatestWebuiThread(client, "token", KEY);
    const surviving = fetchLatestWebuiThread(client, "token", KEY);
    const receive = (chatId: string, scope: string) => socket.onmessage?.({
      data: JSON.stringify({ event: "session_updated", chat_id: chatId, scope }),
    } as MessageEvent);
    receive("shared", "metadata");
    receive("another-chat", "thread");
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false);
    if (invalidation === "thread update") receive("shared", "thread");
    else socket.onmessage?.({
      data: JSON.stringify({ event: "turn_end", chat_id: "shared", turn_id: "turn-shared" }),
    } as MessageEvent);
    const fresh = fetchLatestWebuiThread(client, "token", KEY);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const body = cachedThread("complete");
    reads[0].resolve(new Response(JSON.stringify(cachedThread("stale")), { status: 200 }));
    reads[1].resolve(new Response(JSON.stringify(body), { status: 200 }));
    await Promise.all([first, surviving, fresh].map((read) => expect(read).resolves.toEqual(body)));
  });

  it("keeps host clients and renewed credentials in separate reads", async () => {
    const firstHost = connectedClient("ws://first-host");
    const secondHost = connectedClient("ws://second-host");
    const reads = [deferredResponse(), deferredResponse(), deferredResponse()];
    const fetchMock = vi.fn()
      .mockReturnValueOnce(reads[0].promise)
      .mockReturnValueOnce(reads[1].promise)
      .mockReturnValueOnce(reads[2].promise);
    vi.stubGlobal("fetch", fetchMock);
    const requests = [
      fetchLatestWebuiThread(firstHost, "old-token", KEY),
      fetchLatestWebuiThread(firstHost, "new-token", KEY),
      fetchLatestWebuiThread(secondHost, "old-token", KEY),
    ];
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const read of reads) read.resolve(new Response(JSON.stringify(cachedThread()), { status: 200 }));
    await Promise.all(requests);
  });

  it("does not join a pending read after a newer canonical page changes its cached baseline", async () => {
    const client = connectedClient("ws://host");
    const oldBody = cachedThread("old");
    const newBody = cachedThread("new");
    webuiThreadCache.set(KEY, oldBody);
    const reads = [deferredResponse(), deferredResponse()];
    const fetchMock = vi.fn().mockReturnValueOnce(reads[0].promise).mockReturnValueOnce(reads[1].promise);
    vi.stubGlobal("fetch", fetchMock);
    const oldRead = fetchLatestWebuiThread(client, "token", KEY);
    webuiThreadCache.set(KEY, newBody);
    const newRead = fetchLatestWebuiThread(client, "token", KEY);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const read of reads) read.resolve(new Response(null, { status: 304 }));
    await expect(oldRead).resolves.toBe(oldBody);
    await expect(newRead).resolves.toBe(newBody);
  });
});
