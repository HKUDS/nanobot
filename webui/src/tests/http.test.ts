import { afterEach, expect, it, vi } from "vitest";

import { fetchWithTimeout, readResponseWithTimeout } from "@/lib/http";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("preserves the raw Response contract without consuming its body", async () => {
  vi.useFakeTimers();
  const response = { ok: true, json: vi.fn() } as unknown as Response;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  const controller = new AbortController();
  expect(await fetchWithTimeout("/raw-response", { signal: controller.signal })).toBe(response);
  expect(response.json).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["raw", "consumed"])("leaves a disabled timeout's original signal attached through body consumption (%s)", async (mode) => {
  const controller = new AbortController();
  let finish!: () => void;
  let bodyStopped = false;
  vi.stubGlobal("fetch", vi.fn(async (_input, init: RequestInit) => ({
    json: () => new Promise<void>((_resolve, reject) => {
      finish = () => { bodyStopped = true; reject(new DOMException("Aborted", "AbortError")); };
      init.signal!.addEventListener("abort", finish, { once: true });
    }),
  }) as Response));
  const init = { signal: controller.signal };
  const response = mode === "raw" ? await fetchWithTimeout("/no-timeout", init, 0)
    : await readResponseWithTimeout("/no-timeout", init, async (response) => response, 0);
  expect(fetch).toHaveBeenCalledWith("/no-timeout", init);
  const body = response.json();
  const rejected = expect(body).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  await rejected;
  expect(bodyStopped).toBe(true);
});

it("releases the timeout and external listener only after the body has finished", async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  let transportSignal!: AbortSignal;
  let finish!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn(async (_input, init: RequestInit) => {
    transportSignal = init.signal!;
    return { json: () => new Promise((resolve) => { finish = resolve; }) } as Response;
  }));
  const read = readResponseWithTimeout("/slow-body", { signal: controller.signal }, (response) => response.json());
  await vi.advanceTimersByTimeAsync(0);
  expect(vi.getTimerCount()).toBe(1);
  finish({ complete: true });
  await expect(read).resolves.toEqual({ complete: true });
  expect(vi.getTimerCount()).toBe(0);
  controller.abort();
  expect(transportSignal.aborted).toBe(false);
});
