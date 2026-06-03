export const DEFAULT_HTTP_TIMEOUT_MS = 20_000;

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_HTTP_TIMEOUT_MS,
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return fetch(input, init);
  }

  const controller = typeof AbortController !== "undefined"
    ? new AbortController()
    : null;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const request = fetch(input, {
    ...init,
    signal: controller?.signal ?? init.signal,
  });
  const timeout = new Promise<Response>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(`Request timed out after ${timeoutMs}ms`));
      controller?.abort();
    }, timeoutMs);
  });

  try {
    return await Promise.race([request, timeout]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
}
