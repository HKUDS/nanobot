const DEFAULT_HTTP_TIMEOUT_MS = 20_000;

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
  const externalSignal = init.signal;
  const abortFromExternal = () => controller?.abort();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  if (controller && externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", abortFromExternal, { once: true });
    }
  }

  try {
    const request = fetch(input, {
      ...init,
      signal: controller?.signal ?? externalSignal,
    });
    const timeout = new Promise<Response>((_, reject) => {
      timeoutId = setTimeout(() => {
        reject(new Error(`Request timed out after ${timeoutMs}ms`));
        controller?.abort();
      }, timeoutMs);
    });
    return await Promise.race([request, timeout]);
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}

/** Own fetch and response consumption under one abort/timeout lifetime. */
export async function readResponseWithTimeout<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  read: (response: Response) => Promise<T>,
  timeoutMs: number = DEFAULT_HTTP_TIMEOUT_MS,
): Promise<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return read(await fetch(input, init));
  }

  const controller = new AbortController();
  const externalSignal = init.signal;
  const abortFromExternal = () => controller.abort();
  if (externalSignal?.aborted) controller.abort();
  else externalSignal?.addEventListener("abort", abortFromExternal, { once: true });
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    return await read(await fetch(input, { ...init, signal: controller.signal }));
  } catch (reason) {
    if (timedOut) throw new Error(`Request timed out after ${timeoutMs}ms`, { cause: reason });
    throw reason;
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}
