/**
 * Thread ID synchronization between assistant-ui local threads and the server.
 *
 * Problem: assistant-ui's useDataStreamRuntime may omit the `threadId` from the
 * first message in a new thread due to a React render timing issue (the remoteId
 * state update from initialize() hasn't propagated to the threadIdRef yet).
 * This causes the server to generate a UUID session for the first message,
 * while follow-up messages use `__LOCALID_xxx` — creating separate sessions.
 *
 * Solution: intercept fetch calls to `/api/chat` to:
 * 1. Capture the server's `X-Thread-Id` response header.
 * 2. Map local thread IDs to server-generated thread IDs.
 * 3. Replace local thread IDs with server IDs in subsequent requests.
 * 4. When the first message has no threadId, record a "pending" state so the
 *    next message (with a local ID) can be mapped to the server's UUID.
 */

const CHAT_API = "/api/chat";

/** Map from local thread ID (__LOCALID_xxx) to server thread ID (UUID). */
const threadMap = new Map<string, string>();

/** Server thread ID from the most recent request that had no local thread ID. */
let pendingServerThreadId: string | null = null;

/**
 * Install a global fetch interceptor that synchronizes thread IDs.
 * Call once at app startup (before any chat requests).
 */
export function installThreadSync(): void {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit
  ): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!url.endsWith(CHAT_API) || !init?.body) {
      return originalFetch(input, init);
    }

    let body: Record<string, unknown>;
    try {
      body = JSON.parse(init.body as string);
    } catch {
      return originalFetch(input, init);
    }

    const localThreadId = body.threadId as string | undefined;

    if (localThreadId) {
      // We have a local thread ID — check if we have a server mapping for it.
      if (threadMap.has(localThreadId)) {
        body.threadId = threadMap.get(localThreadId);
        init = { ...init, body: JSON.stringify(body) };
      } else if (pendingServerThreadId) {
        // First message had no local ID, this is the follow-up.
        // Map this local ID → the server UUID from the first message.
        threadMap.set(localThreadId, pendingServerThreadId);
        body.threadId = pendingServerThreadId;
        init = { ...init, body: JSON.stringify(body) };
        pendingServerThreadId = null;
      }
    }

    const response = await originalFetch(input, init);

    // Read the server's canonical thread ID from the response header.
    const serverThreadId = response.headers.get("x-thread-id");
    if (serverThreadId) {
      if (localThreadId) {
        // Direct mapping: local → server.
        threadMap.set(localThreadId, serverThreadId);
      } else {
        // First message had no threadId — store as pending for the next request.
        pendingServerThreadId = serverThreadId;
      }
    }

    return response;
  };
}
