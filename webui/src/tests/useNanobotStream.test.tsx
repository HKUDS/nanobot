import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import type { InboundEvent } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

function fakeClient() {
  const handlers = new Map<string, Set<(ev: InboundEvent) => void>>();
  return {
    client: {
      status: "open" as const,
      defaultChatId: null as string | null,
      onStatus: () => () => {},
      onError: () => () => {},
      onChat(chatId: string, h: (ev: InboundEvent) => void) {
        let set = handlers.get(chatId);
        if (!set) {
          set = new Set();
          handlers.set(chatId, set);
        }
        set.add(h);
        return () => set!.delete(h);
      },
      sendMessage: vi.fn(),
      newChat: vi.fn(),
      attach: vi.fn(),
      connect: vi.fn(),
      close: vi.fn(),
      updateUrl: vi.fn(),
    },
    emit(chatId: string, ev: InboundEvent) {
      const set = handlers.get(chatId);
      set?.forEach((h) => h(ev));
    },
  };
}

function wrap(client: ReturnType<typeof fakeClient>["client"]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
        token="tok"
      >
        {children}
      </ClientProvider>
    );
  };
}

describe("useNanobotStream", () => {
  it("collapses consecutive tool_hint frames into one trace row", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-t", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: 'weather("get")',
        kind: "tool_hint",
      });
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: 'search "hk weather"',
        kind: "tool_hint",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].kind).toBe("trace");
    expect(result.current.messages[0].role).toBe("tool");
    expect(result.current.messages[0].traces).toEqual([
      'weather("get")',
      'search "hk weather"',
    ]);

    act(() => {
      fake.emit("chat-t", {
        event: "message",
        chat_id: "chat-t",
        text: "## Summary",
      });
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].kind).toBeUndefined();
  });

  it("attaches assistant media_urls to complete messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-m", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-m", {
        event: "message",
        chat_id: "chat-m",
        text: "video ready",
        media_urls: [{ url: "/api/media/sig/payload", name: "demo.mp4" }],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].media).toEqual([
      { kind: "video", url: "/api/media/sig/payload", name: "demo.mp4" },
    ]);
  });

  it("keeps assistant buttons on complete messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-q", []), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-q", {
        event: "message",
        chat_id: "chat-q",
        text: "How should I continue?\n\n1. Short answer\n2. Detailed answer",
        button_prompt: "How should I continue?",
        buttons: [["Short answer", "Detailed answer"]],
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("How should I continue?");
    expect(result.current.messages[0].buttons).toEqual([
      ["Short answer", "Detailed answer"],
    ]);
  });
});
