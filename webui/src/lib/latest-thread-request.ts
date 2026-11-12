import { fetchWebuiThread } from "./api";
import type { NanobotClient } from "./nanobot-client";
import type { WebuiThreadPersistedPayload } from "./types";
import type { WebuiThreadCache } from "./webui-thread-cache";

interface LatestThreadRequest {
  cached: WebuiThreadPersistedPayload | undefined;
  controller: AbortController;
  promise: Promise<WebuiThreadPersistedPayload | null>;
  consumers: number;
  settled: boolean;
  shareable: boolean;
  retainOnDetach: boolean;
}

const requestsByClient = new WeakMap<NanobotClient, Map<string, LatestThreadRequest>>();
const INVALIDATED_THREAD_READ = Symbol("invalidated thread read");
const consumersBySignal = new WeakMap<AbortSignal, LatestThreadRequest>();

export function invalidateLatestThreadRead(signal: AbortSignal): void {
  const request = consumersBySignal.get(signal);
  if (request && !request.settled) request.controller.abort();
}

export function cancelLatestThreadReads(client: NanobotClient, key?: string): void {
  for (const [id, request] of requestsByClient.get(client) ?? []) {
    if (!key || (JSON.parse(id) as string[])[1] === key) request.controller.abort();
  }
}

function abortedRequest(): DOMException {
  return new DOMException("The request was aborted", "AbortError");
}

/** Share only the canonical latest 40-event page within one authenticated host. */
export function fetchSharedLatestThread(
  client: NanobotClient,
  token: string,
  key: string,
  cache: WebuiThreadCache,
  publish: (body: WebuiThreadPersistedPayload) => void,
  signal?: AbortSignal,
  retainOnDetach = true,
): Promise<WebuiThreadPersistedPayload | null> {
  if (signal?.aborted) return Promise.reject(abortedRequest());
  const requests = requestsByClient.get(client) ?? new Map<string, LatestThreadRequest>();
  requestsByClient.set(client, requests);
  const requestKey = JSON.stringify([token, key]);
  const cached = cache.get(key);
  let request = requests.get(requestKey);
  if (!request || !request.shareable || request.controller.signal.aborted || request.cached !== cached) {
    const controller = new AbortController();
    request = {
      cached,
      controller,
      consumers: 0,
      settled: false,
      shareable: client.status === "open",
      retainOnDetach,
      promise: fetchWebuiThread(token, key, {
        limit: 40,
        direction: "latest",
        signal: controller.signal,
        revision: cached?.revision,
        cached,
      }),
    };
    requests.set(requestKey, request);
    const current = request;
    let initialStatus = true;
    const unsubscribeStatus = client.onStatus((status) => {
      // Recovery must not join a read started before or during an outage.
      if (status !== "open") {
        current.shareable = false;
        if (!initialStatus) current.controller.abort();
      }
      initialStatus = false;
    });
    const unsubscribeSessionUpdate = client.onSessionUpdate((chatId, scope) => {
      if (key === `websocket:${chatId}` && scope !== "metadata") {
        current.controller.abort(INVALIDATED_THREAD_READ);
      }
    });
    const unsubscribeRunCompletion = client.onRunCompletion((chatId) => {
      if (key === `websocket:${chatId}`) current.controller.abort(INVALIDATED_THREAD_READ);
    });
    const finish = () => {
      if (current.settled) return;
      current.settled = true;
      unsubscribeStatus();
      unsubscribeSessionUpdate();
      unsubscribeRunCompletion();
      current.controller.signal.removeEventListener("abort", finish);
      if (requests.get(requestKey) === current) requests.delete(requestKey);
    };
    current.controller.signal.addEventListener("abort", finish, { once: true });
    void current.promise.then((body) => {
      if (!current.controller.signal.aborted && current.consumers === 0 && cache.peek(key) === current.cached) {
        if (body) publish(body);
        else cache.delete(key);
      }
      finish();
    }, finish);
  }
  const current = request;
  current.retainOnDetach ||= retainOnDetach;
  if (signal) consumersBySignal.set(signal, current);
  return new Promise((resolve, reject) => {
    current.consumers += 1;
    let active = true;
    const release = () => {
      if (!active) return;
      active = false;
      signal?.removeEventListener("abort", abort);
      current.controller.signal.removeEventListener("abort", abort);
      current.consumers -= 1;
      if (current.consumers === 0 && !current.settled && !current.retainOnDetach) current.controller.abort();
    };
    const abort = () => {
      release();
      if (current.controller.signal.reason === INVALIDATED_THREAD_READ) {
        // Replace the stale page after the current notification finishes so
        // all surviving consumers can join one read of its updated thread.
        resolve(Promise.resolve().then(() => fetchSharedLatestThread(client, token, key, cache, publish, signal, retainOnDetach)));
        return;
      }
      reject(abortedRequest());
    };
    signal?.addEventListener("abort", abort, { once: true });
    current.controller.signal.addEventListener("abort", abort, { once: true });
    void current.promise.then((body) => {
      if (!active) return;
      release();
      resolve(body);
    }, (error: unknown) => {
      if (!active) return;
      release();
      reject(error);
    });
  });
}
