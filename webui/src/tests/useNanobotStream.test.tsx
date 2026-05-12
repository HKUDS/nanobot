import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import type { InboundEvent } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

const EMPTY_MESSAGES: import("@/lib/types").UIMessage[] = [];

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
  it("starts in streaming mode when history shows pending tool calls", () => {
    const fake = fakeClient();
    const initialMessages = [{
      id: "m1",
      role: "assistant" as const,
      content: "Using tools",
      createdAt: Date.now(),
    }];
    const { result } = renderHook(
      () => useNanobotStream("chat-p", initialMessages, true),
      {
        wrapper: wrap(fake.client),
      },
    );

    expect(result.current.isStreaming).toBe(true);
  });

  it("collapses consecutive tool_hint frames into one trace row", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-t", EMPTY_MESSAGES), {
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
    const { result } = renderHook(() => useNanobotStream("chat-m", EMPTY_MESSAGES), {
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

  it("reports runtime model name updates from message frames", () => {
    const fake = fakeClient();
    const onModelNameChange = vi.fn();
    renderHook(
      () => useNanobotStream("chat-model", EMPTY_MESSAGES, false, undefined, onModelNameChange),
      {
        wrapper: wrap(fake.client),
      },
    );

    act(() => {
      fake.emit("chat-model", {
        event: "message",
        chat_id: "chat-model",
        text: "Switched model preset to `fast`.",
        model_name: "openai/gpt-4.1",
      });
    });

    expect(onModelNameChange).toHaveBeenCalledWith("openai/gpt-4.1");
  });

  it("suppresses redundant stream confirmation after assistant media", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-img-result", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-img-result", {
        event: "message",
        chat_id: "chat-img-result",
        text: "image ready",
        media_urls: [{ url: "/api/media/sig/image", name: "generated.png" }],
      });
      fake.emit("chat-img-result", {
        event: "message",
        chat_id: "chat-img-result",
        text: "message()",
        kind: "tool_hint",
      });
      fake.emit("chat-img-result", {
        event: "delta",
        chat_id: "chat-img-result",
        text: "发送成功",
      });
      fake.emit("chat-img-result", {
        event: "stream_end",
        chat_id: "chat-img-result",
      });
      fake.emit("chat-img-result", {
        event: "turn_end",
        chat_id: "chat-img-result",
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("image ready");
    expect(result.current.messages[0].media).toHaveLength(1);
  });

  it("passes image generation options to the websocket client", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-img", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send(
        "draw a square icon",
        undefined,
        { imageGeneration: { enabled: true, aspect_ratio: "1:1" } },
      );
    });

    expect(fake.client.sendMessage).toHaveBeenCalledWith(
      "chat-img",
      "draw a square icon",
      undefined,
      { imageGeneration: { enabled: true, aspect_ratio: "1:1" } },
    );
  });

  it("stops the active turn without adding a user slash command bubble", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-stop", EMPTY_MESSAGES), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      result.current.send("long task");
    });
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.isStreaming).toBe(true);

    act(() => {
      result.current.stop();
    });

    expect(fake.client.sendMessage).toHaveBeenLastCalledWith("chat-stop", "/stop");
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("long task");
  });

  it("keeps assistant buttons on complete messages", () => {
    const fake = fakeClient();
    const { result } = renderHook(() => useNanobotStream("chat-q", EMPTY_MESSAGES), {
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

  it("keeps streaming alive across stream_end and completes on turn_end", () => {
    const fake = fakeClient();
    const onTurnEnd = vi.fn();
    const { result } = renderHook(() => useNanobotStream("chat-s", EMPTY_MESSAGES, false, onTurnEnd), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-s", {
        event: "delta",
        chat_id: "chat-s",
        text: "Hello",
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0]).toMatchObject({
      role: "assistant",
      content: "Hello",
      isStreaming: true,
    });

    act(() => {
      fake.emit("chat-s", {
        event: "stream_end",
        chat_id: "chat-s",
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages[0].isStreaming).toBe(true);

    act(() => {
      fake.emit("chat-s", {
        event: "message",
        chat_id: "chat-s",
        text: "Hello world",
      });
    });

    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "assistant",
      content: "Hello world",
    });

    act(() => {
      fake.emit("chat-s", {
        event: "turn_end",
        chat_id: "chat-s",
      });
    });

    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.every((message) => !message.isStreaming)).toBe(true);
    expect(onTurnEnd).toHaveBeenCalledTimes(1);
  });

  it("refreshes session metadata when the server reports a session update", () => {
    const fake = fakeClient();
    const onTurnEnd = vi.fn();
    renderHook(() => useNanobotStream("chat-title", EMPTY_MESSAGES, false, onTurnEnd), {
      wrapper: wrap(fake.client),
    });

    act(() => {
      fake.emit("chat-title", {
        event: "session_updated",
        chat_id: "chat-title",
      });
    });

    expect(onTurnEnd).toHaveBeenCalledTimes(1);
  });
});
