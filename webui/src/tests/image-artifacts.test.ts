import { describe, expect, it } from "vitest";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { projectActivityTimeline } from "@/lib/activity-timeline";
import type { ThreadProjectionEvent } from "@/lib/types";

const user: ThreadProjectionEvent = { event: "user_message", chat_id: "fixture", turn_id: "turn-1",
  text: "Make an image", starts_turn: true };
const image: ThreadProjectionEvent = { event: "message", kind: "artifacts", chat_id: "fixture",
  turn_id: "turn-1", text: "", media_urls: [{ url: "/api/media/fixture/image.png", name: "image.png" }] };
const answer: ThreadProjectionEvent = { event: "message", chat_id: "fixture", turn_id: "turn-1",
  text: "Here is the completed image." };

describe("typed image deliverables", () => {
  it("keeps later reasoning and answer streaming, and displays images at the turn footer", () => {
    const events: ThreadProjectionEvent[] = [user, image,
      { event: "reasoning_delta", chat_id: "fixture", turn_id: "turn-1", text: "Checking output" },
      { event: "delta", chat_id: "fixture", turn_id: "turn-1", text: "Here is" },
      { event: "delta", chat_id: "fixture", turn_id: "turn-1", text: " the completed image." },
      { event: "stream_end", chat_id: "fixture", turn_id: "turn-1" },
      { event: "turn_end", chat_id: "fixture", turn_id: "turn-1" }];
    const messages = projectThreadEvents(events);
    expect(messages.some((message) => message.content.includes("completed image"))).toBe(true);
    const last = projectActivityTimeline(messages).at(-1)!;
    expect(last.type).toBe("message");
    if (last.type !== "message") throw new Error("missing answer");
    expect(last.message.content).toBe(answer.text);
    expect(last.message.media).toHaveLength(1);
  });

  it("deduplicates repeated delivery and an explicit media message", () => {
    const messages = projectThreadEvents([user, image, image, { ...answer, media_urls: image.media_urls }]);
    const units = projectActivityTimeline(messages);
    const media = units.flatMap((unit) => unit.type === "message" ? unit.message.media ?? [] : []);
    expect(media).toHaveLength(1);
  });

  it("does not duplicate a Markdown image or move an artifact to the next turn", () => {
    const messages = projectThreadEvents([user, image, { ...answer,
      text: "![Output](/api/media/fixture/image.png)" },
      { ...user, turn_id: "turn-2", text: "Another question" },
      { ...answer, turn_id: "turn-2", text: "Unrelated answer" }]);
    const units = projectActivityTimeline(messages);
    expect(units.flatMap((unit) => unit.type === "message" ? unit.message.media ?? [] : [])).toHaveLength(0);
  });

  it("keeps a completed artifact when the turn is stopped before a final answer", () => {
    const messages = projectThreadEvents([user, image,
      { event: "turn_end", chat_id: "fixture", turn_id: "turn-1", outcome: "cancelled" }]);
    const last = projectActivityTimeline(messages).at(-1)!;
    expect(last.type === "message" && last.message.media?.length).toBe(1);
  });
});
