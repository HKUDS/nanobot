/** Mirrors nanobot/channels/websocket.py outbound payloads. */

export type ReadyEvent = {
  event: "ready";
  chat_id: string;
  client_id: string;
};

export type MessageEvent = {
  event: "message";
  text: string;
  media?: unknown;
  reply_to?: unknown;
};

export type DeltaEvent = {
  event: "delta";
  text: string;
  stream_id?: number | string;
};

export type StreamEndEvent = {
  event: "stream_end";
  stream_id?: number | string;
};

export type ParsedServerPayload =
  | ReadyEvent
  | MessageEvent
  | DeltaEvent
  | StreamEndEvent;

export function tryParseServerPayload(raw: string): ParsedServerPayload | null {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("{")) {
    return null;
  }
  try {
    const data = JSON.parse(trimmed) as unknown;
    if (data && typeof data === "object" && !Array.isArray(data) && "event" in data) {
      return data as ParsedServerPayload;
    }
    return null;
  } catch {
    return null;
  }
}

export function summarizeServerPayload(parsed: ParsedServerPayload): string {
  switch (parsed.event) {
    case "ready":
      return `ready · chat_id=${parsed.chat_id} · client_id=${parsed.client_id}`;
    case "message": {
      const extras: string[] = [];
      if (parsed.media !== undefined) {
        extras.push("media");
      }
      if (parsed.reply_to !== undefined) {
        extras.push("reply_to");
      }
      const suffix = extras.length ? ` · [${extras.join(", ")}]` : "";
      const preview =
        parsed.text.length > 120 ? `${parsed.text.slice(0, 120)}…` : parsed.text;
      return `message · ${preview}${suffix}`;
    }
    case "delta": {
      const sid =
        parsed.stream_id !== undefined ? ` stream_id=${String(parsed.stream_id)}` : "";
      const preview =
        parsed.text.length > 80 ? `${parsed.text.slice(0, 80)}…` : parsed.text;
      return `delta${sid} · ${preview}`;
    }
    case "stream_end": {
      const sid =
        parsed.stream_id !== undefined ? ` stream_id=${String(parsed.stream_id)}` : "";
      return `stream_end${sid}`;
    }
    default: {
      const unknownEvent: string = (parsed as { event: string }).event;
      return unknownEvent;
    }
  }
}
