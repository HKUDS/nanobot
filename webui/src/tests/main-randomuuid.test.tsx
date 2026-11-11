import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NanobotClient } from "@/lib/nanobot-client";

const render = vi.fn();
const createRoot = vi.fn(() => ({ render }));

vi.mock("react-dom/client", () => ({
  default: { createRoot },
}));

vi.mock("@/App", () => ({
  default: () => null,
}));

describe("main entry crypto shim", () => {
  const originalRandomUUID = globalThis.crypto.randomUUID;

  beforeEach(() => {
    vi.resetModules();
    createRoot.mockClear();
    render.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
    Reflect.deleteProperty(globalThis.crypto, "randomUUID");
  });

  afterEach(() => {
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      value: originalRandomUUID,
      configurable: true,
    });
    document.body.innerHTML = "";
  });

  it("installs a randomUUID fallback when the browser omits it", async () => {
    await import("../main");

    expect(globalThis.crypto.randomUUID).toEqual(expect.any(Function));
    expect(globalThis.crypto.randomUUID()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    await waitFor(() => {
      expect(createRoot).toHaveBeenCalledWith(document.getElementById("root"));
    });
  });

  it("creates and forks chats when WebUI starts without native randomUUID", async () => {
    await import("../main");

    const socket = {
      readyState: 1,
      onopen: null as (() => void) | null,
      onmessage: null as ((event: MessageEvent) => void) | null,
      onerror: null,
      onclose: null,
      sent: [] as string[],
      send(frame: string) { this.sent.push(frame); },
      close() {},
    };
    const client = new NanobotClient({
      url: "ws://test",
      socketFactory: () => socket as unknown as WebSocket,
    });
    client.connect();
    socket.onopen?.();

    try {
      for (const [type, start] of [
        ["new_chat", () => client.newChat()],
        ["new_temporary_chat", () => client.newTemporaryChat()],
        ["fork_chat", () => client.forkChat("source", 1)],
      ] as const) {
        const result = start();
        const frame = JSON.parse(socket.sent.at(-1)!) as { type: string; request_id: string };
        expect(frame.type).toBe(type);
        expect(frame.request_id).toMatch(/^[A-Za-z0-9._:-]{1,128}$/);
        socket.onmessage?.({ data: JSON.stringify({
          event: "attached", chat_id: `${type}-id`, request_id: frame.request_id,
          temporary: type === "new_temporary_chat",
        }) } as MessageEvent);
        await expect(result).resolves.toBe(`${type}-id`);
      }
    } finally {
      client.close();
    }
  });
});
